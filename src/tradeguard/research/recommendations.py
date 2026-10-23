"""Frozen scan evidence for locally authored, auditable research shortlists."""

from datetime import date

from pydantic import Field, model_validator
from sqlalchemy import select

from tradeguard.db import session
from tradeguard.db.models import ResearchReport, Run, ScanResult, ScanSummary, Security, now
from tradeguard.portfolio.schemas import StrictModel
from tradeguard.report import _pick, daily_report
from tradeguard.screening.availability import bounded_day
from tradeguard.workspace.schemas import Scope

PACK = "recommendation_evidence_v1"
REPORT = "recommendation_v1"


class Pick(StrictModel):
    symbol: str
    thesis: str = Field(min_length=10, max_length=4000)
    evidence_ids: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    invalidation: str = Field(min_length=5, max_length=2000)
    next_step: str = Field(min_length=5, max_length=2000)


class Alternative(StrictModel):
    symbol: str
    reason: str = Field(min_length=5, max_length=2000)


class Submission(StrictModel):
    evidence_pack_id: str
    author: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=10, max_length=4000)
    methodology: str = Field(min_length=10, max_length=4000)
    picks: list[Pick] = Field(max_length=5)
    abstention_reason: str | None = None
    alternatives: list[Alternative] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_picks(self):
        symbols = [p.symbol for p in self.picks]
        if len(symbols) != len(set(symbols)):
            raise ValueError("入选股票不能重复")
        if len(self.picks) < 5 and not (self.abstention_reason or "").strip():
            raise ValueError("不足五只时必须解释为何不凑数")
        if any(not r.strip() for p in self.picks for r in p.risks):
            raise ValueError("风险不能为空")
        return self


def prepare(scope: Scope, target: date) -> dict:
    bounded_day(target)
    # An explicit day is mandatory: no fallback to another day, source or adjustment.
    report = daily_report(target, scope.market, scope.source, scope.adjustment)
    with session() as db, db.begin():
        summary = db.scalar(select(ScanSummary).where(ScanSummary.run_id == report["run_id"]))
        run = db.get(Run, report["run_id"])
        if (
            not summary
            or not run
            or run.status not in {"success", "partial"}
            or run.market != scope.market
            or run.market_date != target
            or run.details.get("source") != scope.source
            or run.details.get("adjustment", "forward") != scope.adjustment
        ):
            raise ValueError("仅可读取已完成的扫描")
        rows = db.scalars(
            select(ScanResult)
            .join(Security, Security.symbol == ScanResult.symbol)
            .where(ScanResult.run_id == run.id, Security.market == scope.market)
        ).all()
        candidates = []
        for row in sorted(rows, key=lambda r: (-(r.resonance_count or len(r.hits)), r.symbol)):
            if not row.hits or row.trade_date != target:
                continue
            candidate = _pick(row)
            candidate["evidence_id"] = f"scan:{run.id}:{row.symbol}"
            candidate["strategy_details"] = (row.metadata_snapshot or {}).get(
                "strategy_details", []
            )
            candidates.append(candidate)
        payload = {
            "type": PACK,
            "scope": scope.model_dump(),
            "trade_date": str(target),
            "prepared_at": now().isoformat(),
            "scan_run_id": run.id,
            "scan_parameters": run.details,
            "market_regime": summary.market_regime,
            "benchmark": summary.benchmark,
            "counts": report["counts"],
            "scan_status": summary.status,
            "candidates": candidates,
            "changes": report["changes_vs_previous_day"],
            "limitations": [
                "技术扫描研究候选，不是完整基本面、估值或新闻研究",
                "共振优先排序只是研究起点，不代表胜率或收益预测",
                "未核验公告、财报、停复牌和当日开盘状态",
                "未结合新鲜账户、明确个人规则和拟交易数量，买入资格为 needs_input",
            ]
            + (["扫描部分完成，候选不代表完整市场排名"] if summary.status != "success" else []),
        }
        saved = ResearchReport(payload=payload)
        db.add(saved)
        db.flush()
        return {"evidence_pack_id": saved.id, **payload}


def submit(submission: Submission) -> dict:
    with session() as db, db.begin():
        row = db.get(ResearchReport, submission.evidence_pack_id)
        if not row or row.payload.get("type") != PACK:
            raise ValueError("证据包不存在")
        pack = row.payload
        candidates = {p["symbol"]: p for p in pack["candidates"]}
        picks = []
        for rank, pick in enumerate(submission.picks, 1):
            candidate = candidates.get(pick.symbol)
            if not candidate or set(pick.evidence_ids) != {candidate["evidence_id"]}:
                raise ValueError("每只入选股票必须引用本证据包内自身的扫描证据")
            picks.append({"rank": rank, **pick.model_dump(), "evidence": candidate})
        for alternative in submission.alternatives:
            if alternative.symbol not in candidates or alternative.symbol in {
                p.symbol for p in submission.picks
            }:
                raise ValueError("备选必须来自同一候选池并提供未入选原因")
        payload = {
            "type": REPORT,
            "scope": pack["scope"],
            "trade_date": pack["trade_date"],
            "scan_run_id": pack["scan_run_id"],
            "evidence_pack_id": row.id,
            "author": submission.author,
            "summary": submission.summary,
            "methodology": submission.methodology,
            "picks": picks,
            "abstention_reason": submission.abstention_reason,
            "alternatives": [a.model_dump() for a in submission.alternatives],
            "market_regime": pack["market_regime"],
            "scan_status": pack["scan_status"],
            "counts": pack["counts"],
            "limitations": pack["limitations"],
            "execution_eligibility": "needs_input",
            "created_at": now().isoformat(),
            "validation": "symbol_and_evidence_links_only",
        }
        saved = ResearchReport(payload=payload)
        db.add(saved)
        db.flush()
        return {"report_id": saved.id, **payload}


def latest(scope: Scope, target: date | None = None) -> dict | None:
    target = bounded_day(target)
    with session() as db:
        row = db.scalar(
            select(ResearchReport)
            .where(
                ResearchReport.payload["type"].as_string() == REPORT,
                ResearchReport.payload["scope"]["market"].as_string() == scope.market,
                ResearchReport.payload["scope"]["source"].as_string() == scope.source,
                ResearchReport.payload["scope"]["adjustment"].as_string() == scope.adjustment,
                ResearchReport.payload["trade_date"].as_string() <= str(target),
            )
            .order_by(
                ResearchReport.payload["trade_date"].as_string().desc(),
                ResearchReport.created_at.desc(),
                ResearchReport.id.desc(),
            )
            .limit(1)
        )
        return {"report_id": row.id, **row.payload} if row else None
