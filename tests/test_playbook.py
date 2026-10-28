import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from tradeguard.cli import app
from tradeguard.console import create_app
from tradeguard.db import session
from tradeguard.db.models import ResearchReport, RuleProfile, now
from tradeguard.discipline.playbook import Playbook, latest_playbook, save_playbook


def synthetic_playbook(title="Synthetic reminder"):
    return Playbook(
        title=title,
        sources=[{"document": "synthetic/manual.md", "version": "test-v1", "sha256": "a" * 64}],
        reminders=["Synthetic reminder, not personal policy"],
        sections=[{"title": "Synthetic plan", "items": ["Keep the original range explicit"]}],
        notes=["Narrative reminders do not activate numeric checks"],
    )


def test_playbook_cli_api_round_trip_and_empty_state(database, tmp_path):
    client = TestClient(create_app())
    assert client.get("/api/discipline/playbook").json() is None
    path = tmp_path / "playbook.json"
    payload = synthetic_playbook().model_dump(mode="json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = CliRunner().invoke(app, ["discipline", "playbook-import", "--file", str(path)])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["status"] == "success"
    response = client.get("/api/discipline/playbook")
    assert response.status_code == 200
    saved = response.json()
    assert saved["report_id"] == envelope["data"]["report_id"]
    assert saved["sources"] == payload["sources"]
    assert saved["sections"] == payload["sections"]
    assert saved["notes"] == payload["notes"]
    with session() as db:
        assert db.scalars(select(RuleProfile)).all() == []


def test_new_playbook_appends_version_and_ignores_other_research(database):
    first = save_playbook(synthetic_playbook("First synthetic version"))
    with session() as db, db.begin():
        row = db.get(ResearchReport, first["report_id"])
        row.created_at = now() - timedelta(days=1)
    second = save_playbook(synthetic_playbook("Second synthetic version"))
    with session() as db, db.begin():
        db.add(ResearchReport(payload={"type": "recommendation_v1", "title": "Other research"}))
    latest = latest_playbook()
    assert latest["report_id"] == second["report_id"]
    assert latest["title"] == "Second synthetic version"
    with session() as db:
        assert (
            db.get(ResearchReport, first["report_id"]).payload["title"] == "First synthetic version"
        )
