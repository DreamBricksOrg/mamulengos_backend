from pydantic import BaseModel, Field, EmailStr

class TokenResponse(BaseModel):
    accessToken: str
    expiresIn: int

class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
