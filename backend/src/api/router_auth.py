"""Authentication router — register, login, profile.

Security features:
- Password strength validation (min 8 chars, uppercase, lowercase, digit)
- Redis-backed rate limiting (survives restarts, works across workers)
- Input sanitization via Pydantic validators
"""

import re
import time
from collections import defaultdict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from src.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    Role,
)
from src.core.audit import log_action
from src.database.models import User
from src.database.session import get_db

logger = structlog.get_logger()
router = APIRouter()

# --- Rate Limiting ---
_RATE_LIMIT_WINDOW = 15 * 60  # 15 minutes
_LOGIN_MAX = 10
_REGISTER_MAX = 5

# Redis-backed rate limiter (falls back to in-memory)
_redis_client = None
_memory_store: dict[str, list[float]] = defaultdict(list)


def _get_redis():
    """Lazy-init Redis client for rate limiting."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            from src.core.config import get_settings
            settings = get_settings()
            _redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                decode_responses=True,
                socket_connect_timeout=2,
            )
            _redis_client.ping()
        except Exception:
            _redis_client = False  # Mark as unavailable
            logger.warning("rate_limiter_redis_unavailable", fallback="in-memory")
    return _redis_client if _redis_client is not False else None


def _check_rate_limit(request: Request, action: str, max_attempts: int):
    """Check rate limit by IP + action. Uses Redis if available, else in-memory.

    Raises HTTPException(429) if rate limit exceeded.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"ratelimit:{action}:{client_ip}"

    redis_cli = _get_redis()
    if redis_cli:
        try:
            current = redis_cli.incr(key)
            if current == 1:
                redis_cli.expire(key, _RATE_LIMIT_WINDOW)
            if current > max_attempts:
                raise HTTPException(
                    status_code=429,
                    detail=f"Quá nhiều yêu cầu. Thử lại sau {_RATE_LIMIT_WINDOW // 60} phút.",
                )
            return
        except HTTPException:
            raise
        except Exception:
            pass  # Fall through to in-memory

    # In-memory fallback
    now = time.time()
    _memory_store[key] = [t for t in _memory_store[key] if now - t < _RATE_LIMIT_WINDOW]
    if len(_memory_store[key]) >= max_attempts:
        raise HTTPException(
            status_code=429,
            detail=f"Quá nhiều yêu cầu. Thử lại sau {_RATE_LIMIT_WINDOW // 60} phút.",
        )
    _memory_store[key].append(now)


# --- Request Models ---

class RegisterRequest(BaseModel):
    """Registration request with password strength validation."""
    email: EmailStr
    full_name: str
    password: str
    role: str = "engineer"
    company: str = ""

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Enforce password complexity rules."""
        if len(v) < 8:
            raise ValueError("Mật khẩu phải có ít nhất 8 ký tự")
        if len(v) > 128:
            raise ValueError("Mật khẩu không được quá 128 ký tự")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Mật khẩu phải có ít nhất 1 chữ hoa (A-Z)")
        if not re.search(r"[a-z]", v):
            raise ValueError("Mật khẩu phải có ít nhất 1 chữ thường (a-z)")
        if not re.search(r"[0-9]", v):
            raise ValueError("Mật khẩu phải có ít nhất 1 chữ số (0-9)")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        """Sanitize full name — strip whitespace, check length."""
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Tên phải có ít nhất 2 ký tự")
        if len(v) > 255:
            raise ValueError("Tên không được quá 255 ký tự")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# --- Endpoints ---

@router.post("/register")
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Register a new user account."""
    _check_rate_limit(request, "register", _REGISTER_MAX)

    if req.role not in Role.ALL:
        raise HTTPException(400, f"Vai trò không hợp lệ. Chọn: {', '.join(Role.SELF_REGISTER)}")
    if req.role not in Role.SELF_REGISTER:
        raise HTTPException(403, "Vai trò này phải do quản trị viên cấp, không thể tự đăng ký")

    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(400, "Email đã được đăng ký")

    user = User(
        email=req.email,
        full_name=req.full_name,
        hashed_password=hash_password(req.password),
        role=req.role,
        company=req.company,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        {"sub": str(user.id), "email": user.email, "role": user.role}
    )
    log_action(
        "register",
        user_id=user.id,
        detail={"email": user.email, "role": user.role},
        ip_address=request.client.host if request.client else None,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
        },
    }


@router.post("/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Login and get access token."""
    _check_rate_limit(request, "login", _LOGIN_MAX)

    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(401, "Email hoặc mật khẩu không chính xác")

    token = create_access_token(
        {"sub": str(user.id), "email": user.email, "role": user.role}
    )
    log_action(
        "login",
        user_id=user.id,
        detail={"email": user.email},
        ip_address=request.client.host if request.client else None,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
        },
    }


@router.get("/me")
async def get_profile(current_user: dict = Depends(get_current_user)):
    """Get current user profile."""
    return current_user
