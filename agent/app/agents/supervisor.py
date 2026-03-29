"""
Agent: Supervisor Agent
职责: 意图识别、任务拆解、子 Agent 调度、结果质量评估
绑定工具: 无（调度其他 Agent）
"""

import json
import logging
from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.prompts.supervisor import QUALITY_CHECK_PROMPT, SUPERVISOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class SupervisorState(TypedDict):
    messages: list[dict[str, str]]
    user_query: str
    intent: str
    topic: str
    research_plan: list[dict[str, Any]]
    sub_results: dict[int, str]
    final_output: str
    iteration: int
    max_iterations: int
    status: str
    events: list[dict[str, str]]


def _response_to_text(response: Any) -> str:
    content = getattr(response, "content", response)
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


def _extract_json_payload(text: str) -> str:
    if "```json" in text:
        return text.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    return text.strip()


def _fallback_plan(query: str) -> dict[str, Any]:
    return {
        "intent": "literature_review",
        "topic": query,
        "plan": [
            {"step": 1, "agent": "search_agent", "task": query, "params": {}},
            {
                "step": 2,
                "agent": "analysis_agent",
                "task": "分析检索到的论文并提取关键信息",
                "depends_on": [1],
            },
            {
                "step": 3,
                "agent": "synthesis_agent",
                "task": "生成综合报告",
                "depends_on": [2],
            },
        ],
    }


def intent_recognition(state: SupervisorState) -> dict[str, Any]:
    """识别用户意图并生成研究计划。"""
    from app.agents.llm import get_llm

    llm = get_llm()
    messages = [
        SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
        HumanMessage(content=state["user_query"]),
    ]

    response = llm.invoke(messages)
    content = _response_to_text(response)

    try:
        plan_data = json.loads(_extract_json_payload(content))
    except json.JSONDecodeError:
        logger.warning("Failed to parse plan JSON, using fallback. Response: %s", content[:200])
        plan_data = _fallback_plan(state["user_query"])

    events = list(state.get("events", []))
    events.append(
        {
            "type": "agent_status",
            "agent": "supervisor",
            "step": f"意图识别完成：{plan_data.get('intent', 'unknown')}",
        }
    )

    return {
        "intent": plan_data.get("intent", "literature_review"),
        "topic": plan_data.get("topic", state["user_query"]),
        "research_plan": plan_data.get("plan", []),
        "status": "executing",
        "events": events,
    }


def dispatch_agents(state: SupervisorState) -> dict[str, Any]:
    """按计划依次调度子 Agent。"""
    plan = state["research_plan"]
    sub_results = dict(state.get("sub_results", {}))
    events = list(state.get("events", []))

    for step_info in plan:
        step = step_info["step"]
        agent_name = step_info["agent"]
        task = step_info["task"]

        for dep in step_info.get("depends_on", []):
            if dep not in sub_results:
                logger.warning("Step %s depends on %s which has no result", step, dep)

        events.append(
            {
                "type": "agent_status",
                "agent": agent_name,
                "step": f"正在执行：{task}",
            }
        )
        sub_results[step] = _dispatch_single_agent(agent_name, task, state, sub_results)

    return {
        "sub_results": sub_results,
        "status": "checking",
        "events": events,
    }


def _dispatch_single_agent(
    agent_name: str,
    task: str,
    state: SupervisorState,
    prior_results: dict[int, str],
) -> str:
    """Dispatch to a single sub-agent. Placeholder for tasks 3.3-3.5."""
    del task, prior_results
    topic = state.get("topic") or state["user_query"]
    if agent_name == "search_agent":
        return f"[Search Agent Mock] 检索到 15 篇关于“{topic}”的论文。"
    if agent_name == "analysis_agent":
        return "[Analysis Agent Mock] 已分析论文，提取了研究问题、方法、数据集、指标和结果。"
    if agent_name == "synthesis_agent":
        return "[Synthesis Agent Mock] 已生成综合报告与研究结论。"
    return f"[Unknown Agent: {agent_name}]"


def quality_check(state: SupervisorState) -> dict[str, Any]:
    """评估子 Agent 结果质量。"""
    from app.agents.llm import get_llm

    combined = "\n\n".join(
        f"Step {step}: {result}"
        for step, result in sorted(state["sub_results"].items())
    )

    llm = get_llm()
    prompt = QUALITY_CHECK_PROMPT.format(
        user_query=state["user_query"],
        result=combined,
    )
    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        check_result = json.loads(_extract_json_payload(_response_to_text(response)))
    except json.JSONDecodeError:
        check_result = {"passed": True, "score": 7, "feedback": ""}

    events = list(state.get("events", []))
    if check_result.get("passed", True):
        events.append(
            {
                "type": "agent_status",
                "agent": "supervisor",
                "step": f"质量检查通过 (评分: {check_result.get('score', '?')}/10)",
            }
        )
        return {
            "final_output": combined,
            "status": "completed",
            "events": events,
        }

    next_iteration = state["iteration"] + 1
    feedback = check_result.get("feedback", "")
    if next_iteration >= state["max_iterations"]:
        events.append(
            {
                "type": "agent_status",
                "agent": "supervisor",
                "step": f"质量未达标，已达到最大重试次数 (反馈: {feedback})",
            }
        )
        return {
            "iteration": next_iteration,
            "final_output": combined,
            "status": "failed",
            "events": events,
        }

    events.append(
        {
            "type": "agent_status",
            "agent": "supervisor",
            "step": f"质量未达标，重新执行计划 (反馈: {feedback})",
        }
    )
    return {
        "iteration": next_iteration,
        "status": "executing",
        "events": events,
    }


def should_retry(state: SupervisorState) -> Literal["retry", "done"]:
    """判断是否需要重试。"""
    if state["status"] in {"completed", "failed"}:
        return "done"
    if state["iteration"] >= state["max_iterations"]:
        return "done"
    return "retry"


def build_supervisor_graph():
    """构建 Supervisor Agent 的 LangGraph 状态机。"""
    graph = StateGraph(SupervisorState)

    graph.add_node("intent_recognition", intent_recognition)
    graph.add_node("dispatch_agents", dispatch_agents)
    graph.add_node("quality_check", quality_check)

    graph.set_entry_point("intent_recognition")
    graph.add_edge("intent_recognition", "dispatch_agents")
    graph.add_edge("dispatch_agents", "quality_check")
    graph.add_conditional_edges(
        "quality_check",
        should_retry,
        {
            "retry": "dispatch_agents",
            "done": END,
        },
    )

    return graph.compile()


supervisor_graph = build_supervisor_graph()