from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_env: str = Field(default='development', alias='APP_ENV')
    mock_mode: bool = Field(default=True, alias='MOCK_MODE')
    port: int = Field(default=8080, alias='PORT')
    public_base_url: str = Field(default='http://localhost:8080', alias='PUBLIC_BASE_URL')

    # Tavus
    tavus_api_key: str = Field(default='', alias='TAVUS_API_KEY')
    tavus_session_create_url: str = Field(default='', alias='TAVUS_SESSION_CREATE_URL')
    tavus_session_end_url_template: str = Field(default='', alias='TAVUS_SESSION_END_URL_TEMPLATE')
    tavus_session_payload_template: str = Field(default='', alias='TAVUS_SESSION_PAYLOAD_TEMPLATE')
    tavus_llm_auth_token: str = Field(default='', alias='TAVUS_LLM_AUTH_TOKEN')
    tavus_max_duration_seconds: int = Field(default=900, alias='TAVUS_MAX_DURATION_SECONDS')

    # Vertex AI
    gcp_project_id: str = Field(default='', alias='GCP_PROJECT_ID')
    gcp_region: str = Field(default='us-central1', alias='GCP_REGION')
    gemini_model: str = Field(default='gemini-2.0-flash-001', alias='GEMINI_MODEL')

    # Lightweight endpoint protection
    session_create_rate_limit_per_minute: int = Field(default=8, alias='SESSION_CREATE_RATE_LIMIT_PER_MINUTE')


@lru_cache
def get_settings() -> Settings:
    return Settings()
