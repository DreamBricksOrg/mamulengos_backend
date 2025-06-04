from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional

class RegistrationInitRequest(BaseModel):
    name: str = Field(..., min_length=1)
    email: EmailStr
    phone: str = Field(..., min_length=1)
    videoContentType: str = Field(...)

class RegistrationInitResponse(BaseModel):
    id: str
    videoUploadUrl: str
    thumbnailUploadUrl: str

class RegistrationCompleteRequest(BaseModel):
    id: str

class RegistrationCompleteResponse(BaseModel):
    id: str
    name: str
    email: EmailStr
    phone: str
    videoUrl: str
    thumbnailUrl: str
    status: str
    createdAt: datetime

class SubmissionOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    videoUrl: str
    thumbnailUrl: str
    status: str
    createdAt: datetime
    rating: Optional[int]
    comments: Optional[str]
    flaggedWinner: Optional[bool]
