from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from tradeguard.backtesting import plugins, service, studies
from tradeguard.backtesting.schemas import BacktestConfig

router = APIRouter(prefix="/api/backtests", tags=["backtests"])
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tradeguard-backtest")
slots = BoundedSemaphore(2)


class EnableInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.get("/plugins")
def plugin_list():
    return plugins.catalog()


@router.patch("/plugins/{name}")
def plugin_enable(name: str, payload: EnableInput):
    return plugins.set_enabled(name, payload.enabled)


@router.post("/preflight")
def preflight(payload: BacktestConfig):
    return service.preflight(payload)


def worker(identifier, study=False):
    try:
        (studies.execute if study else service.execute)(identifier)
    except Exception:
        # The service durably records a sanitized error. Never echo provider/DB secrets.
        pass
    finally:
        slots.release()


@router.post("", status_code=202)
def launch(payload: BacktestConfig):
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "已有回测运行或排队，请稍后重试")
    try:
        identifier = service.create(payload)
        executor.submit(worker, identifier)
    except Exception:
        slots.release()
        raise
    return {"id": identifier, "status": "queued"}


@router.get("")
def history(market: str, adjustment: str, source: str = ""):
    if market not in {"CN", "US", "HK"} or adjustment not in {"none", "forward", "backward"}:
        raise HTTPException(422, "请选择有效市场及复权")
    return service.history(market, source, adjustment)


@router.post("/studies/preflight")
def study_preflight(payload: studies.StudyConfig):
    return studies.preflight(payload)


@router.post("/studies", status_code=202)
def study_launch(payload: studies.StudyConfig):
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "已有回测运行或排队，请稍后重试")
    try:
        identifier = studies.create(payload)
        executor.submit(worker, identifier, True)
    except Exception:
        slots.release()
        raise
    return {"id": identifier, "status": "queued"}


@router.get("/{identifier}")
def report(identifier: str, market: str, adjustment: str, source: str = ""):
    try:
        return service.get(identifier, market, source, adjustment)
    except ValueError as exc:
        if "没有这个回测" in str(exc):
            raise HTTPException(404, str(exc)) from None
        raise
