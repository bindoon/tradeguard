from datetime import timedelta
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from tradeguard.cli import app
from tradeguard.db import session
from tradeguard.db.models import ResearchReport, Run, ScanResult, ScanSummary, Security
from tradeguard.research.recommendations import Submission, latest, prepare, submit
from tradeguard.screening.availability import today
from tradeguard.workspace.schemas import Scope


def seed():
    target = today() - timedelta(days=1)
    with session() as db, db.begin():
        db.add(
            Security(symbol="600000.SH", name="Synthetic candidate", market="CN", currency="CNY")
        )
        run = Run(
            kind="scan",
            status="partial",
            market="CN",
            market_date=target,
            details={"source": "fixture", "adjustment": "forward"},
        )
        db.add(run)
        db.flush()
        db.add(
            ScanResult(
                run_id=run.id,
                symbol="600000.SH",
                trade_date=target,
                hits=["box_breakout"],
                resonance_count=1,
                close=Decimal("10.00000001"),
                metadata_snapshot={
                    "name": "Synthetic candidate",
                    "strategy_details": [
                        {"title": "箱体突破", "reason": "测试信号", "metadata": {"box_top": 9}}
                    ],
                },
            )
        )
        db.add(
            ScanSummary(
                run_id=run.id,
                market="CN",
                trade_date=target,
                source="fixture",
                adjustment="forward",
                status="partial",
                market_regime="unknown",
                universe_count=2,
                scanned_count=1,
                hit_count=1,
                resonance_count=0,
            )
        )
    return target


def draft(pack):
    return {
        "evidence_pack_id": pack["evidence_pack_id"],
        "author": "test-agent",
        "methodology": "先验证候选证据，再比较技术信号；不将命中数量当作胜率。",
        "summary": "仅根据技术扫描安排后续研究优先级，尚缺基本面证据。",
        "picks": [
            {
                "symbol": "600000.SH",
                "thesis": "候选命中箱体突破，但仍需检查突破是否延续。",
                "evidence_ids": [pack["candidates"][0]["evidence_id"]],
                "risks": ["未验证公告和突破持续性"],
                "invalidation": "后续收盘跌回箱体则重新评估",
                "next_step": "先核验公告和量价，不直接下单",
            }
        ],
        "abstention_reason": "仅有一个候选，不凑五只",
    }


def test_frozen_evidence_and_scope_isolation(database):
    target = seed()
    scope = Scope(market="CN", source="fixture")
    pack = prepare(scope, target)
    assert pack["scan_status"] == "partial"
    assert pack["candidates"][0]["close"] == "10.00000001"
    assert pack["candidates"][0]["sector_strength"] is None
    saved = submit(Submission.model_validate(draft(pack)))
    assert saved["execution_eligibility"] == "needs_input"
    assert saved["picks"][0]["rank"] == 1
    with session() as db, db.begin():
        row = db.get(ScanResult, (pack["scan_run_id"], "600000.SH"))
        row.close = Decimal("99")
    assert latest(scope)["picks"][0]["evidence"]["close"] == "10.00000001"
    assert latest(Scope(market="US", source="fixture")) is None
    assert latest(Scope(market="CN", source="fixture", adjustment="none")) is None
    assert latest(scope, target - timedelta(days=1)) is None
    with pytest.raises(ValueError):
        prepare(scope, today() + timedelta(days=1))
    with pytest.raises(ValueError):
        prepare(Scope(market="CN", source="other"), target)


def test_reject_invented_candidates_cross_pack_refs_and_force_five(database):
    target = seed()
    scope = Scope(market="CN", source="fixture")
    pack = prepare(scope, target)
    other = prepare(scope, target)
    data = draft(pack)
    data["picks"][0]["symbol"] = "AAPL.US"
    with pytest.raises(ValueError, match="证据"):
        submit(Submission.model_validate(data))
    data = draft(pack)
    # Another pack for a different run must not be accepted as evidence.
    data["picks"][0]["evidence_ids"] = ["scan:unrelated:600000.SH"]
    with pytest.raises(ValueError, match="证据"):
        submit(Submission.model_validate(data))
    data = draft(other)
    data["picks"] *= 2
    with pytest.raises(ValueError, match="重复"):
        Submission.model_validate(data)
    data = draft(pack)
    data["abstention_reason"] = None
    with pytest.raises(ValueError, match="不凑数"):
        Submission.model_validate(data)
    data = draft(pack)
    data["picks"] = []
    saved = submit(Submission.model_validate(data))
    assert saved["picks"] == []
    with session() as db:
        assert db.get(ResearchReport, pack["evidence_pack_id"]).payload["candidates"]


def test_cli_roundtrip_and_empty_read(database, tmp_path):
    import json

    runner = CliRunner()
    empty = runner.invoke(app, ["research", "shortlist", "--source", "fixture"])
    assert empty.exit_code == 0, empty.output
    assert json.loads(empty.output)["data"]["recommendation"] is None
    target = seed()
    prepared = runner.invoke(
        app, ["research", "prepare", "--date", str(target), "--source", "fixture"]
    )
    assert prepared.exit_code == 0, prepared.output
    pack = json.loads(prepared.output)["data"]
    path = tmp_path / "shortlist.json"
    path.write_text(json.dumps(draft(pack)), encoding="utf-8")
    saved = runner.invoke(app, ["research", "shortlist-save", "--file", str(path)])
    assert saved.exit_code == 0, saved.output
    assert json.loads(saved.output)["data"]["picks"][0]["symbol"] == "600000.SH"
