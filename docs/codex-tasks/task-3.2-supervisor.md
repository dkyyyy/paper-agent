# Codex 执行指令 — 任务 3.2：Supervisor Agent

## 任务目标

实现主调度 Agent，负责意图识别、任务拆解、子 Agent 调度、结果质量评估。使用 LangGraph StateGraph 构建有状态工作流。

## 前置依赖

- 任务 3.1 已完成（Python gRPC Server 骨架）
- 参考文档：`docs/02-dev-standards.md` Agent 开发模板、`docs/03-task-acceptance.md` 任务 3.2

## 需要创建的文件

### 1. `agent/app/prompts/supervisor.py`

```python
"""
Prompt: Supervisor Agent System Prompt
版本: v1.0
"""

SUPERVISOR_SYSTEM_PROMPT = """你是一个学术研究助手的调度中心。

## 角色
你负责理解用户的研究需求，将其拆解为子任务，并分配给专业的子 Agent 执行。

## 可用子 Agent
1. search_agent: 文献检索，支持 ArXiv、Semantic Scholar、DBLP 多源搜索
2. analysis_agent: 论文深度分析，提取研究问题、方法、数据集、指标、结果
3. synthesis_agent: 跨论文综合分析，生成对比报告和文献综述

## 意图分类
根据用户输入，识别以下四种意图之一：
- literature_review: 文献调研（关键词：调研、综述、最新进展、研究现状）
- paper_reading: 论文精读（关键词：分析这篇、解读、精读，通常伴随 PDF 上传）
- method_comparison: 方法对比（关键词：对比、比较、区别、优缺点）
- gap_analysis: Research Gap 发现（关键词：还有哪些方向、研究空白、未来方向）

## 任务编排规则
- literature_review: search_agent → analysis_agent → synthesis_agent
- paper_reading: analysis_agent（直接分析上传的 PDF）
- method_comparison: search_agent → analysis_agent（并行分析多篇） → synthesis_agent
- gap_analysis: 基于已有分析结果 → synthesis_agent

## 输出格式
以 JSON 格式输出任务计划：
```json
{
  "intent": "literature_review | paper_reading | method_comparison | gap_analysis",
  "topic": "用户研究主题的简洁描述",
  "plan": [
    {"step": 1, "agent": "search_agent", "task": "具体任务描述", "params": {}},
    {"step": 2, "agent": "analysis_agent", "task": "具体任务描述", "depends_on": [1]},
    {"step": 3, "agent": "synthesis_agent", "task": "具体任务描述", "depends_on": [2]}
  ]
}
```
"""

QUALITY_CHECK_PROMPT = """你是一个学术研究质量评审员。

请评估以下研究结果的质量：

## 用户原始需求
{user_query}

## 研究结果
{result}

## 评估标准
1. 相关性：结果是否回答了用户的问题？
2. 完整性：是否覆盖了主要方面？
3. 准确性：信息是否准确、有引用支撑？

## 输出格式
```json
{
  "passed": true/false,
  "score": 1-10,
  "feedback": "如果不通过，说明缺失了什么或需要改进什么"
}
```
"""
```

### 2. `agent/app/agents/supervisor.py`

```python
"""
Agent: Supervisor Agent
职责: 意图识别、任务拆解、子 Agent 调度、结果质量评估
绑定工具: 无（调度其他 Agent）
"""

import json
import logging
from typing import TypedDict, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

from app.prompts.supervisor import SUPERVISOR_SYSTEM_PROMPT, QUALITY_CHECK_PROMPT

logger = logging.getLogger(__name__)


class SupervisorState(TypedDict):
    messages: list              # 用户消息历史
    user_query: str             # 当前用户输入
    intent: str                 # 识别的意图
    topic: str                  # 研究主题
    research_plan: list         # 任务计划
    sub_results: dict           # 子 Agent 返回结果 {step: result}
    final_output: str           # 最终输出
    iteration: int              # 当前重试次数
    max_iterations: int         # 最大重试次数
    status: str                 # pending | planning | executing | checking | completed | failed
    events: list                # 流式事件列表，供 gRPC 层读取


def intent_recognition(state: SupervisorState) -> dict:
    """识别用户意图并生成研究计划。"""
    from app.agents.llm import get_llm

    llm = get_llm()
    messages = [
        SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
        HumanMessage(content=state["user_query"]),
    ]

    response = llm.invoke(messages)
    content = response.content

    # Parse JSON from response
    try:
        # Extract JSON block if wrapped in markdown
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        plan_data = json.loads(content.strip())
    except (json.JSONDecodeError, IndexError):
        logger.warning(f"Failed to parse plan JSON, using fallback. Response: {content[:200]}")
        plan_data = {
            "intent": "literature_review",
            "topic": state["user_query"],
            "plan": [
                {"step": 1, "agent": "search_agent", "task": state["user_query"], "params": {}},
                {"step": 2, "agent": "analysis_agent", "task": "分析检索到的论文", "depends_on": [1]},
                {"step": 3, "agent": "synthesis_agent", "task": "生成综合报告", "depends_on": [2]},
            ],
        }

    events = state.get("events", [])
    events.append({
        "type": "agent_status",
        "agent": "supervisor",
        "step": f"意图识别完成：{plan_data.get('intent', 'unknown')}",
    })

    return {
        "intent": plan_data.get("intent", "literature_review"),
        "topic": plan_data.get("topic", state["user_query"]),
        "research_plan": plan_data.get("plan", []),
        "status": "executing",
        "events": events,
    }


def dispatch_agents(state: SupervisorState) -> dict:
    """按计划依次调用子 Agent。

    当前为骨架实现，子 Agent 在任务 3.3-3.5 中实现后替换。
    """
    plan = state["research_plan"]
    sub_results = state.get("sub_results", {})
    events = state.get("events", [])

    for step_info in plan:
        step = step_info["step"]
        agent_name = step_info["agent"]
        task = step_info["task"]

        # Check dependencies
        depends_on = step_info.get("depends_on", [])
        for dep in depends_on:
            if dep not in sub_results:
                logger.warning(f"Step {step} depends on {dep} which has no result, skipping")

        events.append({
            "type": "agent_status",
            "agent": agent_name,
            "step": f"正在执行：{task}",
        })

        # Dispatch to sub-agent (placeholder - will be replaced in tasks 3.3-3.5)
        result = _dispatch_single_agent(agent_name, task, state, sub_results)
        sub_results[step] = result

    return {
        "sub_results": sub_results,
        "status": "checking",
        "events": events,
    }


def _dispatch_single_agent(agent_name: str, task: str, state: dict, prior_results: dict) -> str:
    """Dispatch to a single sub-agent. Placeholder for now."""
    # TODO: Replace with actual agent invocation in tasks 3.3-3.5
    if agent_name == "search_agent":
        return f"[Search Agent Mock] 检索到 15 篇关于「{state['topic']}」的论文"
    elif agent_name == "analysis_agent":
        return f"[Analysis Agent Mock] 已分析论文，提取了关键信息"
    elif agent_name == "synthesis_agent":
        return f"[Synthesis Agent Mock] 已生成综合报告"
    return f"[Unknown Agent: {agent_name}]"


def quality_check(state: SupervisorState) -> dict:
    """评估子 Agent 结果质量。"""
    from app.agents.llm import get_llm

    # Combine all sub-results
    combined = "\n\n".join(
        f"Step {k}: {v}" for k, v in sorted(state["sub_results"].items())
    )

    llm = get_llm()
    prompt = QUALITY_CHECK_PROMPT.format(
        user_query=state["user_query"],
        result=combined,
    )
    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        check_result = json.loads(content.strip())
    except (json.JSONDecodeError, IndexError):
        check_result = {"passed": True, "score": 7, "feedback": ""}

    events = state.get("events", [])

    if check_result.get("passed", True):
        events.append({
            "type": "agent_status",
            "agent": "supervisor",
            "step": f"质量检查通过 (评分: {check_result.get('score', '?')}/10)",
        })
        return {
            "final_output": combined,
            "status": "completed",
            "events": events,
        }
    else:
        events.append({
            "type": "agent_status",
            "agent": "supervisor",
            "step": f"质量不达标，重新规划 (反馈: {check_result.get('feedback', '')})",
        })
        return {
            "iteration": state["iteration"] + 1,
            "status": "executing",
            "events": events,
        }


def should_retry(state: SupervisorState) -> Literal["retry", "done"]:
    """判断是否需要重试。"""
    if state["status"] == "completed":
        return "done"
    if state["iteration"] >= state["max_iterations"]:
        return "done"
    return "retry"


def build_supervisor_graph() -> StateGraph:
    """构建 Supervisor Agent 的 LangGraph 状态机。

    流程：
    START → intent_recognition → dispatch_agents → quality_check
                                                       │
                                             ┌─────────┤
                                             ▼         ▼
                                          done → END  retry → dispatch_agents
    """
    graph = StateGraph(SupervisorState)

    graph.add_node("intent_recognition", intent_recognition)
    graph.add_node("dispatch_agents", dispatch_agents)
    graph.add_node("quality_check", quality_check)

    graph.set_entry_point("intent_recognition")
    graph.add_edge("intent_recognition", "dispatch_agents")
    graph.add_edge("dispatch_agents", "quality_check")
    graph.add_conditional_edges("quality_check", should_retry, {
        "retry": "dispatch_agents",
        "done": END,
    })

    return graph.compile()


# Pre-built graph instance
supervisor_graph = build_supervisor_graph()
```

### 3. `agent/app/agents/llm.py`

```python
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
    elif config.llm_provider == "zhipu":
        from langchain_community.chat_models import ChatZhipuAI
        return ChatZhipuAI(
            model=config.llm_model,
            api_key=config.llm_api_key,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {config.llm_provider}")
```

### 4. `agent/app/agents/__init__.py`

空文件。

### 5. `agent/app/prompts/__init__.py`

空文件。

### 6. 更新 `agent/app/grpc_server.py`

替换 `Chat` 方法，使用 Supervisor Agent：

```python
def Chat(self, request, context):
    """Handle chat request by invoking the Supervisor Agent graph."""
    session_id = request.session_id
    content = request.content
    logger.info(f"Chat request: session={session_id}, content={content[:50]}")

    # Build initial state
    initial_state = {
        "messages": [],
        "user_query": content,
        "intent": "",
        "topic": "",
        "research_plan": [],
        "sub_results": {},
        "final_output": "",
        "iteration": 0,
        "max_iterations": 2,
        "status": "pending",
        "events": [],
    }

    # Add history from context if available
    if request.context and request.context.history:
        initial_state["messages"] = [
            {"role": msg.role, "content": msg.content}
            for msg in request.context.history
        ]

    try:
        from app.agents.supervisor import supervisor_graph

        result = supervisor_graph.invoke(initial_state)

        # Yield all collected events
        for event in result.get("events", []):
            if event["type"] == "agent_status":
                yield agent_pb2.ChatEvent(
                    event_type=agent_pb2.EVENT_TYPE_AGENT_STATUS,
                    agent_name=event.get("agent", ""),
                    step_description=event.get("step", ""),
                )

        # Yield final output as tokens
        final_output = result.get("final_output", "处理完成，但未生成输出。")
        # Send in chunks for streaming effect
        chunk_size = 20
        for i in range(0, len(final_output), chunk_size):
            chunk = final_output[i:i + chunk_size]
            yield agent_pb2.ChatEvent(
                event_type=agent_pb2.EVENT_TYPE_TOKEN,
                content=chunk,
            )

        # Done event
        yield agent_pb2.ChatEvent(
            event_type=agent_pb2.EVENT_TYPE_DONE,
            content=final_output,
        )

    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        yield agent_pb2.ChatEvent(
            event_type=agent_pb2.EVENT_TYPE_ERROR,
            error_message=str(e),
        )
```

## 验收标准

### 1. 编译检查

```bash
cd agent
python -c "from app.agents.supervisor import supervisor_graph; print('OK')"
```

### 2. 单元测试

创建 `agent/tests/test_supervisor.py`：

```python
"""Test Supervisor Agent graph structure and intent recognition."""

import pytest
from app.agents.supervisor import build_supervisor_graph, SupervisorState


def test_graph_builds():
    """Graph should compile without errors."""
    graph = build_supervisor_graph()
    assert graph is not None


def test_initial_state_schema():
    """Verify SupervisorState has all required fields."""
    state = SupervisorState(
        messages=[],
        user_query="test",
        intent="",
        topic="",
        research_plan=[],
        sub_results={},
        final_output="",
        iteration=0,
        max_iterations=2,
        status="pending",
        events=[],
    )
    assert state["user_query"] == "test"
    assert state["max_iterations"] == 2
```

运行：
```bash
cd agent
python -m pytest tests/test_supervisor.py -v
```

### 3. 验收 Checklist

- [ ] `from app.agents.supervisor import supervisor_graph` 无报错
- [ ] Graph 包含 3 个节点：intent_recognition, dispatch_agents, quality_check
- [ ] 正确识别四种意图：literature_review, paper_reading, method_comparison, gap_analysis
- [ ] 生成结构化任务计划（JSON 格式，包含 step, agent, task, depends_on）
- [ ] 质量检查不通过时触发重新规划（最多重试 2 次）
- [ ] 每个步骤产生 agent_status 事件
- [ ] LLM 工厂支持 dashscope 和 zhipu 两种 provider
- [ ] gRPC Chat 方法正确调用 supervisor_graph 并流式返回事件
- [ ] 单元测试通过

## 提交

```bash
git add agent/
git commit -m "feat(agent): implement Supervisor Agent with LangGraph state machine

- Intent recognition (4 types: literature_review/paper_reading/method_comparison/gap_analysis)
- Task planning with structured JSON output
- Sub-agent dispatch (placeholder, to be replaced in tasks 3.3-3.5)
- Quality check with retry mechanism (max 2 retries)
- LLM factory supporting dashscope and zhipu providers
- Integrate supervisor graph into gRPC Chat handler"
```

## 注意事项

1. `_dispatch_single_agent` 是占位实现，任务 3.3-3.5 完成后替换为真实调用
2. LLM 调用需要有效的 API key，测试时可 mock 或设置环境变量
3. JSON 解析有 fallback 逻辑，LLM 输出格式不标准时不会崩溃
4. events 列表是收集式的（非实时流式），gRPC 层在 graph 执行完后统一发送
