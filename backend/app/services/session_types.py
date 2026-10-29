"""Internal snapshots; credentials require explicit access and are never exported."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class AuthContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UUID
    session_id: UUID
    name: str
    email: str
    session_expires_at: datetime


class SessionGrant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    context: AuthContext
    access_token: SecretStr = Field(exclude=True, repr=False)
    refresh_token: SecretStr = Field(exclude=True, repr=False)
    access_expires_at: datetime
