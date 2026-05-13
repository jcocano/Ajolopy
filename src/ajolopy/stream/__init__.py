"""Server-Sent Events (SSE) streaming primitive.

Public surface — the ``Stream`` method decorator, the ``mount_streams``
helper, and the stream-layer error hierarchy. The decorator stamps
metadata on the decorated method (no wrapping); ``mount_streams``
registers each marked method as a Starlette SSE route via the AJ-15
``add_route`` pipeline.
"""

from .decorator import Stream, StreamMetadata, get_stream_metadata, iter_stream_methods
from .errors import StreamConfigError, StreamLayerError, StreamRuntimeError
from .mount import mount_streams
from .sse import format_data_event, format_error_event, format_keepalive

__all__ = [
    "Stream",
    "StreamConfigError",
    "StreamLayerError",
    "StreamMetadata",
    "StreamRuntimeError",
    "format_data_event",
    "format_error_event",
    "format_keepalive",
    "get_stream_metadata",
    "iter_stream_methods",
    "mount_streams",
]
