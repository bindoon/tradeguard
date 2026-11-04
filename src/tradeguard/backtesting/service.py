"""Shared CLI/HTTP service. All durable writes target the independent runtime DB."""

import inspect
from importlib.metadata import version

from sqlalchemy import select

from tradeguard.backtesting import data, engine, plugins, schemas, strategy
from tradeguard.backtesting.plugins import fingerprint, resolve
from tradeguard.backtesting.schemas import BacktestConfig
from tradeguard.db import session
from tradeguard.db.models import BacktestArtifact, Run, RunEvent, now


def engine_version() -> str:
    return fingerprint(
        {
            "sources": [
                inspect.getsource(module) for module in (data, engine, plugins, schemas, strategy)
            ],
            "runtime": {package: version(package) for package in ("pandas", "numpy", "pydantic")},
        }
    )


def preflight(config: BacktestConfig) -> dict:
    signals, portfolio, versions = resolve(config)
    _, manifest = data.freeze(config, signals, getattr(portfolio, "min_history", 1))
    return {"status": "success", "manifest": manifest, "plugins": versions}


def create(config: BacktestConfig) -> str:
    signals, portfolio, versions = resolve(config)
    slices, manifest = data.freeze(config, signals, getattr(portfolio, "min_history", 1))
    return _save(config, slices, manifest, versions)


def _save(config, slices, manifest, versions, replay_of=None, expected_hash=None) -> str:
    with session() as db, db.begin():
        run = Run(
            kind="backtest",
            status="queued",
            market=config.market,
            market_date=config.end,
            details={
                "name": config.name,
                "source": config.source,
                "adjustment": config.adjustment,
                "config": config.model_dump(mode="json"),
                "manifest": manifest,
                "plugins": versions,
                "engine_version": engine_version(),
                "replay_of": replay_of,
                "expected_result_hash": expected_hash,
            },
        )
        db.add(run)
        db.flush()
        for symbol, payload in slices.items():
            db.add(
                BacktestArtifact(
                    run_id=run.id,
                    key="input:" + symbol,
                    content_hash=fingerprint(payload),
                    payload=payload,
                )
            )
        db.add(RunEvent(run_id=run.id, stage="frozen", message="配置、插件版本和行情输入已冻结。"))
        return run.id


def _run_row(db, identifier: str, market=None, source=None, adjustment=None):
    row = db.get(Run, identifier)
    if (
        row is None
        or row.kind not in {"backtest", "backtest_study"}
        or (market is not None and row.market != market)
        or (source is not None and row.details["source"] != source)
        or (adjustment is not None and row.details["adjustment"] != adjustment)
    ):
        raise ValueError("当前市场、来源和复权下没有这个回测实验")
    return row


def _inputs(db, run) -> dict:
    rows = db.scalars(
        select(BacktestArtifact).where(
            BacktestArtifact.run_id == run.id, BacktestArtifact.key.like("input:%")
        )
    ).all()
    if any(fingerprint(row.payload) != row.content_hash for row in rows):
        raise ValueError("冻结行情校验失败")
    result = {row.payload["symbol"]: row.payload for row in rows}
    if fingerprint(result) != run.details["manifest"]["input_hash"]:
        raise ValueError("输入清单与行情切片不一致")
    return result


def execute(identifier: str) -> dict:
    try:
        with session() as db, db.begin():
            run = db.scalar(select(Run).where(Run.id == identifier).with_for_update())
            if run is None or run.kind != "backtest" or run.status != "queued":
                raise ValueError("回测不存在或已被执行")
            config = BacktestConfig.model_validate(run.details["config"])
            if run.details["engine_version"] != engine_version():
                raise ValueError("回测内核版本已变化；需恢复原版本或新建实验")
            signals, portfolio, _ = resolve(config, frozen=run.details["plugins"])
            slices = _inputs(db, run)
            manifest = run.details["manifest"]
            expected_hash = run.details.get("expected_result_hash")
            run.status = "running"

        def progress(done, total):
            with session() as db, db.begin():
                db.add(
                    RunEvent(
                        run_id=identifier,
                        stage="replay",
                        completed=done,
                        total=total,
                        message=f"已回放 {done}/{total} 个交易日。",
                    )
                )

        report = engine.run(config, slices, manifest, signals, portfolio, progress)
        if expected_hash and report["result_hash"] != expected_hash:
            raise ValueError("相同冻结输入的重放结果不一致，请检查策略确定性")
        with session() as db, db.begin():
            run = _run_row(db, identifier)
            db.add(
                BacktestArtifact(
                    run_id=identifier,
                    key="report",
                    content_hash=fingerprint(report),
                    payload=report,
                )
            )
            run.status, run.finished_at = "success", now()
            run.details = {
                **run.details,
                "metrics": report["metrics"],
                "result_hash": report["result_hash"],
            }
            db.add(
                RunEvent(
                    run_id=identifier, stage="complete", message="报告已保存，可在控制台查看。"
                )
            )
        return get(identifier)
    except Exception as exc:
        # A duplicate worker must not turn somebody else's completed/running run into failed.
        if isinstance(exc, ValueError) and str(exc) == "回测不存在或已被执行":
            raise
        with session() as db, db.begin():
            run = db.get(Run, identifier)
            if run and run.kind == "backtest" and run.status in {"queued", "running"}:
                message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                run.status, run.finished_at = "failed", now()
                run.details = {**run.details, "error": message}
                db.add(RunEvent(run_id=identifier, stage="failed", message=message))
        raise


def run(config: BacktestConfig) -> dict:
    return execute(create(config))


def get(identifier: str, market=None, source=None, adjustment=None) -> dict:
    with session() as db:
        row = _run_row(db, identifier, market, source, adjustment)
        artifact = db.get(BacktestArtifact, (identifier, "report"))
        if row.status == "success" and artifact is None:
            raise ValueError("回测报告缺失，请检查归档完整性")
        if artifact and fingerprint(artifact.payload) != artifact.content_hash:
            raise ValueError("已保存报告校验失败")
        events = db.scalars(
            select(RunEvent).where(RunEvent.run_id == identifier).order_by(RunEvent.id)
        ).all()
        return {
            "id": row.id,
            "status": row.status,
            "market": row.market,
            "created_at": row.started_at.isoformat(),
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            **row.details,
            "report": artifact.payload if artifact and row.kind == "backtest" else None,
            "study_report": artifact.payload if artifact and row.kind == "backtest_study" else None,
            "events": [
                {
                    "stage": item.stage,
                    "message": item.message,
                    "completed": item.completed,
                    "total": item.total,
                }
                for item in events
            ],
        }


def history(market: str, source: str | None = None, adjustment: str | None = None) -> list[dict]:
    from tradeguard.db.maintenance import retire_stale_runs

    retire_stale_runs()
    query = select(Run.id, Run.started_at).where(
        Run.kind.in_(["backtest", "backtest_study"]), Run.market == market
    )
    if source is not None:
        query = query.where(Run.details["source"].as_string() == source)
    if adjustment is not None:
        query = query.where(Run.details["adjustment"].as_string() == adjustment)
    with session() as db:
        ids = [
            row.id
            for row in sorted(db.execute(query), key=lambda item: item.started_at, reverse=True)[
                :200
            ]
        ]
        rows = (
            {row.id: row for row in db.scalars(select(Run).where(Run.id.in_(ids)))} if ids else {}
        )
    return [
        {
            "id": key,
            "status": rows[key].status,
            "created_at": rows[key].started_at.isoformat(),
            "name": rows[key].details["name"],
            "config": rows[key].details["config"],
            "experiment_type": rows[key].details.get("experiment_type", "single"),
            "metrics": rows[key].details.get("metrics"),
            "error": rows[key].details.get("error"),
        }
        for key in ids
    ]


def replay(identifier: str) -> dict:
    with session() as db:
        original = _run_row(db, identifier)
        if original.kind == "backtest_study":
            from tradeguard.backtesting import studies

            return studies.replay(identifier)
        if original.status != "success":
            raise ValueError("只能重放已成功的实验")
        if original.details["engine_version"] != engine_version():
            raise ValueError("回测内核版本已变化；重放需恢复原版本")
        config = BacktestConfig.model_validate(original.details["config"])
        resolve(config, frozen=original.details["plugins"])
        slices = _inputs(db, original)
        manifest, versions = original.details["manifest"], original.details["plugins"]
        expected_hash = original.details["result_hash"]
    result = execute(
        _save(config, slices, manifest, versions, replay_of=identifier, expected_hash=expected_hash)
    )
    if result["result_hash"] != expected_hash:
        raise ValueError("相同输入的重放结果不一致，请检查确定性")
    return result
