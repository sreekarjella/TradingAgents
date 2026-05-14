"""Pipeline & log viewer routes — FastAPI APIRouter.

Separated from app.py to keep file sizes manageable.
Imported and mounted in app.py via ``app.include_router(router)``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from dashboard.log_reader import available_tickers, get_run_detail, list_runs
from dashboard.pipeline_runner import (
    PipelineRunner,
    cleanup_old_logs,
    list_log_files,
    read_log_file,
)

# ---------------------------------------------------------------------------
# Router + shared state
# ---------------------------------------------------------------------------

router = APIRouter()
_runner = PipelineRunner()

# Resolved at import time — PROJECT_ROOT/logs
_BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = _BASE_DIR.parent / "logs"


class PipelineStartRequest(BaseModel):
    use_screener: bool = True
    num_candidates: int = 5
    dry_run: bool = False
    max_positions: int = 10
    tickers: list[str] | None = None


def _get_templates():
    """Lazy import to avoid circular dependency with app.py."""
    from dashboard.app import templates, _header_context
    return templates, _header_context


# ---------------------------------------------------------------------------
# Pipeline runner routes
# ---------------------------------------------------------------------------

@router.get("/pipeline", response_class=HTMLResponse)
async def page_pipeline(request: Request) -> HTMLResponse:
    """Pipeline runner page with config form + live log window."""
    templates, _header_context = _get_templates()
    return templates.TemplateResponse(request, "pipeline.html", {
        "page": "pipeline",
        "header": _header_context(),
        "status": _runner.get_status(),
    })


@router.post("/api/pipeline/start")
async def api_pipeline_start(body: PipelineStartRequest) -> JSONResponse:
    """Start the trading pipeline as a background subprocess."""
    ok = await _runner.start(body.model_dump())
    if ok:
        return JSONResponse({"success": True, "message": "Pipeline started"})
    return JSONResponse(
        {"success": False, "message": "Pipeline is already running"},
        status_code=409,
    )


@router.post("/api/pipeline/stop")
async def api_pipeline_stop() -> JSONResponse:
    """Stop the currently running pipeline."""
    ok = await _runner.stop()
    if ok:
        return JSONResponse({"success": True, "message": "Pipeline stopped"})
    return JSONResponse(
        {"success": False, "message": "No pipeline is running"},
        status_code=409,
    )


@router.get("/api/pipeline/status")
async def api_pipeline_status() -> JSONResponse:
    """Get current pipeline status."""
    return JSONResponse(_runner.get_status())


@router.get("/api/pipeline/stream")
async def api_pipeline_stream() -> StreamingResponse:
    """SSE endpoint for live pipeline log streaming."""
    return StreamingResponse(
        _runner.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Log viewer routes
# ---------------------------------------------------------------------------

@router.get("/logs", response_class=HTMLResponse)
async def page_logs(request: Request) -> HTMLResponse:
    """Log viewer page — past 7 days of pipeline logs."""
    cleaned = cleanup_old_logs(LOGS_DIR)
    log_files = list_log_files(LOGS_DIR)

    templates, _header_context = _get_templates()
    return templates.TemplateResponse(request, "logs.html", {
        "page": "logs",
        "header": _header_context(),
        "log_files": log_files,
        "cleaned_count": cleaned,
    })


@router.get("/api/logs/{filename}")
async def api_log_content(filename: str) -> JSONResponse:
    """Return the content of a specific log file."""
    content = read_log_file(LOGS_DIR, filename)
    if content is None:
        return JSONResponse(
            {"success": False, "message": "Log file not found"},
            status_code=404,
        )
    return JSONResponse({"success": True, "content": content, "filename": filename})


@router.post("/api/logs/cleanup")
async def api_logs_cleanup() -> JSONResponse:
    """Manually trigger cleanup of logs older than 7 days."""
    deleted = cleanup_old_logs(LOGS_DIR)
    return JSONResponse({
        "success": True,
        "message": f"Deleted {deleted} old log file(s)",
        "deleted": deleted,
    })


# ---------------------------------------------------------------------------
# Analysis viewer routes
# ---------------------------------------------------------------------------


@router.get("/analysis", response_class=HTMLResponse)
async def page_analysis(
    request: Request,
    from_date: str = "",
    to_date: str = "",
    ticker: str = "",
) -> HTMLResponse:
    """Pipeline analysis viewer — browse step-by-step reports by date/ticker."""
    from datetime import date as _date

    fd = _date.fromisoformat(from_date) if from_date else None
    td = _date.fromisoformat(to_date) if to_date else None
    tk = ticker if ticker else None

    runs = list_runs(from_date=fd, to_date=td, ticker=tk)
    tickers = available_tickers()

    # Auto-select the first run if available
    selected_detail = None
    if runs:
        selected_detail = get_run_detail(runs[0].run_id)

    templates, _header_context = _get_templates()
    return templates.TemplateResponse(request, "analysis.html", {
        "page": "analysis",
        "header": _header_context(),
        "runs": runs,
        "tickers": tickers,
        "selected_ticker": ticker,
        "from_date": from_date,
        "to_date": to_date,
        "detail": selected_detail,
    })


@router.get("/api/analysis/runs", response_class=HTMLResponse)
async def api_analysis_runs(
    request: Request,
    from_date: str = "",
    to_date: str = "",
    ticker: str = "",
) -> HTMLResponse:
    """HTMX partial — returns filtered run list cards."""
    from datetime import date as _date

    fd = _date.fromisoformat(from_date) if from_date else None
    td = _date.fromisoformat(to_date) if to_date else None
    tk = ticker if ticker else None

    runs = list_runs(from_date=fd, to_date=td, ticker=tk)
    templates, _ = _get_templates()
    return templates.TemplateResponse(request, "_analysis_run_list.html", {
        "runs": runs,
    })


@router.get("/api/analysis/detail/{run_id}", response_class=HTMLResponse)
async def api_analysis_detail(request: Request, run_id: str) -> HTMLResponse:
    """HTMX partial — returns tabbed detail view for a single run."""
    detail = get_run_detail(run_id)
    if not detail:
        return HTMLResponse(
            '<p class="p-8 text-gray-500 dark:text-dark-muted">'
            'Run not found.</p>'
        )
    templates, _ = _get_templates()
    return templates.TemplateResponse(request, "_analysis_detail.html", {
        "detail": detail,
    })
