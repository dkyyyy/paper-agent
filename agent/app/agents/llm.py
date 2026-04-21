"""LLM factory and guarded invocation helpers for supported chat providers."""

import logging
from contextvars import ContextVar, Token
from functools import lru_cache
from typing import Any, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from app.config import config
from app.services.token_budget import TokenBudget

logger = logging.getLogger(__name__)

_current_token_budget: ContextVar[TokenBudget | None] = ContextVar("current_token_budget", default=None)


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    """Build the configured chat model client."""
    if config.llm_provider == "dashscope":
        if not config.llm_api_key:
            raise ValueError("LLM_API_KEY is required when LLM_PROVIDER=dashscope")
        from langchain_community.chat_models.tongyi import ChatTongyi

        return ChatTongyi(
            model=config.llm_model,
            dashscope_api_key=config.llm_api_key,
            streaming=True,
        )

    if config.llm_provider == "zhipu":
        if not config.llm_api_key:
            raise ValueError("LLM_API_KEY is required when LLM_PROVIDER=zhipu")
        from langchain_community.chat_models import ChatZhipuAI

        return ChatZhipuAI(
            model=config.llm_model,
            api_key=config.llm_api_key,
        )

    if config.llm_provider in {"openai", "deepseek"}:
        if not config.llm_api_key:
            raise ValueError(f"LLM_API_KEY is required when LLM_PROVIDER={config.llm_provider}")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.llm_model,
            api_key=config.llm_api_key,
            base_url=config.effective_llm_base_url,
            streaming=True,
        )

    raise ValueError(f"Unsupported LLM provider: {config.llm_provider}")


def set_current_token_budget(budget: TokenBudget | None) -> Token:
    """Bind the current request token budget to the running context."""
    return _current_token_budget.set(budget)


def reset_current_token_budget(token: Token) -> None:
    """Clear the current request token budget from the running context."""
    _current_token_budget.reset(token)


def get_current_token_budget() -> TokenBudget | None:
    """Return the token budget bound to the running request, if any."""
    return _current_token_budget.get()


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _extract_usage_tokens(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None) or {}
    prompt_tokens = (
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or usage.get("input_token_count")
        or usage.get("prompt_token_count")
        or 0
    )
    completion_tokens = (
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or usage.get("output_token_count")
        or usage.get("completion_token_count")
        or 0
    )

    if prompt_tokens or completion_tokens:
        return int(prompt_tokens), int(completion_tokens)

    response_metadata = getattr(response, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage") or response_metadata.get("usage") or {}
    prompt_tokens = token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
    completion_tokens = token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
    return int(prompt_tokens), int(completion_tokens)


def _estimate_prompt_tokens(messages: Sequence[BaseMessage]) -> int:
    total_chars = sum(len(_content_to_text(getattr(message, "content", ""))) for message in messages)
    return max(1, total_chars // 4)


def invoke_llm(
    messages: Sequence[BaseMessage],
    *,
    source: str,
    budget: TokenBudget | None = None,
) -> Any:
    """Invoke the configured LLM and record token usage for the active request."""
    active_budget = budget or get_current_token_budget()
    if active_budget and active_budget.is_exhausted:
        raise RuntimeError(f"Token budget exhausted before {source}")

    llm = get_llm()
    response = llm.invoke(list(messages))

    if active_budget is not None:
        prompt_tokens, completion_tokens = _extract_usage_tokens(response)
        if prompt_tokens == 0:
            prompt_tokens = _estimate_prompt_tokens(messages)
        if completion_tokens == 0:
            completion_tokens = max(1, len(_content_to_text(getattr(response, "content", response))) // 4)
        active_budget.record(prompt_tokens, completion_tokens, source=source)
        if active_budget.is_exhausted:
            logger.warning("Token budget exhausted after %s", source)

    return response