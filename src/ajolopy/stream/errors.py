"""Framework-side errors raised by the stream layer.

``StreamConfigError`` fires before traffic is served (decoration time or
mount time) — the user has misconfigured a ``@Stream`` decorator or
``mount_streams`` call. ``StreamRuntimeError`` fires mid-stream and is
caught by the SSE wrapper so the client sees a final error event before
the connection closes.
"""


class StreamLayerError(RuntimeError):
    """Base class for any framework-side error raised by the stream layer."""


class StreamConfigError(StreamLayerError):
    """A ``@Stream`` decorator or ``mount_streams`` call is invalid.

    Raised at decoration time for: non-async-generator targets, empty or
    relative paths, unsupported HTTP methods, ``auth=True`` (reserved for
    AJ-17), non-positive ``heartbeat_seconds`` (use ``None`` to disable),
    or stacked ``@Stream`` decorators on a single method.

    Raised at mount time for: classes with required constructor arguments
    bound without a pre-built instance, classes with no ``@Stream``-marked
    methods, and duplicate ``(method, path)`` pairs across a single
    ``mount_streams`` call.
    """


class StreamRuntimeError(StreamLayerError):
    """A ``@Stream`` handler yielded an unsupported value mid-stream.

    Caught by the SSE wrapper and surfaced as a final
    ``data: {"error": "..."}\\n\\n`` event before the stream closes.
    """
