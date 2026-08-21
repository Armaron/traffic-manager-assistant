from pydantic import BaseModel, Field


class TelegramAuthUser(BaseModel):
    id: int
    display_name: str | None = None
    username: str | None = None
    phone_masked: str | None = None


class TelegramAuthStatus(BaseModel):
    configured: bool
    session_exists: bool = False
    authorized: bool = False
    auth_in_progress: bool = False
    user: TelegramAuthUser | None = None


class TelegramAuthStartRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=32)


class TelegramAuthCodeRequest(BaseModel):
    attempt_id: str = Field(min_length=8, max_length=128)
    code: str = Field(min_length=1, max_length=16)


class TelegramAuthPasswordRequest(BaseModel):
    attempt_id: str = Field(min_length=8, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class TelegramAuthCancelRequest(BaseModel):
    attempt_id: str | None = Field(default=None, max_length=128)


class TelegramAuthAttemptResponse(BaseModel):
    attempt_id: str | None = None
    state: str
    phone_masked: str | None = None
    user: TelegramAuthUser | None = None
