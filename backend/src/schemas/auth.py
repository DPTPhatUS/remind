from pydantic import BaseModel, EmailStr, Field


class BootstrapAdminRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=8)
    patient_display_name: str = Field(min_length=1, max_length=160)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str


class CurrentUserResponse(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    role: str
