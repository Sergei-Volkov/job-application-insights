from typing import Iterator
import hmac

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


def require_write_access(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if not settings.require_write_key:  # pragma: no cover
        return
    expected = settings.write_api_key.strip()
    if not expected:  # pragma: no cover — caught at startup when require_write_key=True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key is required but not configured. Set WRITE_API_KEY in .env.",
        )
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-API-Key")
