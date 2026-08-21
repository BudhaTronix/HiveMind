"""Versioned HTTP and WebSocket routes for the browser dashboard."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status

from hivemind.web.models import NewRunRequest, PublicSettings, ScheduledRun
from hivemind.web.snapshot import build_agent_details, build_snapshot

router = APIRouter(prefix="/api/v1")


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    await request.app.state.repository.initialize()
    return {"status": "ok", "service": "hivemind-web"}


@router.get("/public-settings", response_model=PublicSettings)
async def public_settings(request: Request) -> PublicSettings:
    settings = request.app.state.settings
    return PublicSettings(
        default_provider=settings.provider,
        default_model=settings.model_for("worker"),
        enable_web=settings.enable_web,
        limits={
            "max_managers": settings.max_managers,
            "max_workers_per_manager": settings.max_workers_per_manager,
            "max_research_rounds": settings.max_research_rounds,
            "max_concurrent_llm_calls": settings.max_concurrent_llm_calls,
        },
    )


@router.get("/runs")
async def list_runs(request: Request, limit: int = 50) -> list[dict]:
    safe_limit = min(max(limit, 1), 200)
    runs = await request.app.state.repository.list_runs(safe_limit)
    return [item.model_dump(mode="json") for item in runs]


@router.post("/runs", response_model=ScheduledRun, status_code=status.HTTP_202_ACCEPTED)
async def create_run(payload: NewRunRequest, request: Request) -> ScheduledRun:
    run = await request.app.state.supervisor.schedule(payload)
    return ScheduledRun(run_id=run.run_id)


@router.get("/runs/{run_id}/snapshot")
async def snapshot(run_id: str, request: Request) -> dict:
    result = await build_snapshot(request.app.state.repository, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return result.model_dump(mode="json")


@router.get("/runs/{run_id}/agents/{agent_id}")
async def agent_details(run_id: str, agent_id: str, request: Request) -> dict:
    result = await build_agent_details(request.app.state.repository, run_id, agent_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Agent did not participate in this run.")
    return result.model_dump(mode="json")


@router.post("/runs/{run_id}/resume", response_model=ScheduledRun, status_code=202)
async def resume_run(run_id: str, request: Request) -> ScheduledRun:
    try:
        run = await request.app.state.supervisor.resume(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ScheduledRun(run_id=run.run_id)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request) -> dict:
    try:
        run = await request.app.state.supervisor.cancel(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run.model_dump(mode="json")


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, request: Request) -> dict[str, object]:
    try:
        await request.app.state.supervisor.delete(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": run_id, "deleted": True}


@router.websocket("/runs/{run_id}/stream")
async def stream(run_id: str, websocket: WebSocket) -> None:
    repository = websocket.app.state.repository
    if await repository.get_run(run_id) is None:
        await websocket.close(code=4404, reason="Run not found")
        return
    broker = websocket.app.state.broker
    subscription = broker.subscribe(run_id)
    await websocket.accept()
    seen_events: set[str] = set()
    seen_handoffs: set[str] = set()
    try:
        current = await build_snapshot(repository, run_id)
        assert current is not None
        seen_events.update(item.event_id for item in current.events)
        seen_handoffs.update(item.handoff_id for item in current.handoffs)
        await websocket.send_json(
            {"type": "snapshot", "data": current.model_dump(mode="json")}
        )
        while True:
            envelope = await subscription.queue.get()
            if _is_duplicate(envelope, seen_events, seen_handoffs):
                continue
            await websocket.send_json(envelope)
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        broker.unsubscribe(subscription)


def _is_duplicate(
    envelope: dict, seen_events: set[str], seen_handoffs: set[str]
) -> bool:
    data = envelope.get("data", {})
    if envelope.get("type") == "event":
        identifier = data.get("event_id")
        if identifier in seen_events:
            return True
        if identifier:
            seen_events.add(identifier)
    elif envelope.get("type") == "handoff":
        identifier = data.get("handoff_id")
        if identifier in seen_handoffs:
            return True
        if identifier:
            seen_handoffs.add(identifier)
    return False
