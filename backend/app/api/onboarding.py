"""Onboarding endpoint (Step 6).

The welcome window is shown once, right after a user's first login. The
frontend decides whether to show it from `has_seen_onboarding` in /auth/me
and calls POST /onboarding/seen when the window is closed.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models import User

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/seen")
def mark_onboarding_seen(
    user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Mark the welcome window as seen for the current user."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user.has_seen_onboarding:
        user.has_seen_onboarding = True
        db.commit()
    return {"has_seen_onboarding": True}
