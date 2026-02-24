"""
Authentication utilities: JWT tokens, password hashing (bcrypt), and Google OAuth.
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Cookie
from sqlalchemy.orm import Session
import os
import secrets
from dotenv import load_dotenv

from backend.database import get_db
from backend.models import User

load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

# JWT configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production-min-32-chars")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password (bcrypt)."""
    if isinstance(hashed_password, str):
        hashed_password = hashed_password.encode("utf-8")
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> User:
    """
    Get the current authenticated user from JWT token in HTTPOnly cookie.
    Raises HTTPException if user is not authenticated.
    """
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(access_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_raw = payload.get("sub")
    user_id = int(user_id_raw) if user_id_raw is not None else None
    if user_id is None or user_id_raw is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_current_user_optional(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Get current user if authenticated; return None otherwise."""
    if not access_token:
        return None
    payload = decode_access_token(access_token)
    if payload is None:
        return None
    user_id_raw = payload.get("sub")
    if user_id_raw is None:
        return None
    try:
        user_id = int(user_id_raw)
    except (ValueError, TypeError):
        return None
    return db.query(User).filter(User.id == user_id).first()


def authenticate_user(db: Session, identifier: str, password: str) -> Optional[User]:
    """
    Authenticate a user by email OR username and password.
    `identifier` can be either the email address or the username.
    """
    user = (
        db.query(User)
        .filter((User.email == identifier) | (User.username == identifier))
        .first()
    )
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def verify_google_token(credential: str) -> Tuple[str, str]:
    """
    Verify Google ID token and return (email, name).
    Raises HTTPException if invalid.
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Sign-In is not configured (GOOGLE_CLIENT_ID missing)",
        )
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
        if idinfo.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            raise HTTPException(status_code=400, detail="Invalid token issuer")
        email = idinfo.get("email")
        name = idinfo.get("name") or idinfo.get("email", "").split("@")[0] or "User"
        if not email:
            raise HTTPException(status_code=400, detail="Email not provided by Google")
        return email, name
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid Google token")
    except Exception as e:
        raise HTTPException(status_code=400, detail="Google sign-in failed")


def get_or_create_user_google(db: Session, email: str, name: str) -> User:
    """Find user by email or create new user for Google sign-in. Returns User."""
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    username = name.strip() or email.split("@")[0]
    base = username
    n = 0
    while db.query(User).filter(User.username == username).first():
        n += 1
        username = f"{base}{n}"
    password_placeholder = get_password_hash(secrets.token_hex(32))
    user = User(
        email=email,
        username=username,
        hashed_password=password_placeholder,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
