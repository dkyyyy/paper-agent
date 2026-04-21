"""Supervisor agent for intent detection, orchestration, and quality control."""

import json
import logging
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.agents.llm import get_current_token_budget, invoke_llm
from app.config import config
from app.prompts.supervisor import QUALITY_CHECK_PROMPT, SUPERVISOR_SYSTEM_PROMPT
from app.services.token_budget import compress_messages

logger = logging.getLogger(__name__)

_VALID_INTENTS = {
    "chitchat",
    "literature_review",
    "paper_reading",
    "method_comparison",
    "gap_analysis",
    "survey_writing",
    "paper_qa",
}


class SupervisorState(TypedDict):
    messages: list[dict[str, str]]
    session_id: str
    attachment_ids: list[str]
    user_query: str
    intent: str
    topic: str
    planner_topic: str
    sub_questions: list[dict[str, Any]]
    research_plan: list[dict[str, Any]]
    sub_results: dict[int, str]
    search_results: list[dict[str, Any]]
    analysis_results: list[dict[str, Any]]
    synthesis_output: str
    final_output: str
    error_message: str
    quality_feedback: str
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


def _default_plan(state: SupervisorState, intent: str) -> list[dict[str, Any]]:
    if intent in {"paper_reading", "paper_qa"} and state.get("attachment_ids"):
        return [{"step": 1, "agent": "analysis_agent", "task": "Analyze uploaded papers", "params": {}}]

    if intent == "method_comparison":
        return [
            {"step": 1, "agent": "search_agent", "task": state["user_query"], "params": {}},
            {"step": 2, "agent": "analysis_agent", "task": "Analyze candidate papers", "depends_on": [1]},
            {"step": 3, "agent": "synthesis_agent", "task": "Generate comparison report", "depends_on": [2]},
        ]

    if intent == "gap_analysis":
        return [
            {"step": 1, "agent": "search_agent", "task": state["user_query"], "params": {}},
            {"step": 2, "agent": "analysis_agent", "task": "Analyze candidate papers", "depends_on": [1]},
            {"step": 3, "agent": "synthesis_agent", "task": "Identify research gaps", "depends_on": [2]},
        ]

    if intent == "survey_writing":
        return [
            {"step": 1, "agent": "search_agent", "task": state["user_query"], "params": {}},
            {"step": 2, "agent": "analysis_agent", "task": "Analyze candidate papers", "depends_on": [1]},
            {"step": 3, "agent": "synthesis_agent", "task": "Generate survey report", "depends_on": [2]},
        ]

    if intent == "paper_qa":
        return [
            {"step": 1, "agent": "search_agent", "task": state["user_query"], "params": {}},
            {"step": 2, "agent": "analysis_agent", "task": "Analyze candidate papers", "depends_on": [1]},
            {"step": 3, "agent": "synthesis_agent", "task": "Answer the paper question", "depends_on": [2]},
        ]

    return [
        {"step": 1, "agent": "search_agent", "task": state["user_query"], "params": {}},
        {"step": 2, "agent": "analysis_agent", "task": "Analyze candidate papers", "depends_on": [1]},
        {"step": 3, "agent": "synthesis_agent", "task": "Generate literature review", "depends_on": [2]},
    ]


def _fallback_plan(state: SupervisorState) -> dict[str, Any]:
    intent = "paper_reading" if state.get("attachment_ids") else "literature_review"
    return {
        "intent": intent,
        "topic": state["user_query"],
        "plan": _default_plan(state, intent),
    }


def _normalize_plan(state: SupervisorState, plan_data: dict[str, Any]) -> dict[str, Any]:
    fallback_intent = "paper_reading" if state.get("attachment_ids") else "literature_review"
    intent = plan_data.get("intent") or fallback_intent
    if intent not in _VALID_INTENTS:
        intent = fallback_intent

    plan = plan_data.get("plan") or _default_plan(state, intent)
    topic = plan_data.get("topic") or state["user_query"]

    if state.get("attachment_ids") and intent in {"paper_reading", "paper_qa"}:
        plan = _default_plan(state, intent)

    return {"intent": intent, "topic": topic, "plan": plan}


def _dict_to_message(message: dict[str, str]):
    role = message.get("role", "user")
    content = message.get("content", "")
    if role == "system":
        return SystemMessage(content=content)
    if role == "assistant":
        return AIMessage(content=content)
    return HumanMessage(content=content)


def _build_supervisor_messages(state: SupervisorState) -> list[Any]:
    history = list(state.get("messages", []))
    if not history or history[-1].get("role") != "user" or history[-1].get("content") != state["user_query"]:
        history.append({"role": "user", "content": state["user_query"]})

    budget = get_current_token_budget()
    if budget and budget.should_compress and len(history) > config.token_keep_recent_turns * 2:
        compressed = compress_messages(
            history,
            SUPERVISOR_SYSTEM_PROMPT,
            keep_recent=config.token_keep_recent_turns,
        )
        return [_dict_to_message(message) for message in compressed]

    return [SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT)] + [_dict_to_message(message) for message in history]


def _format_analysis_report(analyzed_papers: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for paper in analyzed_papers:
        info = paper.get("extracted_info", {})
        abstract = (paper.get("abstract") or "").strip()
        summary = (paper.get("summary") or "").strip()
        sections.append(
            "\n".join(
                filter(None, [
                    f"### {paper.get('title', 'Untitled')}",
                    f"- paper_id: {paper.get('paper_id', 'N/A')}",
                    f"- year: {paper.get('year', 'N/A')}",
                    f"- authors: {', '.join(paper.get('authors', [])[:3]) or 'N/A'}",
                    f"- Analysis source: {paper.get('analysis_source', 'unknown')}",
                    f"- Research question: {info.get('research_question', 'N/A')}",
                    f"- Method: {info.get('method', 'N/A')}",
                    f"- Dataset: {info.get('dataset', [])}",
                    f"- Metrics: {info.get('metrics', {})}",
                    f"- Results: {info.get('results', 'N/A')}",
                    f"- Abstract: {abstract}" if abstract else None,
                    summary if summary else None,
                ])
            )
        )
    return "\n\n".join(sections)


def intent_recognition(state: SupervisorState) -> dict[str, Any]:
    """Recognize user intent, build a task plan, and prepare planner output."""
    response = invoke_llm(
        _build_supervisor_messages(state),
        source="supervisor.intent_recognition",
    )
    content = _response_to_text(response)

    try:
        plan_data = json.loads(_extract_json_payload(content))
    except json.JSONDecodeError:
        logger.warning("Failed to parse plan JSON, using fallback. Response: %s", content[:200])
        plan_data = _fallback_plan(state)

    normalized = _normalize_plan(state, plan_data)
    events = list(state.get("events", []))
    events.append(
        {
            "type": "agent_status",
            "agent": "supervisor",
            "step": f"Intent recognized: {normalized['intent']}",
        }
    )

    if normalized["intent"] == "chitchat":
        chitchat_response = invoke_llm(
            [
                SystemMessage(content="你是一个友好的学术研究助手。用户发送了一条日常对话消息，请自然地回复。如果用户问你能做什么，介绍你在文献检索、论文分析、方法对比、Research Gap 发现、综述写作、论文问答方面的能力。"),
                HumanMessage(content=state["user_query"]),
            ],
            source="supervisor.chitchat",
        )
        return {
            "intent": "chitchat",
            "topic": state["user_query"],
            "planner_topic": "",
            "sub_questions": [],
            "research_plan": [],
            "final_output": _response_to_text(chitchat_response),
            "status": "completed",
            "events": events,
        }

    planner_topic = normalized["topic"]
    sub_questions: list[dict[str, Any]] = []
    try:
        from app.agents.planner import run_planner

        planner_output = run_planner(
            user_query=state["user_query"],
            intent=normalized["intent"],
            attachment_ids=state.get("attachment_ids", []),
        )
        planner_topic = planner_output.get("topic") or planner_topic
        sub_questions = list(planner_output.get("sub_questions", []))
        events.append(
            {
                "type": "agent_status",
                "agent": "planner",
                "step": f"Planner generated {len(sub_questions)} sub-questions for topic: {planner_topic}",
            }
        )
    except Exception as exc:
        logger.warning("Planner failed, continuing with fallback topic only: %s", exc, exc_info=True)
        events.append(
            {
                "type": "agent_status",
                "agent": "planner",
                "step": f"Planner failed, continuing without sub-questions: {exc}",
            }
        )

    return {
        "intent": normalized["intent"],
        "topic": normalized["topic"],
        "planner_topic": planner_topic,
        "sub_questions": sub_questions,
        "research_plan": normalized["plan"],
        "status": "executing",
        "events": events,
    }


def dispatch_agents(state: SupervisorState) -> dict[str, Any]:
    """Dispatch each planned sub-agent in order."""
    plan = state["research_plan"]
    sub_results = dict(state.get("sub_results", {}))
    search_results = list(state.get("search_results", []))
    analysis_results = list(state.get("analysis_results", []))
    synthesis_output = state.get("synthesis_output", "")
    events = list(state.get("events", []))

    for step_info in plan:
        step = step_info["step"]
        agent_name = step_info["agent"]
        task = step_info.get("task", "")

        for dependency in step_info.get("depends_on", []):
            if dependency not in sub_results:
                logger.warning("Step %s depends on %s which has no result", step, dependency)

        events.append(
            {
                "type": "agent_status",
                "agent": agent_name,
                "step": f"Dispatching: {task or agent_name}",
            }
        )

        current_state: SupervisorState = {
            **state,
            "sub_results": sub_results,
            "search_results": search_results,
            "analysis_results": analysis_results,
            "synthesis_output": synthesis_output,
            "events": events,
        }

        try:
            result_text, updates, child_events = _dispatch_single_agent(agent_name, task, current_state)
            sub_results[step] = result_text
            search_results = updates.get("search_results", search_results)
            analysis_results = updates.get("analysis_results", analysis_results)
            synthesis_output = updates.get("synthesis_output", synthesis_output)
            events.extend(child_events)
        except Exception as exc:
            logger.error("Agent %s failed: %s", agent_name, exc, exc_info=True)
            events.append(
                {
                    "type": "agent_status",
                    "agent": agent_name,
                    "step": f"Execution failed: {exc}",
                }
            )
            return {
                "sub_results": sub_results,
                "search_results": search_results,
                "analysis_results": analysis_results,
                "synthesis_output": synthesis_output,
                "status": "failed",
                "error_message": f"{agent_name} failed: {exc}",
                "events": events,
            }

    return {
        "sub_results": sub_results,
        "search_results": search_results,
        "analysis_results": analysis_results,
        "synthesis_output": synthesis_output,
        "status": "checking",
        "events": events,
    }


def _dispatch_single_agent(
    agent_name: str,
    task: str,
    state: SupervisorState,
) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
    topic = state.get("planner_topic") or state.get("topic") or state["user_query"]

    if agent_name == "search_agent":
        from app.agents.search_agent import run_search

        sub_questions = state.get("sub_questions") or []
        feedback = state.get("quality_feedback", "")
        search_year_from = 0

        # 有子问题时，对每个子问题分别搜索再合并去重
        if sub_questions:
            from app.agents.planner import PlannerOutput
            # 取 planner 存的 search_year_from（存在 sub_questions 第一个的 parent 里，或从 state 取）
            # 简单起见直接从 planner_output 重新取，或默认 current_year-3
            from datetime import datetime, timezone
            search_year_from = max(0, datetime.now(timezone.utc).year - 3)

        all_papers: list[dict[str, Any]] = []
        all_events: list[dict[str, str]] = []
        seen_ids: set[str] = set()

        if sub_questions:
            find_questions = [q for q in sub_questions if q.get("type") in {"find_paper", "find_topic", "background"}]
            queries_to_search = find_questions or sub_questions
            for sq in queries_to_search:
                q_text = sq.get("question", "").strip()
                if not q_text:
                    continue
                result = run_search(
                    query=q_text,
                    target_count=8,
                    year_from=search_year_from if sq.get("type") != "find_paper" else 0,
                    feedback=feedback,
                )
                for paper in result.get("papers", []):
                    pid = paper.get("paper_id") or paper.get("title", "")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        all_papers.append(paper)
                all_events.extend(result.get("events", []))
        else:
            # 没有子问题时退回到单次搜索
            result = run_search(
                query=task or topic,
                target_count=15,
                feedback=feedback,
            )
            all_papers = result.get("papers", [])
            all_events = result.get("events", [])

        papers = all_papers
        summary = "\n".join(
            [f"Search returned {len(papers)} papers."]
            + [f"- {paper.get('title', 'Unknown')} ({paper.get('year', 'n/a')})" for paper in papers[:10]]
        )
        return summary, {"search_results": papers}, all_events

    if agent_name == "analysis_agent":
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from app.agents.analysis_agent import run_analysis
        from app.services.paper_store import get_paper_metadata, get_paper_text

        analyzed_papers: list[dict[str, Any]] = []
        child_events: list[dict[str, str]] = []

        if state.get("attachment_ids"):
            for paper_id in state["attachment_ids"]:
                metadata = get_paper_metadata(paper_id)
                if not metadata:
                    raise RuntimeError(f"Uploaded paper not found: {paper_id}")
                text = get_paper_text(paper_id)
                if not text:
                    raise RuntimeError(f"Uploaded paper text is unavailable: {paper_id}")
                result = run_analysis(
                    paper_id=paper_id,
                    paper_title=metadata.get("title", paper_id),
                    paper_content=text,
                    persist_to_vectordb=True,
                )
                child_events.extend(result.get("events", []))
                if result.get("index_error"):
                    raise RuntimeError(result["index_error"])
                analyzed_papers.append(
                    {
                        **metadata,
                        "analysis_source": "full_text",
                        "extracted_info": result.get("extracted_info", {}),
                        "summary": result.get("summary", ""),
                        "indexed": result.get("indexed", False),
                    }
                )
        else:
            papers = state.get("search_results") or []
            if not papers:
                raise RuntimeError(
                    "文献检索未返回结果。可能原因：\n"
                    "1. ArXiv/Semantic Scholar API 访问失败（网络问题或被限流）\n"
                    "2. 搜索关键词过于宽泛或过于具体\n"
                    "建议：稍后重试，或尝试更换搜索关键词"
                )
            candidate_papers = [
                p for p in papers[: config.max_analysis_papers]
                if (p.get("abstract") or "").strip()
            ]
            results_map: dict[str, Any] = {}
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_paper = {
                    executor.submit(
                        run_analysis,
                        paper_id=p.get("paper_id", ""),
                        paper_title=p.get("title", "Untitled"),
                        paper_content=(p.get("abstract") or "").strip(),
                        persist_to_vectordb=False,
                    ): p
                    for p in candidate_papers
                }
                for future in as_completed(future_to_paper, timeout=120):
                    paper = future_to_paper[future]
                    try:
                        result = future.result()
                        results_map[paper.get("paper_id", paper.get("title", ""))] = (paper, result)
                    except Exception as exc:
                        logger.warning("Paper analysis failed for '%s': %s", paper.get("title"), exc)
            # 按原始顺序组装，保持结果稳定
            for p in candidate_papers:
                key = p.get("paper_id", p.get("title", ""))
                if key not in results_map:
                    continue
                _, result = results_map[key]
                child_events.extend(result.get("events", []))
                analyzed_papers.append(
                    {
                        **p,
                        "analysis_source": "abstract",
                        "extracted_info": result.get("extracted_info", {}),
                        "summary": result.get("summary", ""),
                        "indexed": result.get("indexed", False),
                    }
                )

        if not analyzed_papers:
            raise RuntimeError("Analysis produced no usable papers")

        return _format_analysis_report(analyzed_papers), {"analysis_results": analyzed_papers}, child_events

    if agent_name == "synthesis_agent":
        from app.agents.synthesis_agent import run_synthesis

        papers = state.get("analysis_results") or []
        if not papers:
            raise RuntimeError("No analyzed papers available for synthesis")

        intent = state.get("intent", "literature_review")
        task_type = {
            "literature_review": "survey",
            "survey_writing": "survey",
            "method_comparison": "comparison",
            "gap_analysis": "gap_analysis",
            "paper_qa": "paper_qa",
        }.get(intent, "full")

        result = run_synthesis(
            papers=papers,
            topic=topic,
            task_type=task_type,
            user_query=state.get("user_query", ""),
            paper_ids=state.get("attachment_ids") or [],
        )
        report = result.get("output", "")
        if not report:
            raise RuntimeError("Synthesis agent returned an empty report")
        return report, {"synthesis_output": report}, result.get("events", [])

    raise RuntimeError(f"Unknown agent: {agent_name}")


def run_comparison_node(state: SupervisorState) -> dict[str, Any]:
    """Run the dedicated method-comparison agent and terminate the workflow."""
    from app.agents.comparison_agent import run_comparison

    result = run_comparison(
        user_query=state["user_query"],
        sub_questions=state.get("sub_questions", []),
        session_id=state.get("session_id", ""),
    )
    return {
        "final_output": result["output"],
        "search_results": result["papers"],
        "status": "completed",
        "events": list(state.get("events", [])) + list(result.get("events", [])),
    }


def _rule_check(state: SupervisorState, candidate_output: str) -> str | None:
    """返回 None 表示通过，返回字符串表示失败原因。"""
    papers = state.get("analysis_results", [])
    if len(papers) < 2:
        return f"论文数量不足（{len(papers)} 篇，要求 ≥2）"
    if len(candidate_output) < 300:
        return f"输出过短（{len(candidate_output)} 字符，要求 ≥300）"
    cited = sum(1 for p in papers[:5] if (p.get("title") or "") in candidate_output)
    if cited == 0:
        return "输出中未引用任何论文标题"
    return None


def quality_check(state: SupervisorState) -> dict[str, Any]:
    """Evaluate final result quality or terminate on prior failure."""
    events = list(state.get("events", []))
    if state.get("status") == "failed":
        return {
            "final_output": "",
            "status": "failed",
            "error_message": state.get("error_message", "Unknown failure"),
            "events": events,
        }

    combined = "\n\n".join(
        f"Step {step}: {result}"
        for step, result in sorted(state["sub_results"].items())
    )
    candidate_output = state.get("synthesis_output") or combined

    # 规则前置检查，避免每次都耗费 Token
    rule_failure = _rule_check(state, candidate_output)
    if rule_failure is not None:
        next_iteration = state["iteration"] + 1
        events.append(
            {
                "type": "agent_status",
                "agent": "supervisor",
                "step": f"Rule check failed: {rule_failure}",
            }
        )
        if next_iteration >= state["max_iterations"]:
            return {
                "iteration": next_iteration,
                "final_output": candidate_output,
                "status": "failed",
                "error_message": rule_failure,
                "events": events,
            }
        return {
            "iteration": next_iteration,
            "quality_feedback": rule_failure,
            "status": "executing",
            "search_results": [],
            "analysis_results": [],
            "synthesis_output": "",
            "sub_results": {},
            "events": events,
        }

    from datetime import datetime, timezone
    prompt = QUALITY_CHECK_PROMPT.format(
        current_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        user_query=state["user_query"],
        result=candidate_output,
    )
    response = invoke_llm(
        [HumanMessage(content=prompt)],
        source="supervisor.quality_check",
    )

    try:
        check_result = json.loads(_extract_json_payload(_response_to_text(response)))
    except json.JSONDecodeError:
        check_result = {"passed": True, "score": 7, "feedback": ""}

    if check_result.get("passed", True):
        events.append(
            {
                "type": "agent_status",
                "agent": "supervisor",
                "step": f"Quality check passed ({check_result.get('score', '?')}/10)",
            }
        )
        return {
            "final_output": candidate_output,
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
                "step": f"Quality check failed and retries were exhausted: {feedback}",
            }
        )
        return {
            "iteration": next_iteration,
            "final_output": candidate_output,
            "status": "failed",
            "error_message": feedback or "Quality check failed",
            "events": events,
        }

    events.append(
        {
            "type": "agent_status",
            "agent": "supervisor",
            "step": f"Quality check requested a retry: {feedback}",
        }
    )
    return {
        "iteration": next_iteration,
        "quality_feedback": feedback,
        "status": "executing",
        "search_results": [],
        "analysis_results": [],
        "synthesis_output": "",
        "sub_results": {},
        "events": events,
    }


def should_retry(state: SupervisorState) -> Literal["retry", "done"]:
    """Decide whether the workflow should retry."""
    if state["status"] in {"completed", "failed"}:
        return "done"
    if state["iteration"] >= state["max_iterations"]:
        return "done"
    return "retry"


def after_intent(state: SupervisorState) -> Literal["dispatch_agents", "comparison", "done"]:
    """Choose the next node after intent recognition."""
    intent = state.get("intent")
    if intent == "chitchat":
        return "done"
    if intent == "method_comparison":
        return "comparison"
    return "dispatch_agents"


def build_supervisor_graph():
    """Build the supervisor agent LangGraph state machine."""
    graph = StateGraph(SupervisorState)
    graph.add_node("intent_recognition", intent_recognition)
    graph.add_node("run_comparison", run_comparison_node)
    graph.add_node("dispatch_agents", dispatch_agents)
    graph.add_node("quality_check", quality_check)

    graph.set_entry_point("intent_recognition")
    graph.add_conditional_edges(
        "intent_recognition",
        after_intent,
        {
            "comparison": "run_comparison",
            "dispatch_agents": "dispatch_agents",
            "done": END,
        },
    )
    graph.add_edge("run_comparison", END)
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
