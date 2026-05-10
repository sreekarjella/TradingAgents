"""Pipeline runner — subprocess management + SSE streaming + log file management.

Handles running the daily trading pipeline as a background subprocess,
streaming its output via Server-Sent Events, and managing log files
with 7-day retention.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
_MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _MODULE_DIR.parent
LOGS_DIR = PROJECT_ROOT / "logs"

# Regex for log lines like  "10:23:45 [INFO] message"  or
#                           "10:23:45 [ERROR] name — message"
_LOG_LEVEL_RE = re.compile(r"\[(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\]")

# Valid pipeline status literals
_STATUS_IDLE = "idle"
_STATUS_RUNNING = "running"
_STATUS_COMPLETE = "complete"
_STATUS_ERROR = "error"

# Sentinel pushed to the queue when the pipeline finishes
_SENTINEL = None


# ---------------------------------------------------------------------------
# Type alias for a single structured log line
# ---------------------------------------------------------------------------
LogLine = dict[str, str]  # keys: timestamp, level, message


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_log_level(raw_line: str) -> str:
    """Extract the log level from a raw pipeline output line.

    Falls back to ``"INFO"`` when no ``[LEVEL]`` marker is found.
    """
    match = _LOG_LEVEL_RE.search(raw_line)
    return match.group("level") if match else "INFO"


def _make_log_entry(raw_line: str) -> LogLine:
    """Turn a raw text line into a structured ``LogLine`` dict."""
    return {
        "timestamp": _now_iso(),
        "level": _parse_log_level(raw_line),
        "message": raw_line,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PipelineRunner
# ═══════════════════════════════════════════════════════════════════════════

class PipelineRunner:
    """Singleton-ish manager for the daily trading pipeline subprocess.

    One instance should be created per FastAPI app and shared across routes.

    Usage::

        runner = PipelineRunner()

        # In a POST handler:
        ok = await runner.start({"dry_run": True, "num_candidates": 5, ...})

        # In an SSE endpoint:
        async for event in runner.stream():
            yield event

        # Status polling:
        info = runner.get_status()
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._status: str = _STATUS_IDLE
        self._current_process: asyncio.subprocess.Process | None = None
        self._log_lines: list[LogLine] = []
        self._start_time: datetime | None = None
        self._end_time: datetime | None = None
        self._config: dict[str, Any] = {}

        # Every call to `stream()` gets its own Queue; this set tracks them
        # so `_read_output` can fan-out each line to all subscribers.
        self._subscribers: set[asyncio.Queue[LogLine | None]] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self, config: dict[str, Any]) -> bool:
        """Launch the pipeline as a subprocess.

        Parameters
        ----------
        config:
            ``use_screener`` (bool), ``num_candidates`` (int),
            ``dry_run`` (bool), ``max_positions`` (int),
            ``tickers`` (optional list[str]).

        Returns ``False`` if a pipeline is already running.
        """
        async with self._lock:
            if self._status == _STATUS_RUNNING:
                logger.warning("Pipeline already running — ignoring start request.")
                return False

            self._reset_state(config)

        cmd = self._build_command(config)
        log_file_path = self._create_log_file()

        logger.info("Starting pipeline: %s", " ".join(cmd))
        logger.info("Log file: %s", log_file_path)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
                cwd=str(PROJECT_ROOT),
                env=os.environ.copy(),
            )
        except Exception:
            logger.exception("Failed to spawn pipeline subprocess.")
            async with self._lock:
                self._status = _STATUS_ERROR
                self._end_time = datetime.now(timezone.utc)
                entry = _make_log_entry("[RUNNER] Failed to start subprocess.")
                entry["level"] = "ERROR"
                self._log_lines.append(entry)
                self._broadcast(entry)
                self._broadcast_sentinel()
            return False

        async with self._lock:
            self._current_process = process

        # Fire-and-forget the reader task — it will update status on exit.
        asyncio.create_task(
            self._read_output(process, log_file_path),
            name="pipeline-reader",
        )
        return True

    async def stop(self) -> bool:
        """Gracefully terminate (SIGTERM) then force-kill the running pipeline.

        Returns ``False`` if nothing is running.
        """
        async with self._lock:
            proc = self._current_process
            if proc is None or self._status != _STATUS_RUNNING:
                return False

        logger.info("Stopping pipeline (pid=%s) …", proc.pid)

        try:
            proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass  # already dead

        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Pipeline did not exit after SIGTERM — sending SIGKILL.")
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()

        async with self._lock:
            self._status = _STATUS_ERROR
            self._end_time = datetime.now(timezone.utc)
            entry = _make_log_entry("[RUNNER] Stopped by user")
            entry["level"] = "WARNING"
            self._log_lines.append(entry)
            self._broadcast(entry)
            self._broadcast_sentinel()
            self._current_process = None

        return True

    async def stream(self) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted events for the pipeline log stream.

        Late joiners receive all historical lines first, then live lines
        until the pipeline finishes (or is stopped).
        """
        queue: asyncio.Queue[LogLine | None] = asyncio.Queue()

        # Snapshot existing lines + register under the lock so we don't
        # miss anything between the snapshot and the subscription.
        async with self._lock:
            history = list(self._log_lines)
            self._subscribers.add(queue)
            finished = self._status not in (_STATUS_RUNNING, _STATUS_IDLE)

        try:
            # Replay history
            for line in history:
                yield _sse_data(line)

            if finished:
                yield _sse_done(self._status)
                return

            # Live tail
            while True:
                line = await queue.get()
                if line is _SENTINEL:
                    yield _sse_done(self._status)
                    return
                yield _sse_data(line)

        finally:
            async with self._lock:
                self._subscribers.discard(queue)

    def get_status(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of the current state."""
        elapsed: float | None = None
        if self._start_time is not None:
            end = self._end_time or datetime.now(timezone.utc)
            elapsed = (end - self._start_time).total_seconds()

        return {
            "status": self._status,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "elapsed_secs": round(elapsed, 1) if elapsed is not None else None,
            "line_count": len(self._log_lines),
            "config": self._config,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _reset_state(self, config: dict[str, Any]) -> None:
        """Clear state for a fresh run.  Must be called under ``_lock``."""
        self._status = _STATUS_RUNNING
        self._current_process = None
        self._log_lines = []
        self._start_time = datetime.now(timezone.utc)
        self._end_time = None
        self._config = dict(config)

    @staticmethod
    def _build_command(config: dict[str, Any]) -> list[str]:
        """Build the CLI argv list for the subprocess."""
        cmd: list[str] = [
            sys.executable,
            "-m",
            "tradingagents.trading.daily_runner",
        ]

        if config.get("dry_run"):
            cmd.append("--dry-run")

        if not config.get("use_screener", True):
            cmd.append("--no-screen")

        candidates = config.get("num_candidates")
        if candidates is not None:
            cmd.append(f"--candidates={int(candidates)}")

        max_pos = config.get("max_positions")
        if max_pos is not None:
            cmd.append(f"--max-positions={int(max_pos)}")

        tickers: list[str] | None = config.get("tickers")
        if tickers:
            cmd.append(f"--tickers={','.join(tickers)}")

        return cmd

    def _create_log_file(self) -> Path:
        """Create (and return the path to) a timestamped log file."""
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        return LOGS_DIR / f"pipeline_{ts}.log"

    async def _read_output(
        self,
        process: asyncio.subprocess.Process,
        log_file_path: Path,
    ) -> None:
        """Read subprocess stdout line-by-line, fan out to subscribers & file.

        Runs as a background ``asyncio.Task``.
        """
        assert process.stdout is not None  # guaranteed by PIPE  # noqa: S101

        try:
            with log_file_path.open("a", encoding="utf-8") as fh:
                async for raw_bytes in process.stdout:
                    raw_line = raw_bytes.decode("utf-8", errors="replace").rstrip("\n\r")
                    if not raw_line:
                        continue

                    entry = _make_log_entry(raw_line)

                    # Persist to file
                    try:
                        fh.write(raw_line + "\n")
                        fh.flush()
                    except OSError:
                        logger.exception("Failed to write to log file.")

                    # Append + broadcast
                    async with self._lock:
                        self._log_lines.append(entry)
                        self._broadcast(entry)

        except Exception:
            logger.exception("Error reading pipeline output stream.")

        # Wait for exit code
        return_code = await process.wait()

        async with self._lock:
            if self._status == _STATUS_RUNNING:
                self._status = _STATUS_COMPLETE if return_code == 0 else _STATUS_ERROR
            self._end_time = datetime.now(timezone.utc)
            self._current_process = None

            # Emit a runner-level summary line
            label = "completed successfully" if return_code == 0 else f"exited with code {return_code}"
            summary = _make_log_entry(f"[RUNNER] Pipeline {label}.")
            summary["level"] = "INFO" if return_code == 0 else "ERROR"
            self._log_lines.append(summary)
            self._broadcast(summary)
            self._broadcast_sentinel()

        logger.info("Pipeline finished (rc=%s, status=%s).", return_code, self._status)

    # -- fan-out helpers (must be called under _lock) ----------------------

    def _broadcast(self, entry: LogLine) -> None:
        for q in self._subscribers:
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                logger.warning("Subscriber queue full — dropping log line.")

    def _broadcast_sentinel(self) -> None:
        for q in self._subscribers:
            try:
                q.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                pass


# ---------------------------------------------------------------------------
# SSE formatting helpers
# ---------------------------------------------------------------------------

def _sse_data(entry: LogLine) -> str:
    """Format a log line as an SSE ``data:`` frame."""
    return f"data: {json.dumps(entry)}\n\n"


def _sse_done(status: str) -> str:
    """Format the final SSE ``event: done`` frame."""
    return f"event: done\ndata: {json.dumps({'status': status})}\n\n"


# ═══════════════════════════════════════════════════════════════════════════
# Log-file management functions
# ═══════════════════════════════════════════════════════════════════════════

def list_log_files(logs_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return metadata for ``pipeline_*.log`` files from the past 7 days.

    Each entry::

        {"filename": "pipeline_2026-05-10_142300.log",
         "date": "2026-05-10",
         "size_bytes": 48201,
         "line_count": 312}

    Results are sorted newest-first.
    """
    logs_dir = logs_dir or LOGS_DIR
    if not logs_dir.is_dir():
        return []

    cutoff = datetime.now() - timedelta(days=7)
    results: list[dict[str, Any]] = []

    for path in sorted(logs_dir.glob("pipeline_*.log"), reverse=True):
        try:
            stat = path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime)
            if mtime < cutoff:
                continue

            # Try extracting the date from the filename (pipeline_YYYY-MM-DD_HHMMSS.log)
            stem = path.stem  # e.g. "pipeline_2026-05-10_142300"
            file_date = stem.split("_", 1)[1][:10] if "_" in stem else mtime.strftime("%Y-%m-%d")

            line_count = _count_lines(path)

            results.append({
                "filename": path.name,
                "date": file_date,
                "size_bytes": stat.st_size,
                "line_count": line_count,
            })
        except OSError:
            logger.warning("Could not stat log file %s", path)

    return results


def read_log_file(logs_dir: Path | None, filename: str) -> str | None:
    """Read and return the full contents of a log file.

    Returns ``None`` if the file does not exist, is not a regular file, or
    the resolved path escapes ``logs_dir`` (path-traversal guard).
    """
    logs_dir = logs_dir or LOGS_DIR

    try:
        target = (logs_dir / filename).resolve()
    except (OSError, ValueError):
        return None

    # Path-traversal guard: resolved path must live inside logs_dir
    try:
        target.relative_to(logs_dir.resolve())
    except ValueError:
        logger.warning("Path traversal attempt blocked: %s", filename)
        return None

    if not target.is_file():
        return None

    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read log file %s", target)
        return None


def cleanup_old_logs(logs_dir: Path | None = None, max_age_days: int = 7) -> int:
    """Delete ``pipeline_*.log`` files older than *max_age_days*.

    Returns the number of files deleted.
    """
    logs_dir = logs_dir or LOGS_DIR
    if not logs_dir.is_dir():
        return 0

    cutoff = datetime.now() - timedelta(days=max_age_days)
    deleted = 0

    for path in logs_dir.glob("pipeline_*.log"):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if mtime < cutoff:
                path.unlink()
                deleted += 1
                logger.info("Deleted old log file: %s", path.name)
        except OSError:
            logger.warning("Could not delete log file %s", path)

    return deleted


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _count_lines(path: Path) -> int:
    """Count non-empty lines in a file without loading it all into memory."""
    count = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for _ in fh:
                count += 1
    except OSError:
        pass
    return count
