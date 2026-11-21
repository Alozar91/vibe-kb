"""Конфигурация приложения: все env-переменные в одном месте (code-standards §2.1)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Источник настроек — переменные окружения с префиксом KB_ (см. deployment.md §2)."""

    model_config = SettingsConfigDict(env_prefix="KB_", env_file=".env", extra="ignore")

    app_name: str = "vibe-kb"
    debug: bool = False

    # БД
    db_url: str = "postgresql+psycopg://kb:kb@localhost:5432/kb"

    # Valkey (кэш/брокер)
    valkey_url: str = "redis://localhost:6379/0"

    # Silo (S3)
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket_files: str = "kb-files"
    s3_bucket_previews: str = "kb-previews"

    # Keycloak (АУТ-5)
    keycloak_issuer: str = "https://merch-vibe.ru/auth/realms/corp-kb"
    keycloak_audiences: str = "kb-web,kb-rag,kb-mcp"
    jwks_cache_ttl: int = 300

    # Модели (OpenAI-compatible)
    embeddings_base_url: str = ""
    embeddings_api_key: str = ""
    embeddings_model: str = "bge-m3"
    embeddings_dims: int = 1024

    # Идемпотентность (НФТ-9)
    idempotency_ttl_hours: int = 24

    # Системные админы (ПРВ-5, bootstrap): keycloak sub через запятую
    admin_subs: str = ""

    # Загрузка (НФТ-5; дефолт, переопределяется настройками в БД)
    upload_max_size_mb: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
