"""HTTP-обработчики статусов (api-spec §4: POST /materials/{id}/transitions)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal, get_db
from app.common import audit
from app.common.db import UoW
from app.common.security.jwt import Principal
from app.domain.statuses import service
from app.models.materials import Material

router = APIRouter(tags=["statuses"])


class TransitionIn(BaseModel):
    to: str = Field(pattern="^(draft|on_review|confirmed|archived|deleted)$")


class TransitionOut(BaseModel):
    id: uuid.UUID
    status: str
    current_version_id: uuid.UUID | None

    model_config = {"from_attributes": True}


@router.post("/materials/{material_id}/transitions", response_model=TransitionOut)
def transition(
    material_id: uuid.UUID,
    payload: TransitionIn,
    x_request_id: uuid.UUID | None = None,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Смена статуса (СТАТ-2; Idempotency-Key рекомендован — X-Request-Id как request_id)."""

    with UoW(session) as uow:
        m = service.transition(uow, principal, material_id, payload.to, x_request_id)
        audit.record(uow.session, None, "status.change", "material", m.id,
                     {"from": "journal", "to": str(m.status)}, request_id=x_request_id)
        return TransitionOut(id=m.id, status=str(m.status), current_version_id=m.current_version_id)


@router.get("/materials/{material_id}/journal")
def journal(
    material_id: uuid.UUID,
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Журнал переходов (СТАТ-3, append-only)."""

    return service.journal(session, principal, material_id)


def _material_out(m: Material) -> dict:
    return {"id": str(m.id), "status": str(m.status)}
