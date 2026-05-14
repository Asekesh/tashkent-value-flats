"""Server-rendered admin panel at /admin (admins only)."""
from __future__ import annotations

import math
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.admin.metrics import active_plan_by_user, dashboard_metrics
from app.auth.dependencies import require_admin
from app.db.session import get_db
from app.models import User

router = APIRouter(prefix="/admin", tags=["admin-panel"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

PAGE_SIZE = 25


@router.get("")
def admin_dashboard(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"admin": admin, "metrics": dashboard_metrics(db)},
    )


@router.get("/users")
def admin_users(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    q: str = Query("", max_length=120),
):
    stmt = select(User)
    query = q.strip()
    if query:
        filters = [User.username.ilike(f"%{query}%")]
        if query.isdigit():
            filters.append(User.telegram_id == int(query))
        stmt = stmt.where(or_(*filters))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    pages = max(math.ceil(total / PAGE_SIZE), 1)
    page = min(page, pages)
    users = list(
        db.scalars(
            stmt.order_by(User.created_at.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        ).all()
    )
    plan_map = active_plan_by_user(db, [u.id for u in users])

    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "admin": admin,
            "users": users,
            "plan_map": plan_map,
            "page": page,
            "pages": pages,
            "total": total,
            "q": query,
        },
    )


def _redirect_to_users(request: Request) -> RedirectResponse:
    referer = request.headers.get("referer")
    return RedirectResponse(url=referer or "/admin/users", status_code=303)


@router.post("/users/{user_id}/role")
def update_role(
    request: Request,
    user_id: int,
    role: str = Form(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = role
    db.commit()
    return _redirect_to_users(request)


@router.post("/users/{user_id}/account-type")
def update_account_type(
    request: Request,
    user_id: int,
    account_type: str = Form(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if account_type not in ("individual", "agent"):
        raise HTTPException(status_code=400, detail="Invalid account type")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.account_type = account_type
    db.commit()
    return _redirect_to_users(request)
