from functools import lru_cache
from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        env_file_encoding="utf-8",
        extra="ignore",          # ignore unknown env vars instead of erroring
    )

    # App
    app_env: str = "development"
    app_secret_key: str = "finrag-dev-secret-key"
    api_v1_prefix: str = "/api/v1"

    # CORS — hardcoded default, ignore .env value entirely to avoid parse issues
    # Override by setting CORS_ORIGINS=url1,url2 with no spaces and no quotes
    cors_origins: str = "http://localhost:7100,http://localhost:7101,http://localhost:3000,http://localhost:3001"

    @property
    def cors_origins_list(self) -> List[str]:
        """Always returns a clean list regardless of how cors_origins is set."""
        raw = self.cors_origins or ""
        # Strip surrounding quotes if present
        raw = raw.strip('"').strip("'")
        return [o.strip() for o in raw.split(",") if o.strip()]

    # PostgreSQL
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "finrag"
    postgres_user: str = "finrag"
    postgres_password: str = "finrag_dev_pw"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # S3 / MinIO
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_raw: str = "finrag-raw"
    s3_bucket_processed: str = "finrag-processed"
    s3_region: str = "us-east-1"

    # Weaviate
    weaviate_url: str = "http://weaviate:8080"
    weaviate_api_key: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-large"
    openai_chat_model: str = "gpt-4o"
    openai_embedding_dims: int = 1536

    # Azure OpenAI (optional)
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-02-01"
    azure_openai_chat_deployment: str = "gpt-4o"
    azure_openai_embedding_deployment: str = "text-embedding-3-large"

    @property
    def use_azure_openai(self) -> bool:
        return bool(self.azure_openai_endpoint)

    # Auth
    auth_domain: str = "your-tenant.auth0.com"
    auth_audience: str = "https://finrag-api"
    auth_algorithm: str = "RS256"

    # Ingestion
    max_upload_size_mb: int = 100
    ocr_confidence_threshold: float = 0.6
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 128

    # Retrieval
    top_k_retrieve: int = 20
    top_k_rerank: int = 5
    min_similarity_threshold: float = 0.5

    # Internet Search
    tavily_api_key: str = ""

    # Monitoring
    sentry_dsn: str = ""
    log_level: str = "INFO"


    # ─── Model Provider Selection ─────────────────────────────────────────────
    # embedding_provider: openai | azure | ollama | huggingface | local
    embedding_provider: str = "huggingface"
    # llm_provider: openai | azure | ollama
    llm_provider: str = "ollama"

    # ─── Ollama (free, local) ─────────────────────────────────────────────────
    ollama_base_url: str = "http://ollama:11434"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_chat_model: str = "llama3.2"

    # ─── HuggingFace local embeddings (free, runs in container) ──────────────
    hf_embedding_model: str = "BAAI/bge-small-en-v1.5"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

