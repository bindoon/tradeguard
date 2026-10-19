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
for name, sub in [
    ("market", market),
    ("scan", scan_app),
    ("portfolio", portfolio),
    ("discipline", discipline),
    ("research", research),
    ("pipeline", pipeline),
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
    date: Annotated[str, typer.Option()],
    symbol: Annotated[list[str] | None, typer.Option()] = None,
    source: str = "legacy_mysql",
    refresh: bool = False,
    market: str = "CN",
):
    """Scan cache; --refresh --source baostock explicitly enables network synchronization."""
    from tradeguard.jobs import daily
    from tradeguard.market.schemas import normalize_symbol

    output(
        lambda: daily(
            day(date),
            [normalize_symbol(s) for s in symbol] if symbol else None,
            source,
            refresh,
            market.upper(),
        )
    )


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
