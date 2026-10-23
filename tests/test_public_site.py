import json
from pathlib import Path

import pytest
from sqlalchemy import select

from tradeguard.db import session
from tradeguard.db.models import Run, ScanResult, Security
from tradeguard.market.service import import_csv
from tradeguard.public_site.export import export_site
from tradeguard.screening.service import scan
from tradeguard.workspace.schemas import Scope, WatchInput
from tradeguard.workspace.service import add_watch, today


def test_public_bundle_allowlist_excludes_private_state_and_escapes_html(database, tmp_path):
    from test_discipline import inputs

    from tradeguard.portfolio.service import save_snapshot

    imported = import_csv(Path("examples/bars.csv"))
    from datetime import date

    target = date.fromisoformat(imported["max_date"])
    result = scan(target, "synthetic")
    _, _, snapshot = inputs()
    snapshot.label = "PRIVATE_ACCOUNT_SENTINEL"
    snapshot.statement = "PRIVATE_STATEMENT_SENTINEL"
    save_snapshot(snapshot)
    scope = Scope(market="CN", source="synthetic")
    add_watch(WatchInput(**scope.model_dump(), symbol="600000.SH", reason="PRIVATE_WATCH_SENTINEL"))
    with session() as db, db.begin():
        security = db.get(Security, "600000.SH")
        security.name = '</script><script>alert("XSS")</script>'
        run = db.get(Run, result["run_id"])
        run.details = {**run.details, "private_debug": "PRIVATE_DEBUG_SENTINEL"}
        hit = db.scalar(select(ScanResult).where(ScanResult.run_id == result["run_id"]))
        if hit is None:
            hit = ScanResult(
                run_id=result["run_id"],
                symbol="600000.SH",
                trade_date=target,
                hits=["ma_golden_cross"],
                close="100",
                resonance_count=1,
            )
            db.add(hit)
        hit.metadata_snapshot = {"private_note": "PRIVATE_RESEARCH_SENTINEL"}
    output = tmp_path / "public"
    exported = export_site(scope, target, ["600000.SH"], output)
    assert exported["private_data"] is False
    assert {p.name for p in output.iterdir()} == {"index.html"}
    html = (output / "index.html").read_text()
    for private in [
        "PRIVATE_ACCOUNT_SENTINEL",
        "PRIVATE_STATEMENT_SENTINEL",
        "PRIVATE_WATCH_SENTINEL",
        "PRIVATE_DEBUG_SENTINEL",
        "PRIVATE_RESEARCH_SENTINEL",
        result["run_id"],
        "/api/portfolio",
        "TRADEGUARD_DATABASE_URL",
    ]:
        assert private not in html
    payload = html.split('<script id="public-data" type="application/json">')[1].split("</script>")[
        0
    ]
    assert "<script>" not in payload and "<" not in payload
    data = json.loads(payload)
    assert set(data) == {
        "schema_version",
        "generated_at",
        "trade_date",
        "market",
        "source",
        "adjustment",
        "summary",
        "stocks",
    }
    assert data["stocks"][0]["name"].startswith("</script>")
    assert all(bar["date"] <= str(target) for bar in data["stocks"][0]["bars"])
    with pytest.raises(ValueError, match="empty"):
        export_site(scope, target, ["600000.SH"], output)
    with pytest.raises(ValueError, match="market"):
        export_site(Scope(market="US", source="synthetic"), target, ["600000.SH"], tmp_path / "bad")
    with pytest.raises(ValueError, match="select"):
        export_site(scope, today(), [], tmp_path / "empty")
