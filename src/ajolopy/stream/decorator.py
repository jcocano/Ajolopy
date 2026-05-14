"""``@Stream`` method decorator.

The decorator validates its arguments and the decorated function at
decoration time, stamps a :class:`StreamMetadata` record on the function
under the ``_ajolopy_stream`` attribute, and returns the function
unchanged. The mount layer (``mount_streams``) walks marked methods and
builds the SSE handler at registration time.

Returning the function unchanged is deliberate: ``await
instance.respond(...)`` still produces the original async generator, so
``@Eval`` runners, tests, and internal callers can consume the
generator natively — no HTTP framing leaks through Python-level calls.
"""

import inspect
from collections.abc import AsyncGenerator, Callable, Iterator
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from .errors import StreamConfigError

_STREAM_META_ATTR = "_ajolopy_stream"
_ALLOWED_METHODS: frozenset[str] = frozenset({"GET", "POST"})

# ``AsyncGenerator`` is invariant in both type parameters; the decorator
# accepts any async-generator method shape (yielded type varies between
# str / dict / BaseModel).
F = TypeVar("F", bound=Callable[..., AsyncGenerator[Any]])


@dataclass(frozen=True, slots=True)
class StreamMetadata:
    """Stamped on every ``@Stream``-decorated method.

    Held verbatim by ``mount_streams`` so route registration sees the
    exact values that the user wrote — no defaults are mutated or
    re-derived later.
    """

    path: str
    method: str
    auth: bool
    heartbeat_seconds: float | None
    handler: Callable[..., AsyncGenerator[Any]]


def Stream(  # noqa: N802 — public surface mirrors the Brief's primitive name.
    path: str,
    method: str = "POST",
    *,
    auth: bool = False,
    heartbeat_seconds: float | None = 30.0,
) -> Callable[[F], F]:
    """Mark an ``async def`` generator method as an SSE endpoint.

    Validates ``path`` / ``method`` / ``auth`` / ``heartbeat_seconds`` at
    decoration time. The decorated method must be an async generator
    (uses ``yield`` inside an ``async def``); regular coroutines and sync
    functions are rejected.

    ``auth=True`` declares that the stream MUST be gated by
    ``@UseGuards`` (AJ-17). The decoration-time check is light — the
    bool is recorded on the metadata; ``mount_streams`` later raises
    :class:`StreamConfigError` if neither the host class nor the
    method carries any ``_ajolopy_guards`` metadata.
    ``heartbeat_seconds=None`` disables keep-alive comments; a positive
    float configures the interval.
    """
    _validate_path(path)
    upper = _validate_method(method)
    _validate_auth(auth)
    _validate_heartbeat(heartbeat_seconds)

    def decorate(fn: F) -> F:
        if not inspect.isasyncgenfunction(fn):
            raise StreamConfigError(
                f"@Stream target {_qualname(fn)} must be an async generator "
                f"(async def with yield). Got "
                f"{'a coroutine' if inspect.iscoroutinefunction(fn) else 'a non-async function'}."
            )
        if getattr(fn, _STREAM_META_ATTR, None) is not None:
            raise StreamConfigError(
                f"@Stream cannot be stacked on {_qualname(fn)}; the method "
                f"already carries stream metadata."
            )
        metadata = StreamMetadata(
            path=path,
            method=upper,
            auth=auth,
            heartbeat_seconds=heartbeat_seconds,
            handler=fn,
        )
        setattr(fn, _STREAM_META_ATTR, metadata)
        return fn

    return decorate


def get_stream_metadata(obj: object) -> StreamMetadata | None:
    """Return the :class:`StreamMetadata` stamped on ``obj``, or ``None``.

    Works for unbound functions, bound methods (the metadata lives on the
    underlying function, which Python exposes as ``__func__``), and any
    callable carrying the ``_ajolopy_stream`` attribute.
    """
    metadata = getattr(obj, _STREAM_META_ATTR, None)
    if metadata is None:
        func = getattr(obj, "__func__", None)
        if func is not None:
            metadata = getattr(func, _STREAM_META_ATTR, None)
    return metadata if isinstance(metadata, StreamMetadata) else None


def iter_stream_methods(target: object) -> Iterator[tuple[str, Any, StreamMetadata]]:
    """Yield ``(attr_name, bound_method, metadata)`` for every marked method.

    ``target`` may be a class or an instance. For classes, the iteration
    walks the MRO; for instances, attribute access binds ``self``
    naturally. Class-level ``classmethod`` / ``staticmethod`` carrying
    stream metadata are still discovered because the metadata is read
    from the underlying function.
    """
    cls = target if isinstance(target, type) else type(target)
    seen: set[str] = set()
    for klass in cls.__mro__:
        for name, attr in vars(klass).items():
            if name in seen:
                continue
            metadata = get_stream_metadata(attr)
            if metadata is None:
                continue
            seen.add(name)
            bound = getattr(target, name)
            yield name, bound, metadata


# ----------------------------------------------------------------------- helpers


def _qualname(obj: object) -> str:
    return getattr(obj, "__qualname__", repr(obj))


def _validate_path(path: str) -> None:
    if not isinstance(path, str) or not path:  # pyright: ignore[reportUnnecessaryIsInstance]
        raise StreamConfigError("@Stream path must be a non-empty string.")
    if not path.startswith("/"):
        raise StreamConfigError(f"@Stream path must start with '/'; got {path!r}.")


def _validate_method(method: str) -> str:
    if not isinstance(method, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise StreamConfigError(
            f"@Stream method must be a string ('GET' or 'POST'); got {method!r}."
        )
    upper = method.upper()
    if upper not in _ALLOWED_METHODS:
        raise StreamConfigError(
            f"@Stream method {method!r} not supported. Allowed: {sorted(_ALLOWED_METHODS)}."
        )
    return upper


def _validate_auth(auth: bool) -> None:
    # ``auth=`` is purely declarative at decoration time: the metadata
    # stamp lets ``mount_streams`` assert the gating story is wired
    # before the route goes live. We still reject non-bool inputs so a
    # typo (``auth="true"``) surfaces immediately.
    if not isinstance(auth, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise StreamConfigError(
            f"@Stream auth= must be a bool; got {type(auth).__name__}: {auth!r}."
        )


def _validate_heartbeat(seconds: float | None) -> None:
    if seconds is None:
        return
    # ``bool`` passes the static ``float`` check (it subclasses ``int``),
    # but ``True``/``False`` as an interval is almost certainly a bug.
    if isinstance(seconds, bool):
        raise StreamConfigError(
            f"@Stream heartbeat_seconds must be a positive number; got {seconds!r}."
        )
    if seconds <= 0:
        raise StreamConfigError(
            f"@Stream heartbeat_seconds must be > 0; got {seconds}. Use "
            f"None to disable heart beats."
        )


# Re-export for static-type consumers that want the metadata attribute name.
STREAM_META_ATTR: str = _STREAM_META_ATTR


# typing-only export — keeps ``F`` from being flagged as "unused" in __all__.
_ = cast("Any", F)
