"""LLM factory: returns the configured LLM instance."""

from functools import lru_cache

from langchain_core.language_models import BaseChatModel


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    """Get the LLM instance based on config."""
    from app.config import config

    if config.llm_provider == "dashscope":
        from langchain_community.chat_models.tongyi import ChatTongyi

        return ChatTongyi(
            model=config.llm_model,
            dashscope_api_key=config.llm_api_key,
            streaming=True,
        )
    if config.llm_provider == "zhipu":
        from langchain_community.chat_models import ChatZhipuAI

        return ChatZhipuAI(
            model=config.llm_model,
            api_key=config.llm_api_key,
        )
    raise ValueError(f"Unsupported LLM provider: {config.llm_provider}")