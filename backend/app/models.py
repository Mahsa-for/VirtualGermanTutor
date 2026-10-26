from typing import Any, Literal
from pydantic import BaseModel, Field


Scenario = Literal['free', 'interview', 'shopping', 'doctor']
Level = Literal['A1', 'A2', 'B1']


class SetupRequest(BaseModel):
    """Bring-your-own-keys: the user's own Modal + Tavus credentials from the UI."""

    modal_token_id: str = Field(min_length=1)
    modal_token_secret: str = Field(min_length=1)
    tavus_api_key: str = Field(min_length=1)
    replica_id: str = Field(default='', description='Tavus replica id for the avatar face.')


class SetupStatusResponse(BaseModel):
    status: Literal['idle', 'deploying_model', 'creating_avatar', 'ready', 'error']
    step: str
    logs: list[str] = Field(default_factory=list)
    error: str = ''
    ready: bool = False


class SessionCreateRequest(BaseModel):
    scenario: Scenario = 'free'
    level: Level = 'A2'


class SessionCreateResponse(BaseModel):
    session_id: str
    conversation_url: str
    max_duration_seconds: int
    mock_mode: bool


class SessionEndRequest(BaseModel):
    session_id: str = Field(min_length=1)


class FeedbackItem(BaseModel):
    error: str = ''
    correction: str = ''
    rule: str = ''
    explanation: str = ''
    reference: str = ''
    utterance: str = ''


class FeedbackResponse(BaseModel):
    items: list[FeedbackItem] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    detail: str


class TavusMessage(BaseModel):
    role: str
    content: Any


class TavusChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[TavusMessage] = Field(default_factory=list)
    stream: bool = True
    metadata: dict[str, Any] | None = None
