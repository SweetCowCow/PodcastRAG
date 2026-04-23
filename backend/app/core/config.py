from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    frontend_origin: str
    app_env: str = "development"
    app_debug: bool = False

    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    transcription_provider: str = "openai"
    openai_api_key: str | None = None
    zeabur_api_key: str | None = None
    openai_whisper_chunk_size_mb: int = 24
    openai_whisper_chunk_overlap_seconds: int = 0
    faster_whisper_model_size: str = "base"
    faster_whisper_compute_type: str = "int8"
    faster_whisper_device: str = "cpu"
    faster_whisper_model_dir: str = "/models/faster-whisper"

    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    r2_endpoint: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
