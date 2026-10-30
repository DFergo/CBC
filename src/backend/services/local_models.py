"""Whether this backend image ships the local embedding/reranker stack.

The image is built with `INSTALL_LOCAL_MODELS=true` (PyTorch CPU,
sentence-transformers, llama-index-embeddings-huggingface and pre-downloaded
weights) or `false` (no local models; embeddings and reranking must go
through an API connection). Detection uses `find_spec`, so checking never
imports torch.
"""
import importlib.util
import logging
from functools import lru_cache

logger = logging.getLogger("local_models")

LOCAL_MODELS_HINT = (
    "This backend image was built without local models (INSTALL_LOCAL_MODELS=false). "
    "Configure an API connection in Admin → General → RAG Pipeline → Embedding / Reranker provider, "
    "or run an image built with INSTALL_LOCAL_MODELS=true."
)


class LocalModelsUnavailable(RuntimeError):
    """Local provider selected but the image has no local model stack."""


@lru_cache(maxsize=1)
def available() -> bool:
    try:
        return (
            importlib.util.find_spec("sentence_transformers") is not None
            and importlib.util.find_spec("llama_index.embeddings.huggingface") is not None
        )
    except (ImportError, ValueError):
        return False


def require(what: str) -> None:
    if not available():
        raise LocalModelsUnavailable(f"Local {what} unavailable. {LOCAL_MODELS_HINT}")
