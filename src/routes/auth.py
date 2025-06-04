from fastapi import APIRouter, HTTPException, Depends, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordRequestForm
from schemas.user import TokenResponse, CreateUserRequest
from core.config import settings
from core.db import db
from datetime import datetime, timezone, timedelta
import jwt, bcrypt

router = APIRouter(prefix="/api/auth")
security = HTTPBearer()

# Admin Login via JWT
def generate_jwt(username: str, role: str):
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

@router.post("/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await db.users.find_one({"username": form_data.username})
    if not user:
        raise HTTPException(401, "Credenciais inválidas")
    if not bcrypt.checkpw(form_data.password.encode(), user["password"].encode()):
        raise HTTPException(401, "Credenciais inválidas")

    payload = {
        "sub":  user["username"],
        "role": user.get("role", "user"),
        "exp":  datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return TokenResponse(accessToken=token, expiresIn=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)

# User creation Safe Security
@router.post("/create", status_code=201)
async def create_admin_user(
    data: CreateUserRequest,
    authorization: str = Header(..., alias="Authorization")
):
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(400, "Authorization header malformado")
    token = parts[1]

    if token != settings.ADMIN_CREATION_TOKEN:
        raise HTTPException(403, "Token de criação inválido")

    existing = await db.users.find_one({"username": data.username})
    if existing:
        raise HTTPException(400, "Username já existe")

    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(data.password.encode(), salt).decode()
    await db.users.insert_one({
        "username": data.username,
        "password": hashed
    })

    return {"success": True, "message": "Usuário criado"}