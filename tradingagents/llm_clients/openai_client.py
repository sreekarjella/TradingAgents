import os
from typing import Any, Optional

import httpx
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model


class NormalizedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with normalized content output and thinking-mode safety net.

    The Responses API returns content as a list of typed blocks
    (reasoning, text, etc.). ``invoke`` normalizes to string for
    consistent downstream handling. ``with_structured_output`` defaults
    to function-calling so the Responses-API parse path is avoided
    (langchain-openai's parse path emits noisy
    PydanticSerializationUnexpectedValue warnings per call without
    affecting correctness).

    Both MLX (mlx_lm.server) and Ollama, when serving Qwen3 with
    ``chat_template_kwargs.enable_thinking=true``, return the model's
    chain-of-thought in a separate ``reasoning`` field on the assistant
    message. LangChain's ChatOpenAI silently drops it. When the model
    burns its entire token budget on thinking and never gets to write a
    final answer, the AIMessage comes back with empty ``content`` and
    the agent persists a blank report — the bug that wiped the
    2026-05-13 run. ``_create_chat_result`` below is the safety net:
    capture ``reasoning`` into ``additional_kwargs`` for inspection,
    and if ``content`` is empty, promote the reasoning to be the content
    so we never save blank reports. The override is a no-op for
    providers/models that don't emit a ``reasoning`` field.

    Provider-specific quirks (e.g. DeepSeek's reasoning_content
    round-trip) live in purpose-built subclasses below so this base
    class stays small.
    """

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))

    def with_structured_output(self, schema, *, method=None, **kwargs):
        if method is None:
            method = "function_calling"
        return super().with_structured_output(schema, method=method, **kwargs)

    def _create_chat_result(self, response, generation_info=None):
        chat_result = super()._create_chat_result(response, generation_info)
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )
        for generation, choice in zip(
            chat_result.generations, response_dict.get("choices", [])
        ):
            reasoning = (choice.get("message") or {}).get("reasoning")
            if not reasoning:
                continue
            generation.message.additional_kwargs["reasoning_content"] = reasoning
            content = generation.message.content
            content_text = (
                content if isinstance(content, str)
                else "".join(
                    c.get("text", "") for c in (content or [])
                    if isinstance(c, dict)
                )
            )
            if not (content_text or "").strip():
                generation.message.content = reasoning.strip()
        return chat_result


def _input_to_messages(input_: Any) -> list:
    """Normalise a langchain LLM input to a list of message objects.

    Accepts a list of messages, a ``ChatPromptValue`` (from a
    ChatPromptTemplate), or anything else (treated as no messages).
    Used by providers that need to walk the outgoing message history;
    in particular DeepSeek thinking-mode propagation must work for
    both bare-list invocations and ChatPromptTemplate-driven ones, so
    treating only ``list`` here would silently skip half the call sites.
    """
    if isinstance(input_, list):
        return input_
    if hasattr(input_, "to_messages"):
        return input_.to_messages()
    return []


class DeepSeekChatOpenAI(NormalizedChatOpenAI):
    """DeepSeek-specific overrides on top of the OpenAI-compatible client.

    Two quirks that don't apply to other OpenAI-compatible providers:

    1. **Thinking-mode round-trip.** When DeepSeek's thinking models return
       a response with ``reasoning_content``, that field must be echoed
       back as part of the assistant message on the next turn or the API
       fails with HTTP 400. ``_create_chat_result`` captures the field on
       receive and ``_get_request_payload`` re-attaches it on send.

    2. **deepseek-reasoner has no tool_choice.** Structured output via
       function-calling is unavailable, so we raise NotImplementedError
       and let the agent factories fall back to free-text generation
       (see ``tradingagents/agents/utils/structured.py``).
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        outgoing = payload.get("messages", [])
        for message_dict, message in zip(outgoing, _input_to_messages(input_)):
            if not isinstance(message, AIMessage):
                continue
            reasoning = message.additional_kwargs.get("reasoning_content")
            if reasoning is not None:
                message_dict["reasoning_content"] = reasoning
        return payload

    def _create_chat_result(self, response, generation_info=None):
        chat_result = super()._create_chat_result(response, generation_info)
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )
        for generation, choice in zip(
            chat_result.generations, response_dict.get("choices", [])
        ):
            reasoning = choice.get("message", {}).get("reasoning_content")
            if reasoning is not None:
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return chat_result

    def with_structured_output(self, schema, *, method=None, **kwargs):
        if self.model_name == "deepseek-reasoner":
            raise NotImplementedError(
                "deepseek-reasoner does not support tool_choice; structured "
                "output is unavailable. Agent factories fall back to "
                "free-text generation automatically."
            )
        return super().with_structured_output(schema, method=method, **kwargs)


# Kwargs forwarded from user config to ChatOpenAI
_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "reasoning_effort", "max_tokens", "extra_body",
    "api_key", "callbacks", "http_client", "http_async_client",
)

# Default token budget for Qwen3 thinking models served via MLX or Ollama.
# Qwen3's chain-of-thought routinely uses 1–4K tokens before producing the
# final answer, and the analyst/debate prompts then need another 1–2K for
# the report itself. The OpenAI client's default cap of 4096 truncates
# thinking mid-stream and leaves ``content`` empty (only ``reasoning``
# populated, which LangChain drops). 8K gives thinking room to breathe
# with a safety margin.
_QWEN3_THINKING_MAX_TOKENS = 8192
_MLX_DEFAULT_MAX_TOKENS = 8192

# Provider base URLs and API key env vars
_PROVIDER_CONFIG = {
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "qwen": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
    "glm": ("https://api.z.ai/api/paas/v4/", "ZHIPU_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
    "mlx": ("http://localhost:8081/v1", None),
}


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI, Ollama, OpenRouter, and xAI providers.

    For native OpenAI models, uses the Responses API (/v1/responses) which
    supports reasoning_effort with function tools across all model families
    (GPT-4.1, GPT-5). Third-party compatible providers (xAI, OpenRouter,
    Ollama) use standard Chat Completions.
    """

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        """Return configured ChatOpenAI instance."""
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}

        # Provider-specific base URL and auth. An explicit base_url on the
        # client (e.g. a corporate proxy) takes precedence over the
        # provider default so users can route through their own gateway.
        if self.provider in _PROVIDER_CONFIG:
            default_base, api_key_env = _PROVIDER_CONFIG[self.provider]
            llm_kwargs["base_url"] = self.base_url or default_base
            if api_key_env:
                api_key = os.environ.get(api_key_env)
                if api_key:
                    llm_kwargs["api_key"] = api_key
            else:
                # Ollama / MLX: use dummy key and a direct (no-proxy) httpx
                # client so Walmart proxy doesn't intercept localhost traffic.
                llm_kwargs["api_key"] = "ollama"
                llm_kwargs["http_client"] = httpx.Client(
                    proxy=None, verify=False,
                    timeout=httpx.Timeout(600.0, connect=30.0),
                )
        elif self.base_url:
            llm_kwargs["base_url"] = self.base_url

        # Forward user-provided kwargs
        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # Native OpenAI: use Responses API for consistent behavior across
        # all model families. Third-party providers use Chat Completions.
        if self.provider == "openai":
            llm_kwargs["use_responses_api"] = True

        # Qwen3 thinking-mode (MLX or Ollama): keep thinking ENABLED for
        # reasoning quality, and make sure the model has enough tokens to
        # finish thinking AND write the answer. Both mlx_lm.server and
        # Ollama's OpenAI-compat endpoint return thinking output in a
        # separate ``reasoning`` field; if max_tokens runs out mid-thought
        # the final answer ends up in ``reasoning`` and ``content`` comes
        # back empty (LangChain drops the reasoning field). The base
        # NormalizedChatOpenAI safety net catches this, but the *primary*
        # fix is just giving thinking enough room to finish. Note: Ollama
        # requires us to opt in to thinking via chat_template_kwargs;
        # without it Ollama strips thinking server-side.
        is_qwen3_local = (
            self.provider in ("mlx", "ollama")
            and "qwen3" in self.model.lower()
        )
        if is_qwen3_local:
            llm_kwargs.setdefault("max_tokens", _QWEN3_THINKING_MAX_TOKENS)
            if "extra_body" not in self.kwargs:
                llm_kwargs["extra_body"] = {
                    "chat_template_kwargs": {"enable_thinking": True}
                }
            # Users can override extra_body via model_kwargs to disable
            # thinking for a specific run (e.g. latency-sensitive tests).

        # DeepSeek's thinking-mode quirks (reasoning_content round-trip)
        # live in their own subclass; everything else uses the base class
        # which already handles the generic ``reasoning`` field via the
        # safety net in NormalizedChatOpenAI._create_chat_result.
        chat_cls = DeepSeekChatOpenAI if self.provider == "deepseek" else NormalizedChatOpenAI
        return chat_cls(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for the provider."""
        return validate_model(self.provider, self.model)
