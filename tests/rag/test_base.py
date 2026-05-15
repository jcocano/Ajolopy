"""Acceptance tests for :class:`Retriever`, :class:`Document`, and
:class:`RetrievalHit` — the abstract contract and the immutable value
types every backend speaks.
"""

from collections.abc import Iterable
from typing import override

import pytest

from ajolopy.rag import Document, RetrievalHit, Retriever


def test_document_is_frozen_and_slotted() -> None:
    doc = Document(id="d1", text="hello", metadata={"k": "v"})
    # ``frozen=True`` rejects field reassignment.
    with pytest.raises(AttributeError):
        doc.text = "mutated"  # type: ignore[misc]
    # ``slots=True`` blocks ad-hoc attributes; combined with ``frozen``
    # the setter raises ``FrozenInstanceError`` (a subclass of
    # ``AttributeError``) before slots even gets a say.
    with pytest.raises((AttributeError, TypeError)):
        doc.extra = "x"  # type: ignore[attr-defined]
    # ``slots=True`` collapses ``__dict__`` so the attribute is missing.
    assert not hasattr(doc, "__dict__")


def test_document_metadata_defaults_to_empty_mapping() -> None:
    doc = Document(id="d1", text="hello")
    assert doc.metadata == {}


def test_retrieval_hit_is_frozen_and_slotted() -> None:
    doc = Document(id="d1", text="hello")
    hit = RetrievalHit(document=doc, score=0.9)
    with pytest.raises(AttributeError):
        hit.score = 0.0  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        hit.extra = "x"  # type: ignore[attr-defined]
    assert not hasattr(hit, "__dict__")


def test_retriever_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        Retriever()  # type: ignore[abstract]


def test_subclass_missing_method_is_still_abstract() -> None:
    class HalfRetriever(Retriever):
        @override
        async def index(self, documents: Iterable[Document]) -> None:
            return None

        @override
        async def clear(self) -> None:
            return None

    # ``query`` is unimplemented — instantiation must still fail.
    with pytest.raises(TypeError):
        HalfRetriever()  # type: ignore[abstract]


def test_fully_implemented_subclass_instantiates() -> None:
    class TinyRetriever(Retriever):
        @override
        async def index(self, documents: Iterable[Document]) -> None:
            return None

        @override
        async def query(self, text: str, k: int = 5) -> list[RetrievalHit]:
            return []

        @override
        async def clear(self) -> None:
            return None

    assert isinstance(TinyRetriever(), Retriever)
