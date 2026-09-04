"""Chat-model and embedding access through configurable compatible endpoints.

Local runtimes such as Ollama, llama.cpp, and vLLM can share one client path;
provider selection therefore stays in configuration rather than business logic.
"""
from __future__ import annotations

from typing import Iterator

import numpy as np
from openai import OpenAI

from .config import settings

_llm = OpenAI(
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
    timeout=120.0,
    max_retries=2,
)
_embed = OpenAI(
    base_url=settings.embed_base_url,
    api_key=settings.embed_api_key,
    timeout=60.0,
    max_retries=2,
)

EMBED_BATCH = 64  # texts per embeddings request; keeps requests bounded


def _embed_request(texts: list[str]) -> list[list[float]]:
    resp = _embed.embeddings.create(model=settings.embed_model, input=texts)
    return [d.embedding for d in resp.data]


def _embed_resilient(text: str) -> list[float]:
    """Local embed models have small context windows, and token-dense text
    (e.g. tables of part numbers) can overflow them even within our word-count
    chunk limit. Halve the text until the model accepts it — a truncated
    embedding still retrieves far better than a failed ingest."""
    while True:
        try:
            return _embed_request([text])[0]
        except Exception:
            if len(text) < 200:
                raise
            text = text[: len(text) // 2]


def embed_texts(texts: list[str]) -> np.ndarray:
    """Return L2-normalized embeddings (float32) so inner product == cosine.
    Batched so arbitrarily large documents don't produce one huge request."""
    vec_batches = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        try:
            embeddings = _embed_request(batch)
        except Exception:
            # One bad text fails the whole request; isolate per text.
            embeddings = [_embed_resilient(t) for t in batch]
        vec_batches.append(np.array(embeddings, dtype="float32"))
    vecs = np.vstack(vec_batches)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


def embed_one(text: str) -> np.ndarray:
    return embed_texts([text])[0]


def generate_answer(messages: list[dict]) -> str:
    resp = _llm.chat.completions.create(
        model=settings.llm_model, messages=messages, temperature=0.1
    )
    return resp.choices[0].message.content or ""


def stream_answer(messages: list[dict]) -> Iterator[str]:
    """Yield answer text deltas as they arrive from the model."""
    stream = _llm.chat.completions.create(
        model=settings.llm_model, messages=messages, temperature=0.1, stream=True
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
