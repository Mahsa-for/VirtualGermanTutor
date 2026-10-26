from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_env: str = Field(default='development', alias='APP_ENV')
    # In mock mode the UI works without any Modal/Tavus keys (local placeholder session).
    mock_mode: bool = Field(default=True, alias='MOCK_MODE')
    port: int = Field(default=8080, alias='PORT')

    # Tavus REST endpoints (host defaults; no account secrets live here).
    tavus_persona_create_url: str = Field(
        default='https://tavusapi.com/v2/personas', alias='TAVUS_PERSONA_CREATE_URL'
    )
    tavus_session_create_url: str = Field(
        default='https://tavusapi.com/v2/conversations', alias='TAVUS_SESSION_CREATE_URL'
    )
    tavus_session_end_url_template: str = Field(
        default='https://tavusapi.com/v2/conversations/{session_id}/end',
        alias='TAVUS_SESSION_END_URL_TEMPLATE',
    )
    tavus_max_duration_seconds: int = Field(default=900, alias='TAVUS_MAX_DURATION_SECONDS')

    # Model served on the user's Modal account. Must match MODEL_NAME in the Modal app.
    modal_model_name: str = Field(default='Qwen/Qwen2.5-7B-Instruct', alias='MODAL_MODEL_NAME')
    modal_deploy_file: str = Field(
        default='modal_app/german_tutor_modal.py', alias='MODAL_DEPLOY_FILE'
    )

    # Lightweight endpoint protection.
    session_create_rate_limit_per_minute: int = Field(
        default=8, alias='SESSION_CREATE_RATE_LIMIT_PER_MINUTE'
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
