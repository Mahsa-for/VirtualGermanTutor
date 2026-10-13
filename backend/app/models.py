from typing import Any, Literal
from pydantic import BaseModel, Field


Level = Literal['A1', 'A2', 'B1']
Topic = Literal['ordering coffee', 'shopping', 'introducing yourself']


class SessionCreateRequest(BaseModel):
    level: Level
    topic: Topic


class SessionCreateResponse(BaseModel):
    session_id: str
    conversation_url: str
    max_duration_seconds: int
    mock_mode: bool


class SessionEndRequest(BaseModel):
    session_id: str = Field(min_length=1)


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
