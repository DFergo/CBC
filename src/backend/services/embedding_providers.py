"""LlamaIndex-compatible embedding + reranker adapters for remote,
OpenAI-compatible-ish providers (Sprint 20).

Split out of `rag_service.py` (already 1600+ lines) to keep the provider
plumbing self-contained. Two classes:

- `ApiEmbedding(BaseEmbedding)` — POSTs to `{endpoint}/embeddings` with the
  standard OpenAI request/response shape
  (`{"model": ..., "input": [...]}` → `{"data": [{"embedding": [...], "index": N}, ...]}`).
  Verified against Daniel's oMLX server (`bge-m3-mlx-fp16`) in this sprint's
  research; the same shape is used by real OpenAI, vLLM, HF TEI, Infinity.

- `ApiRerank(BaseNodePostprocessor)` — POSTs to `{endpoint}/rerank` with the
  de-facto shape shared by oMLX/TEI/vLLM/Infinity
  (`{"model": ..., "query": ..., "documents": [...]}` →
  `{"results": [{"index": N, "relevance_score": F, "document": {...}}, ...]}`).
  This is NOT part of the official OpenAI API — a generic "openai_compatible"
  provider may not implement it. Documented in the admin UI.

Both classes never log the API key (only ever placed in the Authorization
header) and resolve it once at construction time via
`embedding_config_store.resolve_api_key`.
"""
import logging
from typing import Any, Optional

import httpx
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle

logger = logging.getLogger("embedding_providers")

DEFAULT_TIMEOUT = 30.0


class ApiEmbedding(BaseEmbedding):
    """OpenAI-compatible `/embeddings` client wrapped as a LlamaIndex
    `BaseEmbedding`. Drop-in replacement for `HuggingFaceEmbedding` in
    `rag_service._construct_embed_model` when provider is "omlx" or
    "openai_compatible".
    """

    api_endpoint: str
    api_key: Optional[str] = None
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def class_name(cls) -> str:
        return "ApiEmbedding"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(
                f"{self.api_endpoint.rstrip('/')}/embeddings",
                json={"model": self.model_name, "input": texts},
                headers=self._headers(),
            )
            r.raise_for_status()
            data = r.json().get("data", [])
        # OpenAI-style responses are not guaranteed to preserve input order;
        # `index` is authoritative.
        data.sort(key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    async def _aembed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                f"{self.api_endpoint.rstrip('/')}/embeddings",
                json={"model": self.model_name, "input": texts},
                headers=self._headers(),
            )
            r.raise_for_status()
            data = r.json().get("data", [])
        data.sort(key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    # --- sync (required by BaseEmbedding) ---
    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed([query])[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        # Batch path — used by rag_service's table-card embedding
        # (`get_text_embedding_batch`) and by LlamaIndex's ingest pipeline.
        # Real batching (one HTTP call for N texts) instead of N calls.
        return self._embed(texts)

    # --- async ---
    async def _aget_query_embedding(self, query: str) -> list[float]:
        return (await self._aembed([query]))[0]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return (await self._aembed([text]))[0]

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return await self._aembed(texts)


class ApiRerank(BaseNodePostprocessor):
    """De-facto `/rerank` client (oMLX / HF TEI / vLLM / Infinity shape)
    wrapped as a LlamaIndex `BaseNodePostprocessor`. Drop-in replacement for
    `SentenceTransformerRerank` when provider is "omlx" or
    "openai_compatible".

    NOT part of the official OpenAI API — a generic "openai_compatible"
    provider that only implements chat/embeddings will 404 here. That's
    surfaced to the admin via the health-check error message, not hidden.
    """

    api_endpoint: str
    api_key: Optional[str] = None
    model: str
    top_n: int = 8
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def class_name(cls) -> str:
        return "ApiRerank"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _postprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> list[NodeWithScore]:
        if not nodes:
            return nodes
        if query_bundle is None:
            return nodes[: self.top_n]

        documents = [n.node.get_content() for n in nodes]
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(
                    f"{self.api_endpoint.rstrip('/')}/rerank",
                    json={
                        "model": self.model,
                        "query": query_bundle.query_str,
                        "documents": documents,
                    },
                    headers=self._headers(),
                )
                r.raise_for_status()
                results: list[dict[str, Any]] = r.json().get("results", [])
        except Exception as e:
            logger.warning(f"ApiRerank call failed ({e}); returning unranked order")
            return nodes[: self.top_n]

        results.sort(key=lambda x: x.get("relevance_score", 0.0), reverse=True)
        out: list[NodeWithScore] = []
        for res in results[: self.top_n]:
            idx = res.get("index")
            if idx is None or not (0 <= idx < len(nodes)):
                continue
            nws = nodes[idx]
            nws.score = res.get("relevance_score", nws.score)
            out.append(nws)
        return out or nodes[: self.top_n]
