import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=255)
    organization_name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=8, max_length=255)


class MessageResponse(BaseModel):
    message: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    # Display hints only; the server re-checks on every admin request. Both are true only for the
    # configured Super Admin with a verified email.
    is_platform_admin: bool
    is_super_admin: bool = False
    email_verified: bool = False

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    user: UserResponse
    organizations: list["OrganizationSummary"]


class OrganizationSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str

    model_config = {"from_attributes": True}


class VerifyEmailRequest(BaseModel):
    token: str
