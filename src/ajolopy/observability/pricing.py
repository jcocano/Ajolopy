"""Internal pricing catalog + cost-math helper for LLM calls.

AJ-30 ships an embedded snapshot of LiteLLM's
``model_prices_and_context_window.json`` (MIT-licensed) plus a thin
:func:`compute_cost_usd` helper that turns the ``gen_ai.usage.*_tokens``
already on every ``chat`` span into ``gen_ai.cost_usd*`` attributes. The
snapshot is bundled as ``pricing.json`` next to this module; the
``tools/sync_pricing.py`` script refreshes it from upstream and a monthly
GitHub Action opens a PR when prices drift.

Public surface:

- :class:`ModelPrice` — dataclass mirroring LiteLLM's per-tier field names.
- :class:`Catalog` — lazy snapshot loader plus override merging.
- :func:`compute_cost_usd` — tier-summed cost in USD or ``None`` for an
  unknown model. The same helper is reused by future ``@Embed`` /
  ``@Memory`` / vectorstore primitives that want cost on their spans.

**Model-name normalisation.** :meth:`Catalog.get` accepts both LiteLLM-style
keys (``"groq/llama-3.3-70b-versatile"``) and Ajolopy's universal-OpenAI
prefix syntax (``"groq:llama-3.3-70b-versatile"``). The lookup substitutes
``:`` with ``/`` and, when the prefixed key is still absent, falls back to
the bare model name (``"llama-3.3-70b-versatile"``). Native providers
(Anthropic, OpenAI, Gemini) pass their model strings unchanged because
LiteLLM keys them either as bare model names or as ``provider/model`` —
both forms are tried.

Authors adding a new provider should either match the LiteLLM key style or
register an alias via :class:`Catalog.with_overrides`. The default catalog
is loaded lazily on first use to keep import time tight (< 50 ms for the
~1.4 MB snapshot).

**Unknown-model warning silencing (AJ-70).** The one-time WARNING emitted
for unknown models is the right default for cloud models the operator pays
per-token for, but pure noise for local / self-hosted ones (``ollama:*``,
custom on-prem inference). Two silencing layers ship in v0.1:

1. **Default silent prefixes.** Models whose prefix segment (everything
   before the first ``:`` or ``/``) appears in
   :data:`_DEFAULT_SILENT_PREFIXES` skip the warning automatically. The
   list is intentionally small — a prefix qualifies only when the
   corresponding universal-OpenAI route declares ``api_key_env=None``
   AND the upstream service is intended to run on the operator's own
   infrastructure. Today only ``ollama`` matches; new entries land
   behind their own PR + spec note since they are user-visible behaviour
   changes.
2. **Per-catalog silence list.** :class:`Catalog` accepts a keyword-only
   ``silence_models=`` argument (and :class:`AjolopyFactory.create` a
   paired ``pricing_silence=``) — an iterable of exact model strings
   **and** prefix tokens. Both match the same way the default list does,
   so passing ``{"vllm"}`` silences ``vllm:foo`` and ``vllm:bar`` alike.

The chat-span emission is unchanged in every case: unknown models still
omit ``gen_ai.cost_usd*``; only the log line goes away.
"""

import json
import logging
import threading
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# Use the stdlib :mod:`logging` API rather than ``ajolopy.observability.get_logger``
# so the one-time unknown-model warning is visible to ``pytest``'s ``caplog``
# fixture (structlog's default pipeline emits via :class:`structlog.PrintLogger`
# when :func:`configure_logging` has not been called, which bypasses stdlib
# capture). Once the framework's structlog pipeline is installed, this logger
# is captured by the bridge that :func:`configure_logging` puts on the root
# logger, so the rendered output stays consistent.
_LOGGER = logging.getLogger("ajolopy.observability.pricing")

# LiteLLM ships a leading documentation entry under ``sample_spec``. Skip it
# when loading so it cannot be accidentally treated as a real model.
_SAMPLE_SPEC_KEY = "sample_spec"


# Prefixes whose unknown-model warning is silenced by default (AJ-70). A
# prefix qualifies when:
#
#   1. The universal-OpenAI route declares ``api_key_env=None`` (it is
#      operator-hosted infrastructure, not a billed cloud endpoint), AND
#   2. The upstream service is intended to run on the user's own machine
#      / cluster rather than be reached over the public internet.
#
# Today only ``ollama`` matches both conditions (cf.
# ``ajolopy.providers.universal_openai.provider._PREFIX_DEFAULTS``). New
# entries land behind their own PR + spec note since adding a prefix is a
# user-visible behaviour change. The constant is **not** imported from the
# provider package to keep the observability module free of provider-package
# dependencies; the rule is enforced by review.
_DEFAULT_SILENT_PREFIXES: frozenset[str] = frozenset({"ollama"})


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Per-tier USD-per-token prices for a single model.

    Field names mirror LiteLLM's snapshot exactly so the sync script's
    field-by-field diff stays trivial:

    - ``input_cost_per_token`` — billed for non-cached prompt tokens.
    - ``output_cost_per_token`` — billed for completion tokens.
    - ``cache_creation_input_token_cost`` — billed for prompt-cache writes
      (Anthropic). OpenAI / Gemini bill cache creation at the input rate;
      this field stays 0 for them.
    - ``cache_read_input_token_cost`` — billed for prompt-cache reads.

    Defaults of ``0.0`` model the common case where a model entry omits one
    or more cache tiers — the missing tiers contribute 0 to the final
    cost without forcing :func:`compute_cost_usd` to return ``None``.
    """

    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0
    cache_creation_input_token_cost: float = 0.0
    cache_read_input_token_cost: float = 0.0


class Catalog:
    """Lookup table from model string to :class:`ModelPrice`.

    Built from two sources merged in priority order:

    1. The embedded LiteLLM snapshot (``pricing.json`` next to this module).
    2. Optional overrides supplied by the user via
       :class:`AjolopyFactory.create(pricing_overrides=...)` or
       :meth:`with_overrides`.

    Overrides win wholesale over snapshot entries — there is no per-tier
    merge so users always know exactly what price they are billing against.

    The class is immutable from the consumer's perspective: :meth:`get`
    returns ``None`` for unknown models and emits a one-time warning per
    unseen model string. Construction itself is cheap; the snapshot is
    parsed once and cached on the class.
    """

    _default_lock: threading.Lock = threading.Lock()
    _default_instance: Catalog | None = None

    def __init__(
        self,
        prices: Mapping[str, ModelPrice],
        *,
        silence_models: Iterable[str] | None = None,
    ) -> None:
        # Copy so caller mutations cannot retroactively change the catalog.
        self._prices: dict[str, ModelPrice] = dict(prices)
        # Freeze the silence list for the same reason: a downstream caller
        # mutating the original iterable must not retroactively shift this
        # catalog's policy. The set holds both exact model names and prefix
        # tokens; ``_warn_unknown`` checks both forms.
        self._silence_models: frozenset[str] = (
            frozenset(silence_models) if silence_models is not None else frozenset()
        )
        self._warned_unknown: set[str] = set()
        self._warned_lock = threading.Lock()

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    @classmethod
    def load_default(cls) -> Catalog:
        """Return the process-wide default catalog, building it lazily."""
        with cls._default_lock:
            if cls._default_instance is None:
                cls._default_instance = cls(_load_snapshot_prices())
            return cls._default_instance

    @classmethod
    def from_snapshot(cls) -> Catalog:
        """Return a fresh catalog from the embedded snapshot.

        Bypasses the cached :meth:`load_default` instance so tests can build
        an override-free catalog without poisoning the global state.
        """
        return cls(_load_snapshot_prices())

    def with_overrides(self, overrides: Mapping[str, ModelPrice]) -> Catalog:
        """Return a new :class:`Catalog` with ``overrides`` merged in.

        Overrides replace the matching snapshot entries wholesale — no
        per-tier merge. Keys absent from the snapshot are added as new
        entries. The receiver is left unchanged. The silence-list policy
        carries over unchanged so a user who builds a catalog via
        :class:`AjolopyFactory.create(pricing_overrides=..., pricing_silence=...)`
        does not need to know the kwarg evaluation order.
        """
        merged: dict[str, ModelPrice] = dict(self._prices)
        for key, price in overrides.items():
            merged[key] = price
        return Catalog(merged, silence_models=self._silence_models)

    def with_silence(self, *models: str) -> Catalog:
        """Return a new :class:`Catalog` with extra silenced models / prefixes.

        Each positional argument is either an exact model string
        (``"my-custom-model"``) or a prefix token (``"vllm"``); both are
        matched the same way as :data:`_DEFAULT_SILENT_PREFIXES`. The
        receiver is left unchanged. Combines with :meth:`with_overrides`
        in either order — the silence policy and the pricing data are
        independent.
        """
        return Catalog(self._prices, silence_models=self._silence_models | frozenset(models))

    # ------------------------------------------------------------------
    # lookup
    # ------------------------------------------------------------------

    def get(self, model: str) -> ModelPrice | None:
        """Resolve ``model`` against the catalog with normalisation.

        Lookup order:

        1. The model string verbatim.
        2. The model string with ``:`` replaced by ``/`` (universal-OpenAI
           syntax → LiteLLM syntax).
        3. The bare model name (segment after the final ``/`` or ``:``) —
           covers callers routing a bare model through a custom prefix.

        When none of the three resolves, a one-time warning is logged per
        ``model`` string and ``None`` is returned. The caller (usually
        :mod:`ajolopy.observability.pricing_emit`) treats ``None`` as
        "omit the cost attrs" so unknown models never silently report $0.
        """
        for candidate in _normalisation_candidates(model):
            price = self._prices.get(candidate)
            if price is not None:
                return price
        self._warn_unknown(model)
        return None

    def __contains__(self, model: object) -> bool:
        if not isinstance(model, str):
            return False
        return any(c in self._prices for c in _normalisation_candidates(model))

    def __len__(self) -> int:
        return len(self._prices)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _warn_unknown(self, model: str) -> None:
        with self._warned_lock:
            if model in self._warned_unknown:
                return
            # Record the model even when the policy silences it: the dedup
            # invariant ("one log line per model per process") survives a
            # later silence-policy change that way — a model that was silent
            # on the first lookup stays silent on the second.
            self._warned_unknown.add(model)
            if self._is_silenced(model):
                return
        _LOGGER.warning(
            "Unknown model %r — gen_ai.cost_usd omitted from spans. "
            "Register a pricing_overrides entry to silence this warning.",
            model,
        )

    def _is_silenced(self, model: str) -> bool:
        """Return ``True`` when the unknown-model warning should be suppressed.

        Combines the three silencing sources from the AJ-70 spec:

        1. Default silent prefixes (:data:`_DEFAULT_SILENT_PREFIXES`).
        2. Exact model strings in this catalog's silence list.
        3. Prefix tokens in this catalog's silence list.
        """
        if model in self._silence_models:
            return True
        prefix = _prefix_segment(model)
        if prefix is None:
            return False
        if prefix in _DEFAULT_SILENT_PREFIXES:
            return True
        return prefix in self._silence_models


# ---------------------------------------------------------------------------
# Default-catalog seam used by ``AjolopyFactory.create(pricing_overrides=...)``
# ---------------------------------------------------------------------------

_active_catalog_lock: threading.Lock = threading.Lock()
_active_catalog: Catalog | None = None


def set_default_catalog(catalog: Catalog | None) -> None:
    """Override the process-wide active catalog.

    The factory calls this once at bootstrap to install a catalog with
    user-supplied ``pricing_overrides`` merged in. Subsequent calls
    replace the active catalog; ``None`` clears it so the next
    :func:`get_active_catalog` call falls back to
    :meth:`Catalog.load_default`.
    """
    global _active_catalog
    with _active_catalog_lock:
        _active_catalog = catalog


def get_active_catalog() -> Catalog:
    """Return the active catalog, falling back to the default snapshot.

    Used by :mod:`ajolopy.observability.pricing_emit` so the runtime picks
    up the factory-installed catalog on first cost emission rather than at
    construction time (decorator time runs *before* factory time).
    """
    with _active_catalog_lock:
        active = _active_catalog
    if active is not None:
        return active
    return Catalog.load_default()


# ---------------------------------------------------------------------------
# Cost math
# ---------------------------------------------------------------------------


def compute_cost_usd(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    catalog: Catalog | None = None,
) -> float | None:
    """Return the USD cost of a single call, or ``None`` for an unknown model.

    ``catalog`` defaults to the process-wide active catalog (see
    :func:`get_active_catalog`). Missing tiers in the snapshot contribute 0
    to the total — they do not turn the whole call into an unknown result.

    The math is the obvious sum of ``tokens * price_per_token`` over the
    four tiers. Float arithmetic stays well within sub-cent precision for
    realistic billing volumes (1 billion input tokens * $3/MTok = $3000.0
    exactly in IEEE-754).
    """
    if catalog is None:
        catalog = get_active_catalog()
    price = catalog.get(model)
    if price is None:
        return None
    return (
        input_tokens * price.input_cost_per_token
        + output_tokens * price.output_cost_per_token
        + cache_creation_input_tokens * price.cache_creation_input_token_cost
        + cache_read_input_tokens * price.cache_read_input_token_cost
    )


# ---------------------------------------------------------------------------
# Snapshot loader
# ---------------------------------------------------------------------------


def _normalisation_candidates(model: str) -> Iterable[str]:
    """Yield the model-string variants tried by :meth:`Catalog.get`."""
    yield model
    if ":" in model:
        yield model.replace(":", "/", 1)
    # Bare model name (strip the prefix when present in either syntax).
    if ":" in model or "/" in model:
        bare = model.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        if bare and bare != model:
            yield bare


def _prefix_segment(model: str) -> str | None:
    """Return the prefix segment of ``model`` or ``None`` for a bare name.

    The segment is everything before the first ``:`` or ``/``. Used by the
    silence policy to match prefix tokens (e.g. ``"ollama"`` matches
    ``"ollama:llama3.3"``) without forcing callers to know which separator
    syntax the model string uses.

    Returns ``None`` when the model string has neither separator (so a
    bare name like ``"claude-sonnet-4-5"`` never accidentally matches a
    silence list whose entries are intended as prefix tokens).
    """
    colon = model.find(":")
    slash = model.find("/")
    if colon == -1 and slash == -1:
        return None
    # Pick the earliest separator; ``min`` over the two positions while
    # treating -1 as "absent" needs a small dance.
    candidates = [pos for pos in (colon, slash) if pos != -1]
    cut = min(candidates)
    prefix = model[:cut]
    return prefix or None


def _load_snapshot_prices() -> dict[str, ModelPrice]:
    """Parse the bundled LiteLLM snapshot into ``{model: ModelPrice}``."""
    snapshot_text = (
        resources.files("ajolopy.observability").joinpath("pricing.json").read_text("utf-8")
    )
    raw: dict[str, Any] = json.loads(snapshot_text)
    prices: dict[str, ModelPrice] = {}
    for model, entry in raw.items():
        if model == _SAMPLE_SPEC_KEY:
            # Documentation entry, not a real model.
            continue
        if not isinstance(entry, dict):
            # Defensive — every real entry is a dict; skip anything that
            # cannot be coerced rather than crashing the import.
            continue
        prices[model] = _coerce_entry(entry)  # pyright: ignore[reportUnknownArgumentType]
    return prices


def _coerce_entry(entry: dict[str, Any]) -> ModelPrice:
    """Pluck the four pricing fields out of a LiteLLM entry."""
    return ModelPrice(
        input_cost_per_token=_as_float(entry.get("input_cost_per_token")),
        output_cost_per_token=_as_float(entry.get("output_cost_per_token")),
        cache_creation_input_token_cost=_as_float(entry.get("cache_creation_input_token_cost")),
        cache_read_input_token_cost=_as_float(entry.get("cache_read_input_token_cost")),
    )


def _as_float(value: Any) -> float:
    """Coerce a snapshot entry value to ``float``; default to 0.0 on miss.

    Some LiteLLM entries set unused tier fields to ``None`` or to a string
    placeholder ("0.0 used to be string in v1") — fall back to 0.0 rather
    than crashing on a bad type.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


__all__ = [
    "Catalog",
    "ModelPrice",
    "compute_cost_usd",
    "get_active_catalog",
    "set_default_catalog",
]
