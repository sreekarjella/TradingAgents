"""Tests for thinking-mode safety net in NormalizedChatOpenAI.

Both MLX (mlx_lm.server) and Ollama, when serving Qwen3 with
``chat_template_kwargs.enable_thinking=true``, return the model's
chain-of-thought in a separate ``reasoning`` field on the assistant
message. LangChain's ChatOpenAI silently drops it. When the model
burns its entire token budget on thinking and never gets to write a
final answer, the AIMessage comes back with empty ``content`` and
the agent persists a blank report — exactly what wiped the
2026-05-13 run.

Two pieces verified:

1. ``reasoning`` is captured into ``additional_kwargs['reasoning_content']``
   on every response so callers can inspect chain-of-thought.
2. When ``content`` is empty/whitespace but ``reasoning`` has text, the
   reasoning is promoted to be the content (last-resort safety net so
   agents never save blank reports).

Plus: the OpenAIClient factory wires Qwen3-on-MLX-or-Ollama with
``enable_thinking=true`` and a sensible max_tokens default (the
*primary* fix; the safety net is the backstop).
"""

import pytest

from tradingagents.llm_clients.openai_client import (
    NormalizedChatOpenAI,
    OpenAIClient,
    _QWEN3_THINKING_MAX_TOKENS,
)


def _client(*, provider="mlx"):
    base_url = (
        "http://localhost:8081/v1" if provider == "mlx"
        else "http://localhost:11434/v1"
    )
    return NormalizedChatOpenAI(
        model="qwen3:14b-q8_0" if provider == "ollama" else "mlx-community/Qwen3-14B-4bit",
        api_key="placeholder",
        base_url=base_url,
    )


def _response(content, reasoning=None, finish="stop"):
    """Build a server response dict (same shape for MLX and Ollama)."""
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning"] = reasoning
    return {
        "model": "qwen3",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


# ---------------------------------------------------------------------------
# Reasoning capture: stash into additional_kwargs for caller inspection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReasoningCapture:
    def test_reasoning_field_captured_into_additional_kwargs(self):
        """When the response carries ``reasoning``, it lands on the AIMessage's
        ``additional_kwargs['reasoning_content']`` for chain-of-thought logging."""
        client = _client()
        result = client._create_chat_result(
            _response(content="Buy AAPL.", reasoning="Step 1: trend up. Step 2: ...")
        )
        ai = result.generations[0].message
        assert ai.additional_kwargs["reasoning_content"] == "Step 1: trend up. Step 2: ..."
        # Content is non-empty so it stays untouched.
        assert ai.content == "Buy AAPL."

    def test_no_reasoning_means_no_additional_kwargs_key(self):
        """When the server returns no reasoning field, we add nothing."""
        client = _client()
        result = client._create_chat_result(_response(content="Hello."))
        ai = result.generations[0].message
        assert "reasoning_content" not in ai.additional_kwargs
        assert ai.content == "Hello."


# ---------------------------------------------------------------------------
# Safety net: empty content + populated reasoning → promote reasoning
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmptyContentSafetyNet:
    def test_empty_content_is_replaced_by_reasoning(self):
        """Thinking-mode truncation: content is empty, reasoning has the
        actual answer. We promote the reasoning so the agent doesn't save
        a blank report."""
        client = _client()
        result = client._create_chat_result(
            _response(
                content="",
                reasoning="The market shows a bullish trend with RSI 65.",
                finish="length",
            )
        )
        ai = result.generations[0].message
        assert ai.content == "The market shows a bullish trend with RSI 65."
        # And it's still in additional_kwargs for transparency.
        assert (
            ai.additional_kwargs["reasoning_content"]
            == "The market shows a bullish trend with RSI 65."
        )

    def test_whitespace_only_content_is_replaced(self):
        """Whitespace-only counts as empty for the safety net."""
        client = _client()
        result = client._create_chat_result(
            _response(content="   \n\n  ", reasoning="Real answer here.")
        )
        ai = result.generations[0].message
        assert ai.content == "Real answer here."

    def test_non_empty_content_is_preserved(self):
        """The safety net must not stomp valid content even when reasoning
        is also present (the normal happy path with thinking mode)."""
        client = _client()
        result = client._create_chat_result(
            _response(content="Final answer: HOLD.", reasoning="prior thoughts")
        )
        ai = result.generations[0].message
        assert ai.content == "Final answer: HOLD."

    def test_empty_content_with_no_reasoning_stays_empty(self):
        """If neither field has anything, we don't fabricate text — let
        the caller see the empty response and decide how to retry."""
        client = _client()
        result = client._create_chat_result(_response(content=""))
        ai = result.generations[0].message
        assert ai.content == ""

    def test_safety_net_works_for_ollama_responses_too(self):
        """Ollama and MLX return the same response shape — one set of
        tests covers both."""
        client = _client(provider="ollama")
        result = client._create_chat_result(
            _response(content="", reasoning="Bullish on tech.", finish="length")
        )
        ai = result.generations[0].message
        assert ai.content == "Bullish on tech."


# ---------------------------------------------------------------------------
# Factory wiring: MLX + Ollama Qwen3 → thinking enabled + max_tokens default
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFactoryWiring:
    def test_mlx_qwen3_enables_thinking_and_max_tokens(self):
        """Primary fix: enough headroom that thinking finishes and writes
        its answer into ``content`` before truncation kicks in."""
        client = OpenAIClient(
            model="mlx-community/Qwen3-14B-4bit",
            base_url="http://localhost:8081/v1",
            provider="mlx",
        )
        llm = client.get_llm()
        assert isinstance(llm, NormalizedChatOpenAI)
        assert llm.max_tokens == _QWEN3_THINKING_MAX_TOKENS
        assert llm.extra_body == {"chat_template_kwargs": {"enable_thinking": True}}

    def test_ollama_qwen3_enables_thinking_and_max_tokens(self):
        """Ollama needs the explicit opt-in via chat_template_kwargs;
        without it Ollama strips thinking server-side."""
        client = OpenAIClient(
            model="qwen3:32b-q8_0",
            base_url="http://localhost:11434/v1",
            provider="ollama",
        )
        llm = client.get_llm()
        assert isinstance(llm, NormalizedChatOpenAI)
        assert llm.max_tokens == _QWEN3_THINKING_MAX_TOKENS
        assert llm.extra_body == {"chat_template_kwargs": {"enable_thinking": True}}

    def test_user_max_tokens_overrides_default(self):
        """User-provided max_tokens always wins over our default."""
        client = OpenAIClient(
            model="mlx-community/Qwen3-14B-4bit",
            base_url="http://localhost:8081/v1",
            provider="mlx",
            max_tokens=16384,
        )
        llm = client.get_llm()
        assert llm.max_tokens == 16384

    def test_user_extra_body_overrides_default_thinking(self):
        """A user that wants thinking off (e.g. latency-sensitive smoke
        test) can pass extra_body and we won't stomp it."""
        client = OpenAIClient(
            model="qwen3:14b-q8_0",
            base_url="http://localhost:11434/v1",
            provider="ollama",
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        llm = client.get_llm()
        assert llm.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}

    def test_ollama_non_qwen3_does_not_force_thinking(self):
        """A user running, say, llama3 via Ollama shouldn't have
        Qwen3-specific options injected into their request."""
        client = OpenAIClient(
            model="llama3:8b",
            base_url="http://localhost:11434/v1",
            provider="ollama",
        )
        llm = client.get_llm()
        assert llm.max_tokens is None
        assert llm.extra_body is None

    def test_mlx_non_qwen3_does_not_force_thinking(self):
        """Symmetric check for MLX with a non-Qwen model."""
        client = OpenAIClient(
            model="mlx-community/Mistral-7B-v0.3-4bit",
            base_url="http://localhost:8081/v1",
            provider="mlx",
        )
        llm = client.get_llm()
        assert llm.max_tokens is None
        assert llm.extra_body is None
