"""Public legal pages (Step 7): /terms, /disclaimer, /removal.

All page text lives in Jinja templates under legal/templates/ so it can be
edited without touching Python. These pages are public and do not depend on
the auth layer or the listings API.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings

router = APIRouter(tags=["legal"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _context() -> dict:
    return {"contact_email": get_settings().legal_contact_email}


@router.get("/terms", response_class=HTMLResponse, include_in_schema=False)
def terms(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "terms.html", _context())


@router.get("/disclaimer", response_class=HTMLResponse, include_in_schema=False)
def disclaimer(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "disclaimer.html", _context())


@router.get("/removal", response_class=HTMLResponse, include_in_schema=False)
def removal(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "removal.html", _context())
