"""Text embeddings for the AI Knowledge Assistant's retrieval step
(Part 4: RAG over product documentation). Uses the same server-side
OpenAI client as every other AI call -- the key never reaches the
frontend.
"""

from __future__ import annotations

from app.ai.client import get_openai_client
from app.config import get_settings


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    client = get_openai_client()
    response = client.embeddings.create(model=settings.openai_embedding_model, input=texts)
    return [item.embedding for item in response.data]
