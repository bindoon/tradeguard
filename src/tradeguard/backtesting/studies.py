"""Same-input experiments and independently funded sleeves, sharing the daily engine."""

import inspect
import math
import sys
from decimal import Decimal
from itertools import combinations
from typing import Literal, Self

import pandas as pd
from pydantic import Field, model_validator
from sqlalchemy import select

from tradeguard.backtesting import data, engine, service
from tradeguard.backtesting.plugins import fingerprint, resolve
from tradeguard.backtesting.schemas import BacktestConfig, StrictModel
from tradeguard.db import session
from tradeguard.db.models import BacktestArtifact, Run, RunEvent, now

ZERO = Decimal(0)
ONE = Decimal(1)
COMMON_FIELDS = (
    "market",
    "currency",
    "source",
    "adjustment",
    "price_model",
    "frequency",
    "start",
    "end",
    "symbols",
    "benchmark",
    "initial_cash",
    "missing_data",
    "execution",
)


class StudyCase(StrictModel):
    key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    config: BacktestConfig
    weight: Decimal = Field(default=Decimal("0.5"), gt=0, le=1)


class StudyConfig(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    mode: Literal["comparison", "allocation"] = "comparison"
    cases: list[StudyCase] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if len({case.key for case in self.cases}) != len(self.cases):
            raise ValueError("策略方案标识不可重复")
        base = self.cases[0].config.model_dump(include=set(COMMON_FIELDS))
        for case in self.cases[1:]:
            values = case.config.model_dump(include=set(COMMON_FIELDS))
            if values != base:
                different = ", ".join(key for key in COMMON_FIELDS if values[key] != base[key])
                raise ValueError(f"共同设置必须一致：{different}")
        if self.mode == "allocation" and sum((c.weight for c in self.cases), ZERO) > ONE:
            raise ValueError("初始资金比例合计不能超过 100%")
        return self


def version() -> str:
    return fingerprint(
        {
            "engine": service.engine_version(),
            "studies": inspect.getsource(sys.modules[__name__]),
        }
    )


def effective_config(config: StudyConfig, case: StudyCase) -> BacktestConfig:
    values = case.config.model_dump()
    if config.mode == "allocation":
        values["initial_cash"] *= case.weight
        values["execution"]["prior_volume_fraction"] *= case.weight
    return BacktestConfig.model_validate(values)


def prepare(config: StudyConfig, frozen=None):
    prepared = []
    for case in config.cases:
        cfg = effective_config(config, case)
        signals, strategy, versions = resolve(cfg, frozen=frozen[case.key] if frozen else None)
        required = max([strategy.min_history, *[s.min_history for s in signals.values()]])
        prepared.append((case, cfg, signals, strategy, versions, required))
    return prepared


def _freeze(config):
    prepared = prepare(config)
    required = max(item[5] for item in prepared)
    slices, manifest = data.freeze(config.cases[0].config, {}, required)
    versions = {item[0].key: item[4] for item in prepared}
    return slices, manifest, versions, prepared


def preflight(config: StudyConfig) -> dict:
    _, manifest, versions, prepared = _freeze(config)
    return {
        "status": "success",
        "manifest": manifest,
        "plugins": versions,
        "cases": [
            {
                "key": c.key,
                "name": cfg.name,
                "initial_cash": str(cfg.initial_cash),
                "required_history": required,
            }
            for c, cfg, _, _, _, required in prepared
        ],
    }


def _save(config, slices, manifest, versions, replay_of=None, expected_hash=None):
    base = config.cases[0].config
    with session() as db, db.begin():
        run = Run(
            kind="backtest_study",
            status="queued",
            market=base.market,
            market_date=base.end,
            details={
                "name": config.name,
                "source": base.source,
                "adjustment": base.adjustment,
                "config": base.model_dump(mode="json"),
                "study_config": config.model_dump(mode="json"),
                "experiment_type": config.mode,
                "manifest": manifest,
                "plugins": versions,
                "engine_version": version(),
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
        db.add(
            RunEvent(
                run_id=run.id, stage="frozen", message="所有策略共享的行情、配置与版本已冻结。"
            )
        )
        return run.id


def create(config: StudyConfig) -> str:
    slices, manifest, versions, _ = _freeze(config)
    return _save(config, slices, manifest, versions)


def _holdings(points):
    groups: dict[str, list] = {}
    for point in points:
        for holding in point["holdings"]:
            groups.setdefault(holding["symbol"], []).append(holding)
    result = []
    for symbol, holdings in sorted(groups.items()):
        quantity = sum(h["quantity"] for h in holdings)
        value = sum((Decimal(h["value"]) for h in holdings), ZERO)
        cost = sum((Decimal(h["average_cost"]) * h["quantity"] for h in holdings), ZERO)
        result.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "average_cost": str(cost / quantity),
                "price": str(value / quantity),
                "value": str(value),
                "unrealized_pnl": str(value - cost),
                "stale": any(h["stale"] for h in holdings),
            }
        )
    return result


def aggregate(config: StudyConfig, cases: list[dict], reserved: Decimal) -> dict:
    base = config.cases[0].config
    curve: list[dict] = []
    orders: list[dict] = []
    trades: list[dict] = []
    peak = base.initial_cash
    for index, day in enumerate(cases[0]["report"]["curve"]):
        points = [case["report"]["curve"][index] for case in cases]
        if any(p["date"] != day["date"] for p in points):
            raise ValueError("策略观察日不一致，不能汇总")
        cash = reserved + sum((Decimal(p["cash"]) for p in points), ZERO)
        market_value = sum((Decimal(p["market_value"]) for p in points), ZERO)
        equity = cash + market_value
        peak = max(peak, equity)
        benchmark = day["benchmark_equity"]
        curve.append(
            {
                "date": day["date"],
                "cash": str(cash),
                "market_value": str(market_value),
                "equity": str(equity),
                "drawdown": str(equity / peak - ONE),
                "exposure": str(market_value / equity) if equity else "0",
                "holdings": _holdings(points),
                "benchmark_equity": str(
                    Decimal(benchmark) / Decimal(cases[0]["initial_cash"]) * base.initial_cash
                )
                if benchmark
                else None,
            }
        )
    for case in cases:
        ids = {}
        for order in case["report"]["orders"]:
            ids[order["id"]] = len(orders) + 1
            orders.append({**order, "id": ids[order["id"]], "case_key": case["key"]})
        trades.extend(
            {**trade, "order_id": ids[trade["order_id"]], "case_key": case["key"]}
            for trade in case["report"]["trades"]
        )
    trades.sort(key=lambda t: (t["date"], t["case_key"], t["order_id"]))
    metrics = engine.calculate_metrics(base.initial_cash, curve, trades)
    # Divide profit directly to avoid cancellation of leading digits in equity/initial - 1.
    metrics["total_return"] = str(
        (Decimal(curve[-1]["equity"]) - base.initial_cash) / base.initial_cash
    )
    benchmark_return = cases[0]["report"]["metrics"]["benchmark_return"]
    metrics["benchmark_return"] = benchmark_return
    metrics["excess_return"] = (
        str(Decimal(metrics["total_return"]) - Decimal(benchmark_return))
        if benchmark_return is not None
        else None
    )
    warnings = list(dict.fromkeys(w for c in cases for w in c["report"]["warnings"]))
    warnings.append(
        "初始资金分账后不跨策略调拨或恢复比例；同股订单不净额撮合，各子策略分别收取费用。"
    )
    warnings.append(
        "成交量额度按初始比例分摊；各策略的持仓/仓位上限独立生效，未另设组合级单股集中度限制。"
    )
    result = {
        "schema_version": 1,
        "currency": base.currency,
        "price_model": base.price_model,
        "metrics": metrics,
        "curve": curve,
        "orders": orders,
        "trades": trades,
        "positions": curve[-1]["holdings"],
        "warnings": warnings,
        "assumptions": {
            "allocation": "initial_independent_sleeves",
            "cash_transfers": False,
            "order_netting": False,
            "liquidity": "initial_weight_share",
            "reserved_cash": str(reserved),
            "contribution_rounding": "last_sleeve_decimal_residual",
        },
    }
    result["result_hash"] = fingerprint(result)
    return result


def summarize(config: StudyConfig, cases: list[dict], manifest: dict) -> dict:
    base = config.cases[0].config
    reserved = (
        base.initial_cash - sum((Decimal(c["initial_cash"]) for c in cases), ZERO)
        if config.mode == "allocation"
        else ZERO
    )
    correlations = []
    for left, right in combinations(cases, 2):

        def returns(case):
            values = [Decimal(p["equity"]) for p in case["report"]["curve"]]
            return pd.Series(
                [
                    float(b / a - ONE) if a > ZERO else None
                    for a, b in zip(values, values[1:], strict=False)
                ],
                dtype=float,
            )

        paired = pd.concat([returns(left), returns(right)], axis=1).dropna()
        a, b = paired.iloc[:, 0], paired.iloc[:, 1]
        value = float(a.corr(b)) if len(a) >= 20 and a.std() > 0 and b.std() > 0 else None
        correlations.append(
            {
                "left": left["key"],
                "right": right["key"],
                "observations": len(a),
                "value": value if value is not None and math.isfinite(value) else None,
            }
        )
    portfolio = aggregate(config, cases, reserved) if config.mode == "allocation" else None
    total_equity = Decimal(portfolio["metrics"]["final_equity"]) if portfolio else None
    attribution = []
    if portfolio:
        assigned = ZERO
        total_return = Decimal(portfolio["metrics"]["total_return"])
        for index, case in enumerate(cases):
            final = Decimal(case["report"]["metrics"]["final_equity"])
            profit = final - Decimal(case["initial_cash"])
            direct = profit / base.initial_cash
            contribution = direct if index < len(cases) - 1 else total_return - assigned
            assigned += contribution
            attribution.append(
                {
                    "key": case["key"],
                    "name": case["config"]["name"],
                    "initial_cash": case["initial_cash"],
                    "profit": str(profit),
                    "return_contribution": str(contribution),
                    "rounding_adjustment": str(contribution - direct),
                    "final_weight": str(final / total_equity) if total_equity else None,
                }
            )
    report = {
        "schema_version": 1,
        "mode": config.mode,
        "input_hash": manifest["input_hash"],
        "cases": cases,
        "correlations": correlations,
        "portfolio": portfolio,
        "reserved_cash": str(reserved),
        "attribution": attribution,
    }
    report["result_hash"] = fingerprint(report)
    return report


def execute(identifier: str) -> dict:
    claimed = False
    try:
        with session() as db, db.begin():
            row = db.scalar(select(Run).where(Run.id == identifier).with_for_update())
            if row is None or row.kind != "backtest_study" or row.status != "queued":
                raise ValueError("回测不存在或已被执行")
            claimed = True
            if row.details["engine_version"] != version():
                raise ValueError("回测内核版本已变化；需恢复原版本或新建实验")
            config = StudyConfig.model_validate(row.details["study_config"])
            prepared = prepare(config, row.details["plugins"])
            slices = service._inputs(db, row)
            manifest = row.details["manifest"]
            expected = row.details.get("expected_result_hash")
            row.status = "running"
        cases = []
        for index, (case, cfg, signals, strategy, versions, _) in enumerate(prepared):

            def progress(done, total, case_index=index, case_name=cfg.name):
                with session() as db, db.begin():
                    db.add(
                        RunEvent(
                            run_id=identifier,
                            stage="replay",
                            completed=case_index * total + done,
                            total=len(prepared) * total,
                            message=f"方案 {case_index + 1}/{len(prepared)} · {case_name}：{done}/{total} 日。",
                        )
                    )

            report = engine.run(cfg, slices, manifest, signals, strategy, progress)
            cases.append(
                {
                    "key": case.key,
                    "weight": str(case.weight),
                    "initial_cash": str(cfg.initial_cash),
                    "config": cfg.model_dump(mode="json"),
                    "plugins": versions,
                    "report": report,
                }
            )
        result = summarize(config, cases, manifest)
        if expected and result["result_hash"] != expected:
            raise ValueError("相同冻结输入的重放结果不一致，请检查策略确定性")
        with session() as db, db.begin():
            row = service._run_row(db, identifier)
            db.add(
                BacktestArtifact(
                    run_id=identifier,
                    key="report",
                    content_hash=fingerprint(result),
                    payload=result,
                )
            )
            row.status, row.finished_at = "success", now()
            row.details = {
                **row.details,
                "result_hash": result["result_hash"],
                "metrics": result["portfolio"]["metrics"] if result["portfolio"] else None,
            }
            db.add(
                RunEvent(
                    run_id=identifier, stage="complete", message="全部方案完成，完整报告已归档。"
                )
            )
        return service.get(identifier)
    except Exception as exc:
        if claimed:
            with session() as db, db.begin():
                row = db.get(Run, identifier)
                if row and row.status in {"queued", "running"}:
                    message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                    row.status, row.finished_at = "failed", now()
                    row.details = {**row.details, "error": message}
                    db.add(RunEvent(run_id=identifier, stage="failed", message=message))
        raise


def run(config: StudyConfig) -> dict:
    return execute(create(config))


def replay(identifier: str) -> dict:
    with session() as db:
        original = service._run_row(db, identifier)
        if original.kind != "backtest_study" or original.status != "success":
            raise ValueError("只能重放已成功的策略对比或资金组合")
        if original.details["engine_version"] != version():
            raise ValueError("回测内核版本已变化；重放需恢复原版本")
        config = StudyConfig.model_validate(original.details["study_config"])
        prepare(config, original.details["plugins"])
        slices = service._inputs(db, original)
        manifest, versions = original.details["manifest"], original.details["plugins"]
        expected = original.details["result_hash"]
    return execute(
        _save(config, slices, manifest, versions, replay_of=identifier, expected_hash=expected)
    )
