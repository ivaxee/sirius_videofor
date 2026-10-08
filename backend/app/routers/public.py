"""Публичное API для PWA."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import answers as svc
from ..assign import next_clips
from ..config import settings
from ..db import tx
from ..security import client_ip, current_user_id, issue_token, verify_media
from ..stats import invalidate_total, stop_stats
from ..storage import local_path

router = APIRouter(prefix="/api")

Locale = Literal["ru", "en"]
StopParam = Query(None, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")


class SessionIn(BaseModel):
    consent: bool
    locale: Locale = "ru"


class AnswerIn(BaseModel):
    assignment_id: uuid.UUID
    answer: Literal["cig", "vape", "no", "unsure"]
    sub_answer: Literal["scratch", "eat", "phone", "mask", "other"] | None = None
    response_time_ms: int = Field(ge=0, le=3_600_000)
    locale: Locale = "ru"


class ReportIn(BaseModel):
    assignment_id: uuid.UUID
    reason: Literal["inappropriate", "privacy", "broken", "other"]


class ConsentIn(BaseModel):
    consent: bool


def _raise(e: svc.ApiError):
    raise HTTPException(status_code=e.status, detail=e.code)


@router.get("/health")
def health():
    with tx() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


@router.post("/session")
def create_session(body: SessionIn):
    if not body.consent:
        raise HTTPException(status_code=400, detail="consent_required")
    with tx() as conn:
        uid = svc.create_user(conn, body.locale)
    return {"user_id": str(uid), "token": issue_token(uid)}


@router.get("/next-clips")
def get_next_clips(request: Request, stop: str | None = StopParam, n: int = Query(3, ge=1, le=10),
                   user_id: uuid.UUID = Depends(current_user_id)):
    with tx() as conn:
        result = next_clips(conn, user_id, stop, n, client_ip(request))
    if result.get("error") == "unknown_user":
        raise HTTPException(status_code=401, detail="unknown_user")
    if result.get("error") == "no_consent":
        raise HTTPException(status_code=403, detail="no_consent")
    return result


@router.post("/answers")
def post_answer(body: AnswerIn, request: Request, user_id: uuid.UUID = Depends(current_user_id)):
    try:
        with tx() as conn:
            result = svc.submit_answer(
                conn, user_id, body.assignment_id, body.answer, body.sub_answer,
                body.response_time_ms, client_ip(request), body.locale,
            )
    except svc.ApiError as e:
        _raise(e)
    invalidate_total()
    return result


@router.post("/reports")
def post_report(body: ReportIn, user_id: uuid.UUID = Depends(current_user_id)):
    try:
        with tx() as conn:
            return svc.report_clip(conn, user_id, body.assignment_id, body.reason)
    except svc.ApiError as e:
        _raise(e)


@router.get("/stats")
def get_stats(stop: str | None = StopParam):
    with tx() as conn:
        return stop_stats(conn, stop)


@router.get("/me")
def get_me(user_id: uuid.UUID = Depends(current_user_id)):
    try:
        with tx() as conn:
            return svc.me(conn, user_id)
    except svc.ApiError as e:
        _raise(e)


@router.post("/me/consent")
def post_consent(body: ConsentIn, user_id: uuid.UUID = Depends(current_user_id)):
    try:
        with tx() as conn:
            return svc.set_consent(conn, user_id, body.consent)
    except svc.ApiError as e:
        _raise(e)


@router.delete("/me")
def delete_me(user_id: uuid.UUID = Depends(current_user_id)):
    with tx() as conn:
        svc.delete_user(conn, user_id)
    invalidate_total()
    return {"ok": True}


@router.get("/media/{key:path}")
def media(key: str, exp: int, sig: str = Query(max_length=64)):
    """Отдача клипов при STORAGE_BACKEND=local. URL подписан и живёт CLIP_URL_TTL секунд."""
    if settings.storage_backend != "local" or not verify_media(key, exp, sig):
        raise HTTPException(status_code=403, detail="forbidden")
    path = local_path(key)
    if path is None:
        raise HTTPException(status_code=404, detail="not_found")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=600"})
