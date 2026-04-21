"""Planner module for decomposing user queries into search-ready sub-questions."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage

from app.agents.llm import invoke_llm
from app.prompts.planner import PLANNER_PROMPT

logger = logging.getLogger(__name__)

_METHOD_TOKEN_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*\b")
_GENERIC_ENTITY_STOPWORDS = {
    "AI",
    "API",
    "CPU",
    "CV",
    "GPU",
    "JSON",
    "LLM",
    "ML",
    "NLP",
    "PDF",
    "URL",
}
_VALID_SUBQUESTION_TYPES = {"find_paper", "find_topic", "compare", "background"}


class SubQuestion(TypedDict):
    id: int
    question: str
    type: str
    entities: list[str]
    priority: int


class PlannerOutput(TypedDict):
    intent: str
    topic: str
    sub_questions: list[SubQuestion]
    search_year_from: int


class _PlannerLLMOutput(TypedDict, total=False):
    topic: str
    entities: list[str]
    sub_questions: list[dict[str, Any]]
    search_year_from: int


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


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().strip("\"'`“”‘’[](){}")


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        key = _normalize_key(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return _dedupe_strings([str(item) for item in value if _clean_text(item)])
    if isinstance(value, str):
        parts = re.split(r"[,\n;/，、]+", value)
        return _dedupe_strings(parts)
    return []


def _looks_like_method_name(token: str) -> bool:
    if not token:
        return False
    if token.upper() in _GENERIC_ENTITY_STOPWORDS:
        return False

    uppercase_count = sum(1 for char in token if char.isupper())
    has_digit = any(char.isdigit() for char in token)
    has_separator = "-" in token or "/" in token
    has_internal_upper = any(char.isupper() for char in token[1:])

    return has_digit or uppercase_count >= 2 or (has_separator and has_internal_upper) or has_internal_upper


def _extract_regex_entities(query: str) -> list[str]:
    entities: list[str] = []
    for token in _METHOD_TOKEN_PATTERN.findall(query):
        cleaned = _clean_text(token)
        if _looks_like_method_name(cleaned):
            entities.append(cleaned)
    return _dedupe_strings(entities)


def _extract_entities_from_llm_output(data: _PlannerLLMOutput | None) -> list[str]:
    if not data:
        return []

    entities = _coerce_string_list(data.get("entities"))
    for item in data.get("sub_questions", []):
        if isinstance(item, dict):
            entities.extend(_coerce_string_list(item.get("entities")))
    return _dedupe_strings(entities)


def _merge_entities(*entity_groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in entity_groups:
        merged.extend(group)
    return _dedupe_strings(merged)


def _infer_topic_from_query(user_query: str, intent: str, entities: list[str]) -> str:
    if intent == "method_comparison" and entities:
        return " vs ".join(entities)

    topic = user_query.strip()
    topic = re.sub(r"^(请帮我|请你|帮我|麻烦你|麻烦|我想|想要|需要)\s*", "", topic)
    topic = re.sub(
        r"^(对比|比较|调研|综述|梳理|研究|分析|总结|介绍|了解|评述|review|survey)\s*",
        "",
        topic,
        flags=re.IGNORECASE,
    )
    topic = re.sub(
        r"(领域|方向|方面)?(?:的)?"
        r"(优缺点|区别|差异|异同|最新进展|研究进展|进展|benchmark evaluation|benchmark|基准评测|评测|"
        r"application|applications|应用场景|应用|局限性|limitations|挑战|challenges|"
        r"future directions|未来方向|open problems|开放问题).*$",
        "",
        topic,
        flags=re.IGNORECASE,
    )
    topic = topic.strip(" ，。；：:,.!?！？、")

    if entities and (not topic or len(topic) >= len(user_query)):
        return entities[0]
    return topic or (entities[0] if entities else user_query.strip())


def _coerce_non_negative_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, number)


def _build_sub_question(
    index: int,
    question: str,
    question_type: str,
    entities: list[str],
    priority: int,
) -> SubQuestion:
    normalized_type = question_type if question_type in _VALID_SUBQUESTION_TYPES else "find_topic"
    normalized_priority = priority if priority in {1, 2, 3} else 2
    return {
        "id": index,
        "question": question.strip(),
        "type": normalized_type,
        "entities": _dedupe_strings(entities),
        "priority": normalized_priority,
    }


def _fallback_subquestion_type(intent: str) -> str:
    if intent == "method_comparison":
        return "compare"
    if intent == "literature_review":
        return "background"
    return "find_topic"


def _fallback_output(
    user_query: str,
    intent: str,
    topic: str,
    entities: list[str],
    search_year_from: int,
) -> PlannerOutput:
    return {
        "intent": intent,
        "topic": topic or user_query.strip(),
        "sub_questions": [
            _build_sub_question(
                1,
                user_query,
                _fallback_subquestion_type(intent),
                entities or _extract_regex_entities(user_query),
                1,
            )
        ],
        "search_year_from": max(0, search_year_from),
    }


def _invoke_planner_llm(
    user_query: str,
    intent: str,
    attachment_ids: list[str],
    regex_entities: list[str],
    current_year: int,
) -> tuple[_PlannerLLMOutput | None, bool]:
    prompt = PLANNER_PROMPT.format(
        user_query=user_query,
        intent=intent,
        attachment_ids=", ".join(attachment_ids) if attachment_ids else "none",
        regex_entities=", ".join(regex_entities) if regex_entities else "none",
        current_year=current_year,
    )

    try:
        response = invoke_llm(
            [HumanMessage(content=prompt)],
            source=f"planner.{intent}",
        )
    except Exception as exc:
        logger.warning("Planner LLM invocation failed: %s", exc)
        return None, False

    content = _response_to_text(response)
    try:
        payload = json.loads(_extract_json_payload(content))
    except json.JSONDecodeError:
        logger.warning("Failed to parse planner JSON, using fallback. Response: %s", content[:200])
        return None, True

    if not isinstance(payload, dict):
        logger.warning("Planner JSON payload is not an object, using fallback.")
        return None, True

    return payload, False


def _normalize_llm_sub_questions(raw_sub_questions: Any) -> list[SubQuestion]:
    if not isinstance(raw_sub_questions, list):
        return []

    normalized: list[SubQuestion] = []
    for item in raw_sub_questions:
        if not isinstance(item, dict):
            continue
        question = _clean_text(item.get("question"))
        if not question:
            continue
        priority = _coerce_non_negative_int(item.get("priority"), 2)
        normalized.append(
            _build_sub_question(
                len(normalized) + 1,
                question,
                _clean_text(item.get("type")) or "find_topic",
                _coerce_string_list(item.get("entities")),
                priority,
            )
        )
    return normalized


def _build_method_comparison_questions(entities: list[str]) -> list[SubQuestion]:
    sub_questions: list[SubQuestion] = []
    for entity in entities:
        sub_questions.append(
            _build_sub_question(
                len(sub_questions) + 1,
                f"{entity} paper method",
                "find_paper",
                [entity],
                1,
            )
        )

    if len(entities) >= 2:
        sub_questions.append(
            _build_sub_question(
                len(sub_questions) + 1,
                f"comparison of {' '.join(entities)}",
                "compare",
                entities,
                2,
            )
        )

    return sub_questions


def _build_literature_review_questions(topic: str, current_year: int) -> tuple[list[SubQuestion], int]:
    search_year_from = max(0, current_year - 3)
    recent_years = f"{current_year - 1} {current_year}"
    return (
        [
            _build_sub_question(1, f"{topic} survey overview", "background", [topic], 1),
            _build_sub_question(2, f"{topic} recent advances {recent_years}", "find_topic", [topic], 1),
            _build_sub_question(3, f"{topic} benchmark evaluation", "find_topic", [topic], 2),
            _build_sub_question(4, f"{topic} application", "find_topic", [topic], 3),
        ],
        search_year_from,
    )


def _build_gap_analysis_questions(topic: str) -> list[SubQuestion]:
    return [
        _build_sub_question(1, f"{topic} limitations challenges", "find_topic", [topic], 1),
        _build_sub_question(2, f"{topic} future directions open problems", "find_topic", [topic], 2),
    ]


def run_planner(
    user_query: str,
    intent: str,
    attachment_ids: list[str] | None = None,
) -> PlannerOutput:
    """将用户查询拆解为子问题列表。"""
    attachment_ids = attachment_ids or []
    current_year = datetime.now(timezone.utc).year

    if intent == "paper_reading":
        return {
            "intent": intent,
            "topic": user_query.strip(),
            "sub_questions": [],
            "search_year_from": 0,
        }

    regex_entities = _extract_regex_entities(user_query)
    llm_output, parse_failed = _invoke_planner_llm(
        user_query=user_query,
        intent=intent,
        attachment_ids=attachment_ids,
        regex_entities=regex_entities,
        current_year=current_year,
    )

    heuristic_topic = _infer_topic_from_query(user_query, intent, regex_entities)
    if parse_failed:
        fallback_year = max(0, current_year - 3) if intent == "literature_review" else 0
        return _fallback_output(user_query, intent, heuristic_topic, regex_entities, fallback_year)

    llm_entities = _extract_entities_from_llm_output(llm_output)
    entities = _merge_entities(regex_entities, llm_entities)
    topic = _clean_text((llm_output or {}).get("topic")) or _infer_topic_from_query(user_query, intent, entities)

    if intent == "method_comparison":
        if not entities:
            return _fallback_output(user_query, intent, topic, entities, 0)
        return {
            "intent": intent,
            "topic": topic,
            "sub_questions": _build_method_comparison_questions(entities),
            "search_year_from": 0,
        }

    if intent == "literature_review":
        sub_questions, default_year_from = _build_literature_review_questions(topic, current_year)
        search_year_from = _coerce_non_negative_int((llm_output or {}).get("search_year_from"), default_year_from)
        search_year_from = max(default_year_from, search_year_from)
        return {
            "intent": intent,
            "topic": topic,
            "sub_questions": sub_questions,
            "search_year_from": search_year_from,
        }

    if intent == "gap_analysis":
        return {
            "intent": intent,
            "topic": topic,
            "sub_questions": _build_gap_analysis_questions(topic),
            "search_year_from": _coerce_non_negative_int((llm_output or {}).get("search_year_from"), 0),
        }

    normalized_sub_questions = _normalize_llm_sub_questions((llm_output or {}).get("sub_questions"))
    if normalized_sub_questions:
        return {
            "intent": intent,
            "topic": topic,
            "sub_questions": normalized_sub_questions,
            "search_year_from": _coerce_non_negative_int((llm_output or {}).get("search_year_from"), 0),
        }

    return _fallback_output(user_query, intent, topic, entities, 0)
