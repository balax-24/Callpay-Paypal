from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    paypal_env: str = "sandbox"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    app_url: str = "http://localhost:8000"

    providers_llm: str = "claude,openai,gemini,ollama,ollama_docker"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-5"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_docker_url: str = ""
    ollama_model: str = "deephat"

    # Payout policy: auto-send at or below this total; owner approval above; hard deny above the max.
    payout_auto_approve_limit: float = 50.0
    payout_max_total: float = 1000.0
    payout_max_item: float = 500.0
    crew_emails: str = ""  # comma-separated sandbox personal account emails for seeded crew

    # Voice: speech-to-text, text-to-speech, telephony and SMS chains (missing keys = skipped)
    providers_stt: str = "deepgram,assemblyai,openai_whisper"
    providers_tts: str = "elevenlabs,cartesia,openai_tts"
    providers_sms: str = "twilio,telnyx"
    deepgram_api_key: str = ""
    assemblyai_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    cartesia_api_key: str = ""
    cartesia_voice_id: str = "a0e99841-438c-4a64-b679-ae501e7d6091"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    telnyx_api_key: str = ""
    telnyx_from_number: str = ""

    # Workflow (Temporal primary, in-process fallback)
    temporal_address: str = ""
    temporal_task_queue: str = "callpay"
    api_internal_url: str = "http://localhost:8000"
    internal_api_token: str = ""
    payment_timeout_s: int = 900
    reminder_wait_s: int = 900
    fulfil_seconds: int = 20
    crew_share_pct: float = 10.0
    refund_auto_limit: float = 20.0

    # Object storage (S3-compatible; empty = local disk)
    s3_url: str = ""
    s3_bucket: str = "callpay"
    local_storage_dir: str = "./storage"

    # Analytics (ClickHouse primary, Postgres/SQLite fallback)
    clickhouse_url: str = ""
    clickhouse_user: str = "callpay"
    clickhouse_password: str = "callpay"

    database_url: str = "postgresql+asyncpg://callpay:callpay@postgres:5432/callpay"
    sqlite_fallback_url: str = "sqlite+aiosqlite:///./callpay.db"
    redis_url: str = "redis://redis:6379/0"
    kafka_bootstrap: str = "kafka:9092"

    @property
    def paypal_base_url(self) -> str:
        return (
            "https://api-m.paypal.com"
            if self.paypal_env == "live"
            else "https://api-m.sandbox.paypal.com"
        )

    @property
    def llm_order(self) -> list[str]:
        return [p.strip() for p in self.providers_llm.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
