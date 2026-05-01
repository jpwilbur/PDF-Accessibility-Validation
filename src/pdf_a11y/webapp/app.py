"""FastAPI app: home page (start a run), history list, run detail."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pdf_a11y import __version__, paths
from pdf_a11y.runs import (
    RunStore,
    load_settings,
    save_settings,
)
from pdf_a11y.webapp.runner import ProgressBus, RunRunner

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    paths.ensure_dirs()
    store = RunStore()
    bus = ProgressBus()
    runner = RunRunner(store=store, bus=bus)
    templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

    app = FastAPI(
        title="ObservePoint PDF Validation",
        description="Local PDF accessibility evaluator",
        version=__version__,
    )
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ---- pages -------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        settings = load_settings()
        deps = _system_deps_status()
        recent = store.list(limit=10)
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "settings": settings,
                "deps": deps,
                "recent_runs": recent,
                "app_version": __version__,
                "data_dir": str(paths.app_data_dir()),
            },
        )

    @app.get("/runs", response_class=HTMLResponse)
    async def runs_list(request: Request) -> HTMLResponse:
        runs = store.list(limit=500)
        return templates.TemplateResponse(
            request,
            "runs.html",
            {
                "runs": runs,
                "app_version": __version__,
            },
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str) -> HTMLResponse:
        rec = store.get(run_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        summary_exists = (rec.output_path / "summary.html").exists()
        return templates.TemplateResponse(
            request,
            "run_detail.html",
            {
                "run": rec,
                "summary_exists": summary_exists,
                "app_version": __version__,
            },
        )

    # ---- API ---------------------------------------------------------

    @app.post("/api/runs")
    async def api_start_run(
        source: str = Form(...),
        op_api_key: str | None = Form(None),
        op_report_id: str | None = Form(None),
        urls: str | None = Form(None),
        concurrency: int | None = Form(None),
        save_settings_flag: bool = Form(False),
    ) -> JSONResponse:
        if source == "observepoint":
            if not op_api_key or not op_report_id:
                raise HTTPException(
                    status_code=400,
                    detail="API key and report ID are required for ObservePoint runs.",
                )
            if save_settings_flag:
                _persist_settings(
                    op_api_key=op_api_key,
                    last_op_report_id=op_report_id,
                    last_concurrency=concurrency or 3,
                )
            rec = await runner.start_observepoint(
                api_key=op_api_key,
                report_id=op_report_id,
                concurrency=concurrency,
            )
            return JSONResponse({"run_id": rec.id, "redirect": f"/runs/{rec.id}"})
        if source == "manual":
            if not urls:
                raise HTTPException(status_code=400, detail="Provide at least one URL or path.")
            url_list = [u.strip() for u in urls.splitlines() if u.strip()]
            if not url_list:
                raise HTTPException(status_code=400, detail="No URLs provided.")
            rec = runner.start_manual(urls=url_list, concurrency=concurrency)
            return JSONResponse({"run_id": rec.id, "redirect": f"/runs/{rec.id}"})
        raise HTTPException(status_code=400, detail=f"Unknown source: {source}")

    @app.post("/api/runs/{run_id}/delete")
    async def api_delete_run(run_id: str) -> RedirectResponse:
        rec = store.get(run_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        # Best-effort: remove the run's output directory so disk doesn't fill up.
        try:
            if rec.output_path.exists():
                shutil.rmtree(rec.output_path)
        except OSError:
            pass
        store.delete(run_id)
        return RedirectResponse(url="/runs", status_code=303)

    @app.get("/api/runs/{run_id}/events")
    async def api_run_events(run_id: str) -> StreamingResponse:
        rec = store.get(run_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return StreamingResponse(
            _sse_stream(bus, run_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/health")
    async def api_health() -> dict[str, Any]:
        return {
            "version": __version__,
            "data_dir": str(paths.app_data_dir()),
            "deps": _system_deps_status(),
        }

    # ---- run-specific report file serving ----------------------------

    @app.get("/runs/{run_id}/report/{file_path:path}")
    async def run_report_file(run_id: str, file_path: str) -> Any:
        rec = store.get(run_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        # Prevent path traversal.
        target = (rec.output_path / file_path).resolve()
        if not str(target).startswith(str(rec.output_path.resolve())):
            raise HTTPException(status_code=400, detail="Invalid path")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        from fastapi.responses import FileResponse

        return FileResponse(target)

    return app


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _persist_settings(**kwargs: Any) -> None:
    s = load_settings()
    for k, v in kwargs.items():
        if v is not None and hasattr(s, k):
            setattr(s, k, v)
    save_settings(s)


def _system_deps_status() -> dict[str, Any]:
    """For the home-page badge: are veraPDF / Java / Tesseract available?"""

    def _bin(name: str) -> dict[str, Any]:
        path = shutil.which(name)
        return {"name": name, "ok": path is not None, "path": path}

    return {
        "platform": sys.platform,
        "verapdf": _bin("verapdf"),
        "tesseract": _bin("tesseract"),
        "java": _bin("java"),
    }


async def _sse_stream(bus: ProgressBus, run_id: str) -> AsyncIterator[bytes]:
    """Yield SSE frames as the run emits ProgressEvents.

    Pulls from a per-subscriber queue so multiple browser tabs can watch
    the same run simultaneously. Polls the queue with a short timeout so
    we don't block the event loop.
    """
    import asyncio

    q, last_event, finished = bus.subscribe(run_id)
    try:
        if last_event is not None:
            yield _sse_frame(last_event)
        if finished and last_event and last_event.get("phase") in ("done", "failed"):
            return
        while True:
            try:
                event = await asyncio.to_thread(q.get, True, 1.0)
            except Exception:
                # heartbeat
                yield b": keepalive\n\n"
                continue
            if event is None:
                break
            if event.get("_eos"):
                yield _sse_frame(event)
                break
            yield _sse_frame(event)
    finally:
        bus.unsubscribe(run_id, q)


def _sse_frame(event: dict[str, Any]) -> bytes:
    payload = json.dumps(event, default=str)
    return f"data: {payload}\n\n".encode()
