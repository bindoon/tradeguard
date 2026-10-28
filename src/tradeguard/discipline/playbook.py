"""Private, versioned reminders, separate from executable numeric rule profiles."""

from typing import Literal

from pydantic import Field
from sqlalchemy import select

from tradeguard.db import session
from tradeguard.db.models import ResearchReport
from tradeguard.portfolio.schemas import StrictModel


class PlaybookSource(StrictModel):
    document: str = Field(min_length=1, max_length=300)
    version: str = Field(min_length=1, max_length=80)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PlaybookSection(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    items: list[str] = Field(min_length=1, max_length=12)


class Playbook(StrictModel):
    type: Literal["portfolio_playbook_v1"] = "portfolio_playbook_v1"
    title: str = Field(min_length=1, max_length=100)
    sources: list[PlaybookSource] = Field(min_length=1, max_length=10)
    reminders: list[str] = Field(min_length=1, max_length=8)
    sections: list[PlaybookSection] = Field(min_length=1, max_length=8)
    notes: list[str] = Field(default_factory=list, max_length=8)


def save_playbook(playbook: Playbook) -> dict:
    with session() as db, db.begin():
        row = ResearchReport(payload=playbook.model_dump(mode="json"))
        db.add(row)
        db.flush()
        return {"report_id": row.id, "type": playbook.type, "title": playbook.title}


def latest_playbook() -> dict | None:
    with session() as db:
        row = db.scalar(
            select(ResearchReport)
            .where(ResearchReport.payload["type"].as_string() == "portfolio_playbook_v1")
            .order_by(ResearchReport.created_at.desc(), ResearchReport.id.desc())
            .limit(1)
        )
        if row is None:
            return None
        playbook = Playbook.model_validate(row.payload)
        return {
            **playbook.model_dump(mode="json"),
            "report_id": row.id,
            "created_at": row.created_at.isoformat(),
        }
