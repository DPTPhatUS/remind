from typing import Any, Literal

from pydantic import BaseModel, Field


class LiveMessage(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionReadyMessage(BaseModel):
    type: Literal["session.ready"] = "session.ready"
    payload: dict[str, str]


class SessionErrorMessage(BaseModel):
    type: Literal["session.error"] = "session.error"
    payload: dict[str, str]


class ReminderUpdateMessage(BaseModel):
    type: Literal["reminder.update"] = "reminder.update"
    payload: dict[str, Any]


class RecognitionUpdateMessage(BaseModel):
    type: Literal["recognition.update"] = "recognition.update"
    payload: dict[str, Any]
