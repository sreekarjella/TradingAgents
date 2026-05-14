"""LangGraph checkpoint support for resumable analysis runs.

Per-ticker SQLite databases so concurrent tickers don't contend.

Two robustness layers wrap the upstream :class:`SqliteSaver`:

1. ``SafeSqliteSaver`` — tolerant metadata serializer.  langgraph's stock
   ``SqliteSaver.put`` calls ``json.dumps`` on metadata directly, which
   blows up when an ``AIMessage`` lands in the ``writes`` dict (it does,
   for nodes that emit messages).  We serialise via a custom encoder
   that falls back to ``str(obj)`` for anything langchain-y.

2. ``checkpoint_step`` validates the loaded checkpoint and silently
   clears it if mandatory keys (e.g. ``pending_sends``) are missing —
   this protects against schema drift between langgraph minor versions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from langchain_core.load import dumpd
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.base import (
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.runnables import RunnableConfig

from tradingagents.dataflows.utils import safe_ticker_component

logger = logging.getLogger(__name__)


# ── tolerant JSON encoder ────────────────────────────────────────────────


def _json_default(obj: Any) -> Any:
    """Fallback for objects ``json.dumps`` can't natively handle.

    Order matters: try langchain's structured ``dumpd`` first (lossless
    round-trip), then fall back to ``str(obj)`` so we never crash a
    checkpoint write — losing pretty serialisation is always better
    than losing the run.
    """
    if isinstance(obj, BaseMessage):
        try:
            return dumpd(obj)
        except Exception:  # pragma: no cover - last-ditch
            return {"type": obj.__class__.__name__, "content": str(obj.content)}
    try:
        return dumpd(obj)
    except Exception:
        return str(obj)


class SafeSqliteSaver(SqliteSaver):
    """SqliteSaver that survives non-JSON-native metadata values.

    Overrides only :meth:`put`; everything else (``get``, ``list``,
    ``put_writes``) is inherited unchanged.
    """

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"]["checkpoint_ns"]
        type_, serialized_checkpoint = self.serde.dumps_typed(checkpoint)
        serialized_metadata = json.dumps(
            get_checkpoint_metadata(config, metadata),
            ensure_ascii=False,
            default=_json_default,
        ).encode("utf-8", "ignore")
        with self.cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO checkpoints "
                "(thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, "
                "type, checkpoint, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(thread_id),
                    checkpoint_ns,
                    checkpoint["id"],
                    config["configurable"].get("checkpoint_id"),
                    type_,
                    serialized_checkpoint,
                    serialized_metadata,
                ),
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }


# ── public helpers ───────────────────────────────────────────────────────


# Mandatory keys the current langgraph version expects in a checkpoint.
# A checkpoint missing any of these came from an older minor and will
# crash on resume — we clear it so the next run starts fresh.
_REQUIRED_CHECKPOINT_KEYS = ("channel_values", "channel_versions", "versions_seen")


def _db_path(data_dir: str | Path, ticker: str) -> Path:
    """Return the SQLite checkpoint DB path for a ticker."""
    safe = safe_ticker_component(ticker).upper()
    p = Path(data_dir) / "checkpoints"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{safe}.db"


def thread_id(ticker: str, date: str) -> str:
    """Deterministic thread ID for a ticker+date pair."""
    return hashlib.sha256(f"{ticker.upper()}:{date}".encode()).hexdigest()[:16]


@contextmanager
def get_checkpointer(
    data_dir: str | Path, ticker: str
) -> Generator[SafeSqliteSaver, None, None]:
    """Context manager yielding a SafeSqliteSaver backed by a per-ticker DB."""
    db = _db_path(data_dir, ticker)
    conn = sqlite3.connect(str(db), check_same_thread=False)
    try:
        saver = SafeSqliteSaver(conn)
        saver.setup()
        yield saver
    finally:
        conn.close()


def has_checkpoint(data_dir: str | Path, ticker: str, date: str) -> bool:
    """Check whether a resumable checkpoint exists for ticker+date."""
    return checkpoint_step(data_dir, ticker, date) is not None


def _is_checkpoint_valid(checkpoint: dict) -> bool:
    """Return True if checkpoint has all keys current langgraph requires."""
    return all(k in checkpoint for k in _REQUIRED_CHECKPOINT_KEYS)


def checkpoint_step(data_dir: str | Path, ticker: str, date: str) -> int | None:
    """Return the step number of the latest checkpoint, or None if none exists.

    If the stored checkpoint is missing keys the current langgraph version
    requires (e.g. ``pending_sends`` after a minor-version upgrade) the
    checkpoint is silently cleared and ``None`` is returned, so the
    pipeline starts fresh instead of crashing on resume.
    """
    db = _db_path(data_dir, ticker)
    if not db.exists():
        return None
    tid = thread_id(ticker, date)
    try:
        with get_checkpointer(data_dir, ticker) as saver:
            config = {"configurable": {"thread_id": tid}}
            cp = saver.get_tuple(config)
            if cp is None:
                return None
            if not _is_checkpoint_valid(cp.checkpoint):
                logger.warning(
                    "Stale checkpoint for %s on %s missing required keys; clearing",
                    ticker, date,
                )
                # Deferred clear — can't mutate inside the context.
                stale = True
            else:
                stale = False
                step = cp.metadata.get("step")
    except Exception as exc:  # corrupt DB / schema mismatch
        logger.warning(
            "Could not read checkpoint for %s on %s (%s); clearing", ticker, date, exc,
        )
        clear_checkpoint(data_dir, ticker, date)
        return None

    if stale:
        clear_checkpoint(data_dir, ticker, date)
        return None
    return step


def clear_all_checkpoints(data_dir: str | Path) -> int:
    """Remove all checkpoint DBs. Returns number of files deleted."""
    cp_dir = Path(data_dir) / "checkpoints"
    if not cp_dir.exists():
        return 0
    dbs = list(cp_dir.glob("*.db"))
    for db in dbs:
        db.unlink()
    return len(dbs)


def clear_checkpoint(data_dir: str | Path, ticker: str, date: str) -> None:
    """Remove checkpoint for a specific ticker+date by deleting the thread's rows."""
    db = _db_path(data_dir, ticker)
    if not db.exists():
        return
    tid = thread_id(ticker, date)
    conn = sqlite3.connect(str(db))
    try:
        for table in ("writes", "checkpoints"):
            conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (tid,))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
