"""Structured-output helpers: ``json_match``.

JSON shape comparisons. Room for v0.2 extensions like
``jsonpath_match`` — keep the module narrow for now.
"""

import json

from ._resolve import coerce_to_text
from .errors import MetricsConfigError


def json_match(output: object, expected: object, *, partial: bool = False) -> float:
    """Return ``1.0`` if ``output`` parses to JSON structurally equal to ``expected``.

    - ``output`` is coerced through :func:`coerce_to_text` and then
      parsed with :func:`json.loads`.
    - Parse failure → ``0.0`` (NOT a raise — a malformed-JSON output
      is simply "doesn't match").
    - Equality is plain Python ``==`` so dicts, lists, and JSON scalars
      compose naturally.
    - ``partial=True`` is reserved for v0.2 and rejected with
      :class:`MetricsConfigError` at call time so users see the
      explicit limitation rather than a silent surprise.
    """
    if partial:
        raise MetricsConfigError("json_match: partial=True is reserved for v0.2")
    text = coerce_to_text(output, helper_name="json_match")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return 0.0
    return 1.0 if parsed == expected else 0.0


__all__ = ["json_match"]
