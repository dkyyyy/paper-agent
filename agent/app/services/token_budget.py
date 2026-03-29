"""Token budget tracking and context compression helpers."""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TokenBudget:
    """Track and control token usage for a research session."""

    budget: int = 50000
    used: int = 0
    compress_threshold: float = 0.8
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.used)

    @property
    def usage_ratio(self) -> float:
        return self.used / self.budget if self.budget > 0 else 1.0

    @property
    def should_compress(self) -> bool:
        return self.usage_ratio >= self.compress_threshold

    @property
    def is_exhausted(self) -> bool:
        return self.used >= self.budget

    def record(self, prompt_tokens: int, completion_tokens: int, source: str = "") -> None:
        """Record the token usage of a single LLM call."""
        total = prompt_tokens + completion_tokens
        self.used += total
        self.history.append(
            {
                "source": source,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total": total,
                "cumulative": self.used,
            }
        )
        logger.debug(
            "Token usage: +%s (total: %s/%s, source: %s)",
            total,
            self.used,
            self.budget,
            source,
        )

        if self.is_exhausted:
            logger.warning("Token budget exhausted: %s/%s", self.used, self.budget)
        elif self.should_compress:
            logger.info("Token budget at %.0f%%, context compression recommended", self.usage_ratio * 100)

    def estimate_available(self, reserved_for_output: int = 2000) -> int:
        """Estimate prompt tokens available after reserving output space."""
        return max(0, self.remaining - reserved_for_output)

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget,
            "used": self.used,
            "remaining": self.remaining,
            "usage_ratio": round(self.usage_ratio, 3),
            "should_compress": self.should_compress,
            "is_exhausted": self.is_exhausted,
        }


def compress_messages(
    messages: list[dict[str, str]],
    system_prompt: str,
    keep_recent: int = 3,
) -> list[dict[str, str]]:
    """Compress message history while preserving the system prompt and recent turns."""
    system_message = {"role": "system", "content": system_prompt}
    recent_count = keep_recent * 2

    if len(messages) <= recent_count:
        return [system_message, *messages]

    old_messages = messages[:-recent_count]
    recent_messages = messages[-recent_count:]

    summary_parts: list[str] = []
    for message in old_messages:
        role = message.get("role", "unknown")
        content = message.get("content", "")
        if len(content) > 200:
            content = content[:200] + "..."
        summary_parts.append(f"[{role}]: {content}")

    summary_message = {
        "role": "assistant",
        "content": "以下是之前对话的摘要：\n" + "\n".join(summary_parts),
    }
    compressed = [system_message, summary_message, *recent_messages]
    logger.info("Compressed messages: %s -> %s", len(messages), len(compressed))
    return compressed