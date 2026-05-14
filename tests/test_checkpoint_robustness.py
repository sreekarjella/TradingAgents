"""Tests for the checkpoint robustness layer.

Covers two real-world failure modes seen in production logs:
  1. ``Object of type AIMessage is not JSON serializable`` when an
     LLM message lands in checkpoint metadata.
  2. ``KeyError: 'pending_sends'`` when a stored checkpoint was written
     by an older langgraph version that didn't include that key.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from tradingagents.graph.checkpointer import (
    _json_default,
    SafeSqliteSaver,
    checkpoint_step,
    get_checkpointer,
    thread_id,
)


class TestJsonDefault(unittest.TestCase):
    """The fallback encoder must never raise on langchain message types."""

    def test_aimessage_serialises(self):
        msg = AIMessage(content="hello from puppy")
        encoded = json.dumps({"writes": {"messages": [msg]}}, default=_json_default)
        # Round-trip must succeed and contain the text.
        self.assertIn("hello from puppy", encoded)

    def test_humanmessage_serialises(self):
        msg = HumanMessage(content="prompt")
        encoded = json.dumps(msg, default=_json_default)
        self.assertIn("prompt", encoded)

    def test_arbitrary_object_does_not_raise(self):
        """langchain's ``dumpd`` wraps unknown objects in a ``not_implemented``
        envelope rather than raising — we only need to guarantee no crash."""

        class Weird:
            def __str__(self):
                return "<weird>"

        # Must not raise; structured form is fine.
        encoded = json.dumps({"x": Weird()}, default=_json_default)
        self.assertIn("Weird", encoded)


class TestSafeSqliteSaverPut(unittest.TestCase):
    """SafeSqliteSaver.put must accept metadata containing AIMessage."""

    def test_put_with_aimessage_in_metadata(self):
        # Use in-memory SQLite for speed.
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            saver = SafeSqliteSaver(conn)
            saver.setup()
            cfg = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
            checkpoint = {
                "v": 1,
                "id": "ckpt-1",
                "ts": "2026-05-14T00:00:00+00:00",
                "channel_values": {"messages": []},
                "channel_versions": {},
                "versions_seen": {},
                "pending_sends": [],
            }
            metadata = {
                "source": "loop",
                "step": 1,
                "writes": {"messages": [AIMessage(content="from a node")]},
                "parents": {},
            }
            # Stock SqliteSaver would raise TypeError here; ours must succeed.
            result = saver.put(cfg, checkpoint, metadata, {})
            self.assertEqual(result["configurable"]["checkpoint_id"], "ckpt-1")
        finally:
            conn.close()


class TestStaleCheckpointAutoClear(unittest.TestCase):
    """A checkpoint missing required keys is silently cleared on read."""

    def test_stale_checkpoint_returns_none_and_clears(self):
        with tempfile.TemporaryDirectory() as tmp:
            ticker = "STALE"
            date = "2026-05-14"
            tid = thread_id(ticker, date)

            # Hand-craft a stale checkpoint missing 'channel_versions'.
            with get_checkpointer(tmp, ticker) as saver:
                cfg = {"configurable": {"thread_id": tid, "checkpoint_ns": ""}}
                stale_checkpoint = {
                    "v": 1,
                    "id": "stale-1",
                    "ts": "2026-05-14T00:00:00+00:00",
                    "channel_values": {"messages": []},
                    # Intentionally missing: channel_versions, versions_seen
                    "pending_sends": [],
                }
                saver.put(cfg, stale_checkpoint, {"step": 5, "source": "loop", "parents": {}}, {})

            # Reading via checkpoint_step should detect staleness, clear, return None.
            step = checkpoint_step(tmp, ticker, date)
            self.assertIsNone(step)

            # Subsequent read confirms it's gone (no row to load).
            step_again = checkpoint_step(tmp, ticker, date)
            self.assertIsNone(step_again)

    def test_valid_checkpoint_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            ticker = "GOOD"
            date = "2026-05-14"
            tid = thread_id(ticker, date)

            with get_checkpointer(tmp, ticker) as saver:
                cfg = {"configurable": {"thread_id": tid, "checkpoint_ns": ""}}
                valid_checkpoint = {
                    "v": 1,
                    "id": "good-1",
                    "ts": "2026-05-14T00:00:00+00:00",
                    "channel_values": {"messages": []},
                    "channel_versions": {},
                    "versions_seen": {},
                    "pending_sends": [],
                }
                saver.put(cfg, valid_checkpoint, {"step": 7, "source": "loop", "parents": {}}, {})

            self.assertEqual(checkpoint_step(tmp, ticker, date), 7)


if __name__ == "__main__":
    unittest.main()
