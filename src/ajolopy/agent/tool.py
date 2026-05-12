"""``@Tool`` method decorator + tool-binding helpers.

The decorator tags a method with a ``ToolMetadata`` record. The agent
runtime later scans the decorated class — and any class passed to
``@Agent(tools=[...])`` — for tagged methods and builds a ``ToolBinding``
per tool, which is what the function-calling loop dispatches against.

Schema generation strategy (the "magical default"):

- The method's ``inspect.signature`` is consumed, ``self`` is dropped, every
  remaining parameter is fed into ``pydantic.create_model`` along with its
  annotation and default. ``model_json_schema()`` produces the wire schema.

- ``@Tool(schema=BaseModelSubclass)`` overrides the synthesised model
  wholesale. The runtime still maps the validated model attributes back to
  keyword arguments before invoking the underlying method.

- ``@Tool(name=..., description=...)`` override the introspected name /
  docstring without touching the schema.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, overload

from pydantic import BaseModel, ValidationError, create_model

from ajolopy.providers import Tool as WireTool

from .errors import ToolDefinitionError

_TOOL_MARKER = "__ajolopy_tool__"
"""Attribute name used to tag a method as a ``@Tool``."""


@dataclass(slots=True)
class ToolMetadata:
    """Metadata attached to a ``@Tool``-decorated method.

    ``schema_model`` is a ``BaseModel`` subclass — either synthesised from
    the method's signature or supplied via ``@Tool(schema=...)``. It is
    used to JSON-schema the parameters for the LLM and to validate the
    arguments the LLM produces before invoking the underlying method.

    ``is_async`` flags whether the original callable is a coroutine
    function; sync callables are dispatched through ``asyncio.to_thread``
    by the runtime so they cannot block the event loop.

    ``schema_is_synthetic`` distinguishes the two schema sources: when the
    schema was generated from the method's signature we pass the validated
    model's fields as keyword arguments to the method (one kwarg per
    parameter). When the user supplied a ``BaseModel``, we instead pass
    the model's fields as kwargs too — but the user is responsible for
    making sure the method's parameter names match the model's field
    names. (Validation of that match happens at decoration time.)
    """

    name: str
    description: str
    schema_model: type[BaseModel]
    is_async: bool
    schema_is_synthetic: bool
    fn: Callable[..., Any]

    # Cache the JSON Schema so repeated calls don't re-invoke pydantic.
    _cached_schema: dict[str, Any] | None = field(default=None, repr=False)

    _UNSERIALISABLE_HINT: ClassVar[str] = (
        "Pydantic could not generate a JSON schema for this parameter. "
        "Either annotate it with a JSON-serialisable type (str, int, float, "
        "bool, list, dict, BaseModel, …) or override the whole schema with "
        "@Tool(schema=YourBaseModel)."
    )

    def json_schema(self) -> dict[str, Any]:
        """Return the JSON Schema for this tool's inputs (cached)."""
        if self._cached_schema is None:
            self._cached_schema = self.schema_model.model_json_schema()
        return self._cached_schema

    def to_wire_tool(self) -> WireTool:
        """Convert metadata to the provider-agnostic ``Tool`` wire object."""
        return WireTool(
            name=self.name,
            description=self.description,
            parameters=self.json_schema(),
        )

    def validate_arguments(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Validate raw LLM arguments through the Pydantic model.

        Returns the validated kwargs to forward to the underlying method.
        ``ValidationError`` is propagated; the runtime catches it and
        surfaces a tool_result with ``is_error=True`` to the model.
        """
        try:
            validated = self.schema_model.model_validate(raw)
        except ValidationError:
            raise
        # ``model_dump`` returns the same keys the synthesised model declared,
        # which by construction match the method's parameter names.
        return validated.model_dump()


@dataclass(slots=True)
class ToolBinding:
    """Runtime binding: a tool metadata + the owning class.

    ``owner_cls`` is ``None`` when the tool lives on the decorated agent
    class itself (we use the agent instance directly). For tools harvested
    from ``tools=[OtherClass]`` we cache one instance of ``OtherClass`` on
    the runtime and look it up by class identity at execution time.
    """

    metadata: ToolMetadata
    owner_cls: type[Any] | None


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


@overload
def Tool[F: Callable[..., Any]](fn: F, /) -> F: ...
@overload
def Tool[F: Callable[..., Any]](
    fn: None = ...,
    /,
    *,
    name: str | None = ...,
    description: str | None = ...,
    schema: type[BaseModel] | None = ...,
) -> Callable[[F], F]: ...
def Tool[F: Callable[..., Any]](  # noqa: N802 — public surface mirrors the Brief's primitive name.
    fn: F | None = None,
    /,
    *,
    name: str | None = None,
    description: str | None = None,
    schema: type[BaseModel] | None = None,
) -> F | Callable[[F], F]:
    """Mark an instance method as a tool exposed to the LLM.

    Used either bare (``@Tool``) or with kwargs (``@Tool(name="…")``). The
    decorated method stays callable as a normal Python method; only the
    framework's tool dispatcher consults the attached metadata.

    See ``specs/tool.md`` for the full surface and acceptance criteria.
    """

    def _wrap(fn_inner: F) -> F:
        metadata = _build_metadata(
            fn=fn_inner,
            name_override=name,
            description_override=description,
            schema_override=schema,
        )
        # Stash metadata on the underlying callable; the agent runtime picks
        # it up during tool discovery. We do not wrap the callable — it
        # keeps its original signature, type hints, and call semantics.
        setattr(fn_inner, _TOOL_MARKER, metadata)
        return fn_inner

    if fn is not None:
        return _wrap(fn)
    return _wrap


# ---------------------------------------------------------------------------
# Discovery — called by the agent decorator
# ---------------------------------------------------------------------------


def discover_tools(
    cls: type[Any],
    extras: list[type[Any]] | None,
) -> tuple[list[ToolBinding], dict[type[Any], Any]]:
    """Scan ``cls`` and every class in ``extras`` for ``@Tool``s.

    Returns ``(bindings, extra_instances)``: ``bindings`` is the ordered
    list of discovered tools (the decorated class first, then each extra
    in input order). ``extra_instances`` is a map from each extra class to
    a singleton instance — the runtime uses it to dispatch tool calls
    against tools harvested from external classes.

    Raises ``ToolDefinitionError`` on duplicate tool names across the
    decorated class and the extras.
    """
    bindings: list[ToolBinding] = []
    seen_names: dict[str, type[Any]] = {}

    for metadata in _iter_tools(cls):
        if metadata.name in seen_names:
            raise ToolDefinitionError(
                f"Duplicate tool name {metadata.name!r} on {cls.__qualname__}."
            )
        seen_names[metadata.name] = cls
        bindings.append(ToolBinding(metadata=metadata, owner_cls=None))

    extra_instances: dict[type[Any], Any] = {}
    for extra_cls in extras or []:
        if extra_cls in extra_instances:
            continue
        extra_instances[extra_cls] = extra_cls()
        for metadata in _iter_tools(extra_cls):
            if metadata.name in seen_names:
                origin = seen_names[metadata.name]
                raise ToolDefinitionError(
                    f"Duplicate tool name {metadata.name!r}: defined on both "
                    f"{origin.__qualname__} and {extra_cls.__qualname__}."
                )
            seen_names[metadata.name] = extra_cls
            bindings.append(ToolBinding(metadata=metadata, owner_cls=extra_cls))

    return bindings, extra_instances


def _iter_tools(cls: type[Any]) -> list[ToolMetadata]:
    """Yield ``ToolMetadata`` for every ``@Tool``-tagged member of ``cls``."""
    metadatas: list[ToolMetadata] = []
    for _attr_name, attr in cls.__dict__.items():
        metadata = getattr(attr, _TOOL_MARKER, None)
        if isinstance(metadata, ToolMetadata):
            metadatas.append(metadata)
    return metadatas


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_metadata(
    *,
    fn: Callable[..., Any],
    name_override: str | None,
    description_override: str | None,
    schema_override: type[BaseModel] | None,
) -> ToolMetadata:
    if schema_override is not None:
        schema_model = schema_override
        synthetic = False
        _validate_schema_override_matches_signature(fn, schema_override)
    else:
        schema_model = _synthesize_schema_model(fn)
        synthetic = True

    name = name_override if name_override else fn.__name__
    description = description_override if description_override else _extract_description(fn)

    return ToolMetadata(
        name=name,
        description=description,
        schema_model=schema_model,
        is_async=inspect.iscoroutinefunction(fn),
        schema_is_synthetic=synthetic,
        fn=fn,
    )


def _synthesize_schema_model(fn: Callable[..., Any]) -> type[BaseModel]:
    """Build a Pydantic model from ``fn``'s signature (skipping ``self``).

    Pydantic v2's ``create_model`` does the heavy lifting; it handles
    primitive types, generics (``list[str]``, ``dict[str, int]``), unions,
    nested ``BaseModel`` annotations, ``Literal``, and ``Optional`` out
    of the box. We surface the two failure modes that fall outside that
    set as ``ToolDefinitionError`` at decoration time so the user sees
    them at import, not at first request.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        raise ToolDefinitionError(
            f"Could not inspect signature of {fn.__qualname__}: {exc}"
        ) from exc

    fields: dict[str, Any] = {}
    first = True
    for param_name, param in sig.parameters.items():
        if first:
            first = False
            if param_name == "self":
                continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise ToolDefinitionError(
                f"{fn.__qualname__} declares *args / **kwargs — @Tool needs "
                f"explicit parameters. Use a named parameter list or pass an "
                f"explicit schema= override."
            )
        if param.annotation is inspect.Parameter.empty:
            raise ToolDefinitionError(
                f"Parameter {param_name!r} of {fn.__qualname__} has no type "
                f"annotation. @Tool relies on annotations to build the JSON "
                f"schema; either annotate it or pass an explicit schema= "
                f"override."
            )
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (param.annotation, default)

    model_name = f"{_normalize_model_name(fn.__qualname__)}Args"
    try:
        model = create_model(model_name, **fields)
    except Exception as exc:
        raise ToolDefinitionError(
            f"Pydantic could not build a schema model for {fn.__qualname__}: "
            f"{exc}. {ToolMetadata._UNSERIALISABLE_HINT}"  # pyright: ignore[reportPrivateUsage]
        ) from exc

    # Force the schema to be generated once at decoration time so that
    # any unserialisable parameter type fails fast.
    try:
        model.model_json_schema()
    except Exception as exc:
        raise ToolDefinitionError(
            f"Cannot JSON-serialise the schema of {fn.__qualname__}: {exc}. "
            f"{ToolMetadata._UNSERIALISABLE_HINT}"  # pyright: ignore[reportPrivateUsage]
        ) from exc

    return model


def _validate_schema_override_matches_signature(
    fn: Callable[..., Any],
    schema: type[BaseModel],
) -> None:
    """Make sure every field of the override model matches a parameter of fn.

    The override is used to validate the LLM-supplied arguments; the
    validated model is then expanded into kwargs and passed to ``fn``. If
    the model declares a field the method does not accept, the call will
    fail at runtime with a TypeError. We surface that as a clear
    ``ToolDefinitionError`` at decoration time instead.
    """
    try:
        sig = inspect.signature(fn)
    except TypeError, ValueError:
        return
    accepted = {name for name in sig.parameters if name != "self"}
    has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if has_var_kw:
        return
    declared = set(schema.model_fields.keys())
    unknown = declared - accepted
    if unknown:
        raise ToolDefinitionError(
            f"Schema {schema.__name__} declares field(s) {sorted(unknown)!r} "
            f"that {fn.__qualname__} does not accept. Align the field names "
            f"with the method's parameters or remove them from the model."
        )


def _extract_description(fn: Callable[..., Any]) -> str:
    """Return the first non-empty line of the function's docstring, or ``""``."""
    doc = inspect.getdoc(fn)
    if not doc:
        return ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _normalize_model_name(qualname: str) -> str:
    """Turn ``Support.get_order_status`` into ``Support_get_order_status``."""
    return qualname.replace(".", "_").replace("<", "_").replace(">", "_")
