"""SSE runtime — wraps an async generator into a Starlette streaming endpoint.

The orchestrator multiplexes three concurrent producers via a shared
``asyncio.Queue``:

1. **pump** — drains the user's async generator, serialises each
   yielded value with :func:`format_data_event`, and pushes the bytes
   onto the queue. Exceptions are caught, logged at ``ERROR``, and
   surfaced as one final error event before the sentinel.
2. **heartbeat** — pushes a keep-alive comment every
   ``heartbeat_seconds``; disabled when ``None``.
3. **watch_disconnect** — polls :meth:`Request.is_disconnected` and
   pushes the sentinel so the consumer exits cleanly.

The consumer reads from the queue and yields bytes until it sees the
sentinel; on exit it cancels all background tasks and ``aclose()``-s
the user generator so its ``finally:`` blocks run.
"""

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any, cast

from starlette.responses import StreamingResponse

from ajolopy.http.introspect import extract_raw

from .errors import StreamRuntimeError
from .sse import format_data_event, format_error_event, format_keepalive

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable

    from starlette.requests import Request

    from ajolopy.http.introspect import ResolvedParam
    from ajolopy.http.pipes import Pipe

    from .decorator import StreamMetadata

_LOGGER = logging.getLogger("ajolopy.stream")

_DISCONNECT_POLL_SECONDS = 0.1

_SSE_HEADERS: dict[str, str] = {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache",
    "connection": "keep-alive",
    # Disable proxy buffering (nginx and friends) so events flush in real time.
    "x-accel-buffering": "no",
}


def make_sse_handler(
    *,
    bound_method: Callable[..., Any],
    metadata: StreamMetadata,
    resolved_params: list[ResolvedParam],
    pipe: Pipe,
) -> Callable[[Request], Awaitable[StreamingResponse]]:
    """Build the Starlette endpoint for one ``@Stream`` method.

    Parameter resolution (``Body()``/``Query()``/``Param()``/``Header()``)
    runs **before** the streaming response is constructed, so validation
    failures propagate through the normal AJ-15 filter pipeline and
    produce the regular JSON envelope — no SSE headers leak before the
    handler is known to be valid.
    """
    heartbeat = metadata.heartbeat_seconds

    async def endpoint(request: Request) -> StreamingResponse:
        kwargs: dict[str, Any] = {}
        for rp in resolved_params:
            raw = await extract_raw(request, rp)
            kwargs[rp.name] = await pipe.transform(raw, param=rp)

        gen = cast("AsyncGenerator[Any]", bound_method(**kwargs))
        if not inspect.isasyncgen(gen):
            raise StreamRuntimeError(
                f"@Stream method {metadata.handler.__qualname__} did not "
                f"produce an async generator on invocation."
            )

        body = _iterate_sse(gen, heartbeat, request)
        return StreamingResponse(body, headers=_SSE_HEADERS)

    return endpoint


async def _iterate_sse(
    gen: AsyncGenerator[Any],
    heartbeat_seconds: float | None,
    request: Request,
) -> AsyncIterator[bytes]:
    """Drive the user generator, heartbeat, and disconnect watcher concurrently."""
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for value in gen:
                queue.put_nowait(format_data_event(value))
        except asyncio.CancelledError:
            # Propagate cancellation so the generator's ``finally:`` runs.
            raise
        except Exception as exc:
            _LOGGER.error("Stream handler raised: %s", exc, exc_info=True)
            queue.put_nowait(format_error_event(str(exc)))
        finally:
            queue.put_nowait(None)  # sentinel

    async def heartbeat_loop() -> None:
        if heartbeat_seconds is None:
            return
        while True:
            await asyncio.sleep(heartbeat_seconds)
            queue.put_nowait(format_keepalive())

    async def watch_disconnect() -> None:
        while True:
            if await request.is_disconnected():
                queue.put_nowait(None)
                return
            await asyncio.sleep(_DISCONNECT_POLL_SECONDS)

    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(pump(), name="ajolopy.stream.pump"),
        asyncio.create_task(heartbeat_loop(), name="ajolopy.stream.heartbeat"),
        asyncio.create_task(watch_disconnect(), name="ajolopy.stream.disconnect"),
    ]

    try:
        while True:
            item = await queue.get()
            if item is None:
                return
            yield item
    finally:
        for task in tasks:
            task.cancel()
        # ``aclose()`` runs the generator's ``finally:`` blocks. We catch
        # exceptions here because the generator may already have raised.
        try:
            await gen.aclose()
        except Exception:
            _LOGGER.debug("Generator aclose raised during cleanup", exc_info=True)
        await asyncio.gather(*tasks, return_exceptions=True)
