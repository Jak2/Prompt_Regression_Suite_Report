from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ...config import get_settings
from ...storage.database import get_engine, get_session_factory
from ...storage.orm_models import TestCaseORM
from ...registry import Registry

router = APIRouter()


def _get_session():
    s = get_settings()
    from ...storage.database import get_engine, get_session_factory
    engine = get_engine(s.database_url)
    return get_session_factory(engine)


@router.get("/")
async def list_test_cases() -> list[dict]:
    """All registered test cases with their current baseline scores."""
    factory = _get_session()
    async with factory() as session:
        rows = await session.execute(select(TestCaseORM).order_by(TestCaseORM.name))
        return [
            {
                "id": r.id,
                "name": r.name,
                "prompt_file": r.prompt_file_path,
                "tags": r.tags,
                "expected_behavior": r.expected_behavior,
            }
            for r in rows.scalars()
        ]


@router.get("/{test_case_id}")
async def get_test_case(test_case_id: str) -> dict:
    factory = _get_session()
    async with factory() as session:
        row = await session.get(TestCaseORM, test_case_id)
        if not row:
            raise HTTPException(status_code=404, detail="Test case not found")
        return {
            "id": row.id,
            "name": row.name,
            "prompt_file": row.prompt_file_path,
            "expected_behavior": row.expected_behavior,
            "assertions": row.assertions,
            "tags": row.tags,
        }
