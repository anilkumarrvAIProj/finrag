"""
Model Orchestration Layer
-------------------------
Supports multiple providers for both embeddings and chat/LLM.

Set in .env:

  EMBEDDING_PROVIDER=openai        # openai | azure | ollama | huggingface | local
  LLM_PROVIDER=openai              # openai | azure | ollama

Embedding models by provider:
  openai       → text-embedding-3-large (paid)
  azure        → your Azure deployment (paid)
  ollama       → nomic-embed-text (free, runs locally)
  huggingface  → BAAI/bge-small-en-v1.5 (free, runs in container)
  local        → same as huggingface

LLM models by provider:
  openai  → gpt-4o (paid)
  azure   → your Azure deployment (paid)
  ollama  → llama3, mistral, phi3 etc. (free, runs locally)
"""
from functools import lru_cache
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ModelConfig:
    """Central model configuration — read once, used everywhere."""

    # ── Embedding provider ────────────────────────────────────────────────────
    @property
    def embedding_provider(self) -> str:
        return settings.embedding_provider.lower()

    @property
    def embedding_dims(self) -> int:
        dims = {
            "openai":      1536,
            "azure":       1536,
            "ollama":      768,
            "huggingface": 384,
            "local":       384,
        }
        return dims.get(self.embedding_provider, 384)

    @property
    def embedding_model_name(self) -> str:
        if self.embedding_provider == "openai":
            return settings.openai_embedding_model
        if self.embedding_provider == "azure":
            return settings.azure_openai_embedding_deployment
        if self.embedding_provider == "ollama":
            return settings.ollama_embedding_model
        # huggingface / local
        return settings.hf_embedding_model

    # ── LLM provider ──────────────────────────────────────────────────────────
    @property
    def llm_provider(self) -> str:
        return settings.llm_provider.lower()

    @property
    def llm_model_name(self) -> str:
        if self.llm_provider == "openai":
            return settings.openai_chat_model
        if self.llm_provider == "azure":
            return settings.azure_openai_chat_deployment
        if self.llm_provider == "ollama":
            return settings.ollama_chat_model
        return settings.openai_chat_model

    def log_config(self):
        logger.info(
            "Model configuration",
            embedding_provider=self.embedding_provider,
            embedding_model=self.embedding_model_name,
            embedding_dims=self.embedding_dims,
            llm_provider=self.llm_provider,
            llm_model=self.llm_model_name,
        )


@lru_cache
def get_model_config() -> ModelConfig:
    return ModelConfig()

model_config = get_model_config()
