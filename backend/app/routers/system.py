from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..dependencies import get_db

router = APIRouter(tags=["system"])


@router.get("/health", summary="Check API health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok"}


@router.get("/version", summary="Return the running API version")
def version(request: Request) -> dict[str, str]:
    return {"version": request.app.version}
