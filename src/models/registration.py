from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

class Registration(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    name: str
    email: EmailStr
    phone: str
    cpf: Optional[str]
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    videoUrl: str
    thumbnailUrl: str
    status: str = "pending"
    rating: Optional[int]
    comments: Optional[str]
    flaggedWinner: bool = False
    reviewedAt: Optional[datetime]