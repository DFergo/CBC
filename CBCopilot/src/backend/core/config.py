# Adapted from HRDDHelper/src/backend/core/config.py
# CBC-specific changes:
#   - removed letta_compression_threshold (handled by context_compressor later)
#   - added rag_watcher_enabled + rag_watcher_debounce_seconds (SPEC §4.3, §6.1)
#   - removed reporter LLM slot (ADR-004)
import json
import os
from pydantic import BaseModel


class BackendConfig(BaseModel):
    role: str = "backend"
    lm_studio_endpoint: str = "http://localhost:1234/v1"
    lm_studio_model: str = "qwen3-235b-a22b"
    ollama_endpoint: str = "http://localhost:11434"
    ollama_summariser_model: str = "qwen2.5:7b"
    ollama_num_ctx: int = 8192
    rag_documents_path: str = "./data/documents"
    rag_index_path: str = "./data/rag_index"
    rag_chunk_size: int = 512
    rag_similarity_top_k: int = 5
    rag_embedding_model: str = "all-MiniLM-L6-v2"
    rag_watcher_enabled: bool = True
    rag_watcher_debounce_seconds: int = 5
    streaming_enabled: bool = True
    stream_chunk_size: int = 1
    poll_interval_seconds: int = 2
    sessions_path: str = "./data/sessions"
    prompts_path: str = "./data/prompts"
    campaigns_path: str = "./data/campaigns"
    guardrails_enabled: bool = True
    guardrail_max_triggers: int = 3
    file_max_size_mb: int = 25
    session_token_reuse_cooldown_days: int = 30


def load_config() -> BackendConfig:
    config_path = os.environ.get("DEPLOYMENT_JSON_PATH", "config/deployment_backend.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
        return BackendConfig(**data)
    return BackendConfig()


config = load_config()
