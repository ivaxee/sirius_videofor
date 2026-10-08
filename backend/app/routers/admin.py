"""API админки. Доступ — `Authorization: Bearer $ADMIN_TOKEN`."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from .. import admin as svc
from ..db import tx
from ..security import AdminDep

router = APIRouter(prefix="/api/admin", dependencies=[AdminDep])


class StatusIn(BaseModel):
    status: Literal["active", "hidden", "retired"]


@router.get("/summary")
def summary():
    with tx() as conn:
        return svc.summary(conn)


@router.get("/agreement")
def agreement(min_shared: int = Query(5, ge=2, le=100)):
    with tx() as conn:
        return svc.agreement(conn, min_shared)


@router.get("/export")
def export(
    format: Literal["json", "csv"] = "json",
    state: Literal["pending", "disputed", "done", "gold"] | None = None,
    min_confidence: float | None = Query(None, ge=0, le=1),
):
    with tx() as conn:
        rows = svc.export_rows(conn, state, min_confidence)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    if format == "csv":
        body, media = svc.to_csv(rows), "text/csv; charset=utf-8"
    else:
        body, media = json.dumps(rows, ensure_ascii=False, indent=1), "application/json"
    return Response(
        content=body, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="labels-{stamp}.{format}"'},
    )


@router.get("/reports")
def reports():
    with tx() as conn:
        return svc.reports(conn)


@router.post("/clips/{clip_id}/status")
def clip_status(clip_id: uuid.UUID, body: StatusIn):
    with tx() as conn:
        if not svc.set_clip_status(conn, clip_id, body.status):
            raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True}
