import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from tradeguard import __version__
from tradeguard.db import engine
from tradeguard.db.models import now

app = typer.Typer(no_args_is_help=True, help="Local stock research and discipline tools.")
market = typer.Typer(no_args_is_help=True)
scan_app = typer.Typer(no_args_is_help=True)
portfolio = typer.Typer(no_args_is_help=True)
discipline = typer.Typer(no_args_is_help=True)
research = typer.Typer(no_args_is_help=True)
pipeline = typer.Typer(no_args_is_help=True)
report = typer.Typer(no_args_is_help=True)
workspace_app = typer.Typer(no_args_is_help=True)
public_app = typer.Typer(no_args_is_help=True)
for name, sub in [
    ("market", market),
    ("scan", scan_app),
    ("portfolio", portfolio),
    ("discipline", discipline),
    ("research", research),
    ("pipeline", pipeline),
    ("report", report),
    ("workspace", workspace_app),
    ("public", public_app),
]:
    app.add_typer(sub, name=name)


def output(call: Callable[[], dict]) -> None:
    try:
        data = call()
        status = data.get("status", "success")
        if status not in {"success", "partial", "failed", "needs_input", "blocked"}:
            status = "success"
        if data.get("decision") == "needs_input":
            status = "needs_input"
        elif data.get("decision") == "blocked":
            status = "blocked"
        payload = {"schema_version": 1, "status": status, "as_of": now().isoformat(), "data": data}
        code = {"partial": 2, "needs_input": 3, "blocked": 4}.get(status, 0)
    except ValidationError as exc:
        payload = {
            "schema_version": 1,
            "status": "failed",
            "error": "invalid_input",
            "details": exc.errors(include_input=False, include_context=False),
        }
        code = 1
    except (ValueError, FileNotFoundError) as exc:
        payload = {"schema_version": 1, "status": "failed", "error": str(exc)}
        code = 1
    except SQLAlchemyError:
        payload = {
            "schema_version": 1,
            "status": "failed",
            "error": "Database operation failed; check connection and migrations",
        }
        code = 1
    except RuntimeError as exc:
        payload = {"schema_version": 1, "status": "failed", "error": str(exc)}
        code = 1
    typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
    if code:
        raise typer.Exit(code)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def day(value: str) -> date:
    return date.fromisoformat(value)


@app.command()
def doctor():
    """Check DB connectivity and migration revision without printing credentials."""

    def check():
        with engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        return {"version": __version__, "database": "connected", "migration": revision}

    output(check)


@market.command("import")
def market_import(file: Annotated[Path, typer.Option(exists=True, dir_okay=False)]):
    """Import validated CSV bars atomically. Volume unit is shares."""
    from tradeguard.market.service import import_csv

    output(lambda: import_csv(file))


@market.command("quality")
def market_quality(
    date: Annotated[str, typer.Option()],
    source: Annotated[str, typer.Option()],
    adjustment: str = "forward",
    market: str = "CN",
):
    from tradeguard.market.service import quality

    output(lambda: quality(day(date), source, adjustment, market.upper()))


@market.command("import-legacy")
def market_import_legacy(
    resume_run: str | None = None, since: str | None = None, max_rows: int | None = None
):
    """Read-only MySQL cache -> local PostgreSQL, bounded memory and resumable checkpoints."""
    from tradeguard.market.legacy import import_mysql

    output(lambda: import_mysql(resume_run, day(since) if since else None, max_rows))


@market.command("sync")
def market_sync(
    date: Annotated[str, typer.Option()],
    start: str | None = None,
    symbol: Annotated[list[str] | None, typer.Option()] = None,
    market: str = "CN",
    source: str | None = None,
):
    """Explicit market synchronization. US/HK use Longbridge; CN defaults to baostock."""

    def invoke():
        selected = market.upper()
        provider = source or ("baostock" if selected == "CN" else "longbridge")
        first = day(start) if start else day(date) - timedelta(days=550)
        if provider == "baostock" and selected == "CN":
            from tradeguard.market.baostock import sync

            return sync(day(date), first, symbol)
        if provider == "longbridge":
            from tradeguard.market.longbridge import sync as longbridge_sync

            return longbridge_sync(day(date), first, symbol, selected)
        raise ValueError("Select a supported market/provider combination")

    output(invoke)


@market.command("stats")
def market_stats(
    source: Annotated[str, typer.Option()], adjustment: str = "forward", market: str = "CN"
):
    """Inspect cached coverage without fetching any remote market data."""
    from tradeguard.market.service import stats

    output(lambda: stats(source, adjustment, market.upper()))


@scan_app.command("run")
def scan_run(
    date: Annotated[str, typer.Option()],
    source: Annotated[str, typer.Option()],
    adjustment: str = "forward",
    min_resonance: int = 1,
    symbol: Annotated[list[str] | None, typer.Option()] = None,
    market: str = "CN",
):
    from tradeguard.market.schemas import normalize_symbol
    from tradeguard.screening.service import scan

    output(
        lambda: scan(
            day(date),
            source,
            adjustment,
            [normalize_symbol(s) for s in symbol] if symbol else None,
            min_resonance,
            market=market.upper(),
        )
    )


@scan_app.command("results")
def scan_results(run_id: str):
    from tradeguard.screening.service import results

    output(lambda: results(run_id))


@portfolio.command("import")
def portfolio_import(file: Annotated[Path, typer.Option(exists=True, dir_okay=False)]):
    """Import one complete manual account snapshot; never claims broker verification."""
    from tradeguard.portfolio.schemas import SnapshotInput
    from tradeguard.portfolio.service import save_snapshot

    output(lambda: save_snapshot(SnapshotInput.model_validate(load(file))))


@portfolio.command("report")
def portfolio_report(account: Annotated[str, typer.Option()]):
    from tradeguard.portfolio.service import report

    output(lambda: report(account))


@portfolio.command("import-existing")
def portfolio_existing():
    """Read genuine cached portfolio records from the configured source; preserve timestamps."""
    from tradeguard.portfolio.legacy import import_portfolio

    output(import_portfolio)


@portfolio.command("account-add")
def account_add(
    account: Annotated[str, typer.Option()],
    broker: Annotated[str, typer.Option()],
    label: Annotated[str, typer.Option()],
):
    from tradeguard.portfolio.service import create_account

    output(lambda: create_account(account, broker, label))


@portfolio.command("update")
def portfolio_update(
    account: Annotated[str, typer.Option()],
    file: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
):
    """Apply user-reported facts to a new immutable snapshot; no broker order is submitted."""
    from tradeguard.portfolio.schemas import ManualPatch
    from tradeguard.portfolio.service import manual_update

    output(lambda: manual_update(account, ManualPatch.model_validate(load(file))))


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8188):
    """Serve the local console and compiled selection-derived web interface."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise typer.BadParameter("The account console must bind to loopback")
    import uvicorn

    uvicorn.run("tradeguard.console:create_app", factory=True, host=host, port=port)


@portfolio.command("sync")
def portfolio_sync(
    account: Annotated[str, typer.Option()],
    base_currency: Annotated[str, typer.Option()],
    broker: str = "longbridge",
):
    """Read-only account sync through Longbridge or Futu. No order mutation."""

    def invoke():
        if broker == "longbridge":
            from tradeguard.portfolio.longbridge import sync
        elif broker == "futu":
            from tradeguard.portfolio.futu import sync
        else:
            raise ValueError("broker must be longbridge or futu")
        return sync(account, base_currency.upper())

    output(invoke)


@discipline.command("rules-import")
def rules_import(file: Annotated[Path, typer.Option(exists=True, dir_okay=False)]):
    """Create an immutable personal rule-profile version. No implicit default rules."""
    from tradeguard.discipline.schemas import Rules
    from tradeguard.discipline.service import save_rules

    output(lambda: save_rules(Rules.model_validate(load(file))))


@discipline.command("check")
def discipline_check(
    file: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    profile: Annotated[str, typer.Option()],
):
    from tradeguard.discipline.schemas import Intent
    from tradeguard.discipline.service import check

    output(lambda: check(Intent.model_validate(load(file)), profile))


@research.command("save")
def research_save(file: Annotated[Path, typer.Option(exists=True, dir_okay=False)]):
    from tradeguard.research.service import Report, save_report

    output(lambda: save_report(Report.model_validate(load(file))))


@pipeline.command("daily")
def pipeline_daily(
    market: str = "CN",
    date: Annotated[
        str | None, typer.Option(help="Single trading day. Omit to continue from the last bar.")
    ] = None,
    symbol: Annotated[list[str] | None, typer.Option()] = None,
    source: str | None = None,
    refresh: bool = False,
    start: Annotated[str | None, typer.Option("--from")] = None,
    end: Annotated[str | None, typer.Option("--to")] = None,
):
    """CN backfill uses akshare, then baostock if akshare is down. Explicit cache sources stay offline."""

    def invoke():
        from tradeguard.market.schemas import normalize_symbol

        selected = market.upper()
        target = day(date) if date else None
        first = day(start) if start else None
        last = day(end) if end else None
        if target and (first or last):
            raise ValueError("--date cannot be combined with --from/--to")
        if (first is None) ^ (last is None):
            raise ValueError("--from and --to must be used together")
        symbols = [normalize_symbol(item) for item in symbol] if symbol else None
        if selected == "CN" and source in {None, "akshare"}:
            from tradeguard.jobs import run_cn_pipeline

            return run_cn_pipeline(target=target, start=first, end=last, symbols=symbols)
        if selected == "CN" and source == "baostock" and refresh:
            from tradeguard.jobs import run_cn_pipeline
            from tradeguard.market.providers import BaostockProvider

            return run_cn_pipeline(
                target=target,
                start=first,
                end=last,
                symbols=symbols,
                primary=BaostockProvider(),
                allow_fallback=False,
            )
        if source is None:
            raise ValueError("US/HK daily runs require an explicit source")
        from tradeguard.jobs import daily

        if first and last:
            return daily(last, symbols, source, refresh, selected, start=first, end=last)
        return daily(target, symbols, source, refresh, selected)

    output(invoke)


@report.command("daily")
def report_daily(
    date: Annotated[str, typer.Option()],
    market: str = "CN",
    source: str | None = None,
):
    """JSON daily scan report: regime, strategy counts, resonance, sectors, day-over-day changes."""
    from tradeguard.report import daily_report

    output(lambda: daily_report(day(date), market.upper(), source))


@app.command("example-snapshot")
def example_snapshot():
    """Print a synthetic, current, empty-account snapshot for local acceptance only."""
    output(
        lambda: {
            "synthetic": True,
            "snapshot": {
                "account_id": "demo",
                "broker": "manual",
                "label": "Synthetic demo",
                "external_id": datetime.now().isoformat(),
                "as_of": now().isoformat(),
                "base_currency": "CNY",
                "net_assets": "100000",
                "cash": "100000",
                "margin_used": False,
                "monthly_drawdown": "0",
                "positions": [],
                "orders": [],
            },
        }
    )


@workspace_app.command("report")
def workspace_report(
    source: Annotated[str, typer.Option()], market: str = "CN", adjustment: str = "forward"
):
    """Private evidence bundle for an agent: candidates, position review and explicit rule checks."""
    from tradeguard.workspace.schemas import Scope
    from tradeguard.workspace.service import overview

    output(
        lambda: overview(
            Scope.model_validate(
                {"market": market.upper(), "source": source, "adjustment": adjustment}
            )
        )
    )


@workspace_app.command("refresh")
def workspace_refresh(
    source: Annotated[str, typer.Option()], market: str = "CN", adjustment: str = "forward"
):
    """Evaluate local cached observations and save deduplicated reminders. No network access."""
    from tradeguard.workspace.schemas import Scope
    from tradeguard.workspace.service import refresh

    output(
        lambda: refresh(
            Scope.model_validate(
                {"market": market.upper(), "source": source, "adjustment": adjustment}
            )
        )
    )


@workspace_app.command("watch")
def workspace_watch(file: Annotated[Path, typer.Option(exists=True, dir_okay=False)]):
    from tradeguard.workspace.schemas import WatchInput
    from tradeguard.workspace.service import add_watch

    output(lambda: add_watch(WatchInput.model_validate(load(file))))


@workspace_app.command("alert")
def workspace_alert(file: Annotated[Path, typer.Option(exists=True, dir_okay=False)]):
    from tradeguard.workspace.schemas import AlertInput
    from tradeguard.workspace.service import add_alert

    output(lambda: add_alert(AlertInput.model_validate(load(file))))


@public_app.command("export")
def public_export(
    date: Annotated[str, typer.Option()],
    source: Annotated[str, typer.Option()],
    symbol: Annotated[list[str], typer.Option()],
    output_dir: Annotated[Path, typer.Option("--output")],
    market: str = "CN",
    adjustment: str = "forward",
):
    """Build a standalone public market-only site in a fresh directory; never upload anything."""
    from tradeguard.public_site.export import export_site
    from tradeguard.workspace.schemas import Scope

    output(
        lambda: export_site(
            Scope.model_validate(
                {"market": market.upper(), "source": source, "adjustment": adjustment}
            ),
            day(date),
            symbol,
            output_dir,
        )
    )


@research.command("prepare")
def research_prepare(
    date: Annotated[str, typer.Option()],
    source: Annotated[str, typer.Option()],
    market: str = "CN",
    adjustment: str = "forward",
):
    """Freeze all scan candidates and their evidence for a local agent to rank."""
    from tradeguard.research.recommendations import prepare
    from tradeguard.workspace.schemas import Scope

    output(
        lambda: prepare(
            Scope.model_validate({"market": market, "source": source, "adjustment": adjustment}),
            day(date),
        )
    )


@research.command("shortlist-save")
def research_shortlist_save(file: Annotated[Path, typer.Option(exists=True, dir_okay=False)]):
    """Validate and save an agent-authored shortlist against its frozen evidence pack."""
    from tradeguard.research.recommendations import Submission, submit

    output(lambda: submit(Submission.model_validate(load(file))))


@research.command("shortlist")
def research_shortlist(
    source: Annotated[str, typer.Option()],
    market: str = "CN",
    adjustment: str = "forward",
    date: str | None = None,
):
    """Read the most recent saved shortlist at or before the requested day."""
    from tradeguard.research.recommendations import latest
    from tradeguard.workspace.schemas import Scope

    output(
        lambda: {
            "recommendation": latest(
                Scope.model_validate(
                    {"market": market, "source": source, "adjustment": adjustment}
                ),
                day(date) if date else None,
            )
        }
    )


@research.command("shortlist-schema")
def research_shortlist_schema():
    """Return the agent submission contract without reading private data."""
    from tradeguard.research.recommendations import Submission

    output(Submission.model_json_schema)
