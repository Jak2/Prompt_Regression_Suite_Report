from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ...config import get_settings
from ...storage.baseline_manager import BaselineManager
from ...storage.orm_models import BaselineORM

router = APIRouter()


def _get_manager():
    s = get_settings()
    from ...storage.database import get_engine, get_session_factory
    engine = get_engine(s.database_url)
    factory = get_session_factory(engine)
    return BaselineManager(factory)


@router.get("/")
async def list_baselines() -> list[dict]:
    s = get_settings()
    from ...storage.database import get_engine, get_session_factory
    engine = get_engine(s.database_url)
    factory = get_session_factory(engine)
    async with factory() as session:
        rows = await session.execute(
            select(BaselineORM).order_by(BaselineORM.set_at.desc())
        )
        return [
            {
                "test_case_id": r.test_case_id,
                "score": r.score,
                "set_at": r.set_at.isoformat(),
                "set_by_commit": r.set_by_commit,
                "reason": r.reason,
            }
            for r in rows.scalars()
        ]


class ForceResetRequest(BaseModel):
    new_score: float
    reason: str
    commit_sha: str = ""


@router.post("/{test_case_id}/reset")
async def force_reset_baseline(test_case_id: str, body: ForceResetRequest) -> dict:
    """
    Rule 3: Forced baseline reset — requires a documented reason.
    Use this when you intentionally accept a behaviour change as the new standard.
    """
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail="reason field is required")
    manager = _get_manager()
    await manager.force_reset(
        test_case_id, body.new_score, body.reason, body.commit_sha
    )
    return {"status": "ok", "test_case_id": test_case_id, "new_score": body.new_score}
