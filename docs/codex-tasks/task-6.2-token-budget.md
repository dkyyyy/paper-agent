# Codex 执行指令 — 任务 6.2：Token 预算控制

## 任务目标

控制单次研究任务的 Token 消耗，接近预算时压缩上下文，超出预算时停止迭代。

## 前置依赖

- 任务 3.1 已完成（Python 项目骨架 + config）

## 需要创建的文件

### 1. `agent/app/services/token_budget.py`

```python
"""Token 预算控制：追踪用量、压缩上下文、超限停止。"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TokenBudget:
    """Track and control token usage for a research session."""

    budget: int = 50000             # 总预算
    used: int = 0                   # 已使用
    compress_threshold: float = 0.8  # 80% 时触发压缩
    history: list[dict] = field(default_factory=list)  # 调用记录

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
        """Record a LLM call's token usage."""
        total = prompt_tokens + completion_tokens
        self.used += total
        self.history.append({
            "source": source,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total": total,
            "cumulative": self.used,
        })
        logger.debug(f"Token usage: +{total} (total: {self.used}/{self.budget}, source: {source})")

        if self.is_exhausted:
            logger.warning(f"Token budget exhausted: {self.used}/{self.budget}")
        elif self.should_compress:
            logger.info(f"Token budget {self.usage_ratio:.0%}, context compression recommended")

    def estimate_available(self, reserved_for_output: int = 2000) -> int:
        """Estimate how many tokens are available for the next prompt."""
        return max(0, self.remaining - reserved_for_output)

    def to_dict(self) -> dict:
        return {
            "budget": self.budget,
            "used": self.used,
            "remaining": self.remaining,
            "usage_ratio": round(self.usage_ratio, 3),
            "should_compress": self.should_compress,
            "is_exhausted": self.is_exhausted,
        }


def compress_messages(
    messages: list[dict],
    system_prompt: str,
    keep_recent: int = 3,
) -> list[dict]:
    """Compress message history to fit within token budget.

    Strategy:
    1. Always keep system prompt
    2. Keep the most recent N turns
    3. Summarize older messages into a single context message

    Args:
        messages: Full message history [{"role": "...", "content": "..."}]
        system_prompt: System prompt to always preserve
        keep_recent: Number of recent message pairs to keep

    Returns:
        Compressed message list
    """
    if len(messages) <= keep_recent * 2:
        # No compression needed
        return messages

    # Split into old and recent
    recent_count = keep_recent * 2  # pairs of user+assistant
    old_messages = messages[:-recent_count]
    recent_messages = messages[-recent_count:]

    # Summarize old messages
    old_summary_parts = []
    for msg in old_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # Truncate each old message
        if len(content) > 200:
            content = content[:200] + "..."
        old_summary_parts.append(f"[{role}]: {content}")

    summary = "以下是之前对话的摘要：\n" + "\n".join(old_summary_parts)

    compressed = [
        {"role": "assistant", "content": summary},
    ] + recent_messages

    logger.info(f"Compressed messages: {len(messages)} → {len(compressed)}")
    return compressed
```

### 2. `agent/tests/test_token_budget.py`

```python
"""Test token budget control."""

from app.services.token_budget import TokenBudget, compress_messages


def test_budget_tracking():
    budget = TokenBudget(budget=10000)
    assert budget.remaining == 10000
    assert budget.usage_ratio == 0.0
    assert not budget.should_compress
    assert not budget.is_exhausted

    budget.record(500, 200, source="search")
    assert budget.used == 700
    assert budget.remaining == 9300


def test_budget_compress_threshold():
    budget = TokenBudget(budget=10000)
    budget.record(4000, 4000, source="analysis")
    assert budget.should_compress  # 80%


def test_budget_exhausted():
    budget = TokenBudget(budget=1000)
    budget.record(600, 500, source="test")
    assert budget.is_exhausted


def test_compress_messages_no_compression_needed():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    result = compress_messages(messages, "system", keep_recent=3)
    assert len(result) == 2  # No change


def test_compress_messages():
    messages = []
    for i in range(10):
        messages.append({"role": "user", "content": f"question {i}"})
        messages.append({"role": "assistant", "content": f"answer {i}" * 50})

    result = compress_messages(messages, "system", keep_recent=3)
    # Should have: 1 summary + 6 recent (3 pairs)
    assert len(result) == 7
    assert "摘要" in result[0]["content"]


def test_budget_to_dict():
    budget = TokenBudget(budget=50000)
    budget.record(1000, 500, source="test")
    d = budget.to_dict()
    assert d["budget"] == 50000
    assert d["used"] == 1500
    assert d["remaining"] == 48500
```

## 验收标准

- [ ] 每次 LLM 调用后累计 Token 使用量
- [ ] 接近预算（80%）时 `should_compress` 返回 True
- [ ] 超出预算时 `is_exhausted` 返回 True
- [ ] `compress_messages` 保留系统提示 + 最近 3 轮 + 旧消息摘要
- [ ] `estimate_available` 预留输出 token 后返回可用量
- [ ] `to_dict()` 返回完整状态用于 Redis 存储
- [ ] 测试通过

## 提交

```bash
git add agent/app/services/token_budget.py agent/tests/test_token_budget.py
git commit -m "feat(agent): implement token budget control with context compression

- Track cumulative token usage per session
- Compress threshold at 80%, stop at 100%
- Message compression: keep recent N turns + summarize old
- Serializable state for Redis persistence"
```
