"""``LLMProvider`` abstract base class.

Every concrete LLM provider — Anthropic, OpenAI, Gemini, the universal
OpenAI-compatible adapter, and any plugin provider — implements this
interface. Higher-level primitives (``@Agent``, ``@Workflow``, ``@Eval``)
consume ``LLMProvider``; they must never import a concrete subclass directly.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .types import Chunk, Message, Response, Tool


class LLMProviderError(RuntimeError):
    """Base class for errors raised by any concrete ``LLMProvider``.

    Higher-level layers (`@Agent`, fallback orchestration) catch this base
    class to treat any provider failure uniformly, without importing every
    provider package.
    """


class LLMProvider(ABC):
    """Provider-agnostic contract for talking to a chat-style LLM."""

    GEN_AI_SYSTEM: ClassVar[str] = "unknown"
    """OpenTelemetry ``gen_ai.system`` value used by the observability layer to
    tag spans emitted around this provider's calls. Concrete providers override
    with the upstream vendor identifier (``anthropic``, ``openai``,
    ``gcp.gemini``, ``openai_compatible``). The default is intentionally
    ``unknown`` so test fakes and partial subclasses do not need to override —
    spans will still be emitted, just with a placeholder system value."""

    @classmethod
    def gen_ai_system_for(cls, model: str) -> str:  # noqa: ARG003 — universal subclass uses model
        """Return the ``gen_ai.system`` for a span tagging a call to ``model``.

        Defaults to the class-level :attr:`GEN_AI_SYSTEM`. The universal
        OpenAI-compatible adapter overrides this method to append the route
        flavor (``openai_compatible.groq``, ``openai_compatible.ollama``, …).
        """
        return cls.GEN_AI_SYSTEM

    @abstractmethod
    async def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> Response:
        """Issue a non-streaming completion request."""

    @abstractmethod
    def stream(
        self,
        *,
        model: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = False,
    ) -> AsyncIterator[Chunk]:
        """Issue a streaming completion request, yielding token chunks."""

    @abstractmethod
    async def embed(self, *, model: str, text: str | list[str]) -> list[list[float]]:
        """Embed one or more strings. Always returns a list of vectors."""

    @abstractmethod
    def count_tokens(self, *, model: str, text: str) -> int:
        """Count tokens the given model would consume for ``text``."""

    @abstractmethod
    def supports_prompt_caching(self) -> bool:
        """Whether this provider accepts ``cache=True`` on completion calls."""

    @abstractmethod
    def supports_tool_calling(self) -> bool:
        """Whether this provider accepts ``tools=[...]`` on completion calls."""
