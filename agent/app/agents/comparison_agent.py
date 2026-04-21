"""Dedicated agent for method comparison workflows."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage

from app.agents.analysis_agent import run_analysis
from app.agents.llm import invoke_llm
from app.agents.search_agent import run_search
from app.prompts.comparison import COMPARISON_PROMPT

logger = logging.getLogger(__name__)

_DIMENSIONS = ("检索策略", "是否需要微调", "计算开销", "幻觉抑制机制", "局限性")


class ComparisonResult(TypedDict):
    output: str
    papers: list[dict[str, Any]]
    coverage: dict[int, bool]
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


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _append_unique(target: list[Any], value: Any) -> None:
    if value not in target:
        target.append(value)


def _paper_key(paper: dict[str, Any]) -> str:
    paper_id = _clean_text(paper.get("paper_id"))
    if paper_id:
        return paper_id
    title_key = _normalize_key(paper.get("title"))
    return f"title:{title_key}" if title_key else ""


def _dedupe_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for paper in papers:
        key = _paper_key(paper)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(paper)
    return deduped


def _paper_matches_entities(paper: dict[str, Any], entities: list[str]) -> bool:
    if not entities:
        return False
    title = _normalize_key(paper.get("title"))
    abstract = _normalize_key(paper.get("abstract"))
    for entity in entities:
        entity_key = _normalize_key(entity)
        if entity_key and (entity_key in title or entity_key in abstract):
            return True
    return False


def _paper_title_matches_entities(paper: dict[str, Any], entities: list[str]) -> bool:
    if not entities:
        return False
    title = _normalize_key(paper.get("title"))
    for entity in entities:
        entity_key = _normalize_key(entity)
        if entity_key and entity_key in title:
            return True
    return False


def _is_reasonable_year(year: int) -> bool:
    current_year = datetime.now(timezone.utc).year
    return 1990 <= year <= current_year + 1


def _is_valid_paper(paper: dict[str, Any]) -> bool:
    return bool(_clean_text(paper.get("paper_id"))) and bool(_clean_text(paper.get("abstract"))) and _is_reasonable_year(_safe_int(paper.get("year")))


def _subquestion_id(sub_question: dict[str, Any], fallback_id: int) -> int:
    return _safe_int(sub_question.get("id"), fallback_id)


def _subquestion_entities(sub_question: dict[str, Any]) -> list[str]:
    raw_entities = sub_question.get("entities") or []
    if isinstance(raw_entities, list):
        return [_clean_text(entity) for entity in raw_entities if _clean_text(entity)]
    if isinstance(raw_entities, str):
        return [_clean_text(raw_entities)] if _clean_text(raw_entities) else []
    return []


def _method_name(sub_question: dict[str, Any]) -> str:
    entities = _subquestion_entities(sub_question)
    if entities:
        return entities[0]

    question = _clean_text(sub_question.get("question"))
    question = re.sub(r"\b(?:paper|method|arxiv|comparison|compare|of)\b", "", question, flags=re.IGNORECASE)
    question = re.sub(r"\s+", " ", question).strip(" -_:,")
    return question or f"subquestion-{_subquestion_id(sub_question, 0)}"


def _candidate_sort_key(paper: dict[str, Any], entities: list[str]) -> tuple[int, int, int, int, int]:
    year = _safe_int(paper.get("year"), 9999) or 9999
    citation_count = _safe_int(paper.get("citation_count"), 0)
    return (
        0 if _paper_title_matches_entities(paper, entities) else 1,
        0 if _paper_matches_entities(paper, entities) else 1,
        0 if _is_valid_paper(paper) else 1,
        year,
        -citation_count,
    )


def _select_best_candidate(papers: list[dict[str, Any]], entities: list[str]) -> dict[str, Any] | None:
    if not papers:
        return None
    return sorted(papers, key=lambda paper: _candidate_sort_key(paper, entities))[0]


def _select_primary_paper(papers: list[dict[str, Any]], entities: list[str]) -> dict[str, Any] | None:
    ranked = sorted(papers, key=lambda paper: _candidate_sort_key(paper, entities))
    for paper in ranked:
        if _is_valid_paper(paper) and _paper_matches_entities(paper, entities):
            return paper
    return None


def _prioritize_paper(papers: list[dict[str, Any]], priority_paper: dict[str, Any] | None, limit: int) -> list[dict[str, Any]]:
    deduped = _dedupe_papers(papers)
    if not priority_paper:
        return deduped[:limit]

    priority_key = _paper_key(priority_paper)
    ordered: list[dict[str, Any]] = []
    for paper in deduped:
        if _paper_key(paper) == priority_key:
            ordered.insert(0, paper)
        else:
            ordered.append(paper)
    return ordered[:limit]


def _render_scalar(value: Any) -> str:
    if value is None:
        return "原论文未明确说明"
    if isinstance(value, dict):
        if not value:
            return "原论文未明确说明"
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        cleaned = [_clean_text(item) for item in value if _clean_text(item)]
        return ", ".join(cleaned) if cleaned else "原论文未明确说明"
    text = _clean_text(value)
    if not text or text.lower() == "extraction failed":
        return "原论文未明确说明"
    return text


def _seed_core_idea(paper: dict[str, Any], covered: bool) -> str:
    info = paper.get("extracted_info") or {}
    method = _render_scalar(info.get("method"))
    if method != "原论文未明确说明":
        return method
    return "待根据原论文摘要归纳" if covered else "原论文未明确说明"


def _seed_use_case(paper: dict[str, Any], covered: bool) -> str:
    info = paper.get("extracted_info") or {}
    research_question = _render_scalar(info.get("research_question"))
    if research_question != "原论文未明确说明":
        return research_question
    return "待根据原论文摘要归纳" if covered else "原论文未明确说明"


def _escape_table_cell(value: Any) -> str:
    return _render_scalar(value).replace("\n", " ").replace("|", "\\|")


def _build_overview_table(method_records: list[dict[str, Any]], paper_lookup: dict[str, dict[str, Any]]) -> str:
    rows = [
        "| 方法 | paper_id | 原始论文 | 发表年份 | 核心思路 | 适用场景 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    added_rows = 0
    for record in method_records:
        paper_key = _clean_text(record.get("paper_key"))
        paper = paper_lookup.get(paper_key) if paper_key else None
        if not paper or not _clean_text(paper.get("paper_id")):
            continue

        title = _clean_text(paper.get("title")) or "原论文未明确说明"
        if not record.get("coverage"):
            title = f"未确认原始论文；候选：{title}"
        year = _safe_int(paper.get("year"))
        year_text = str(year) if year else "原论文未明确说明"

        rows.append(
            "| {method} | {paper_id} | {title} | {year} | {core_idea} | {use_case} |".format(
                method=_escape_table_cell(record.get("method")),
                paper_id=_escape_table_cell(paper.get("paper_id")),
                title=_escape_table_cell(title),
                year=_escape_table_cell(year_text),
                core_idea=_escape_table_cell(_seed_core_idea(paper, bool(record.get("coverage")))),
                use_case=_escape_table_cell(_seed_use_case(paper, bool(record.get("coverage")))),
            )
        )
        added_rows += 1

    if added_rows == 0:
        return "暂无带有效 `paper_id` 的可确认原始论文。"
    return "\n".join(rows)


def _build_coverage_notes(
    method_records: list[dict[str, Any]],
    coverage: dict[int, bool],
    compare_records: list[dict[str, Any]],
    paper_lookup: dict[str, dict[str, Any]],
) -> str:
    notes: list[str] = []
    for record in method_records:
        sub_q_id = _safe_int(record.get("sub_question_id"))
        paper = paper_lookup.get(_clean_text(record.get("paper_key")))
        if coverage.get(sub_q_id):
            paper_id = _clean_text((paper or {}).get("paper_id")) or "unknown"
            notes.append(f"- 子问题 {sub_q_id} / {record['method']}：已找到可确认的原始论文 {paper_id}")
        else:
            notes.append(f"- 子问题 {sub_q_id} / {record['method']}：未找到原始论文，以下分析仅供参考")

    for record in compare_records:
        sub_q_id = _safe_int(record.get("sub_question_id"))
        if coverage.get(sub_q_id):
            notes.append(f"- 子问题 {sub_q_id} / compare：已找到补充性对比论文")
        else:
            notes.append(f"- 子问题 {sub_q_id} / compare：未找到有效的补充性对比论文")

    return "\n".join(notes) if notes else "- 暂无覆盖信息。"


def _build_warning_block(method_records: list[dict[str, Any]]) -> str:
    missing_methods = [record["method"] for record in method_records if not record.get("coverage")]
    if not missing_methods:
        return ""

    lines = ["## 说明"]
    for method in missing_methods:
        lines.append(f"- {method}：未找到原始论文，以下分析仅供参考")
    return "\n".join(lines)


def _format_papers_for_prompt(papers: list[dict[str, Any]]) -> str:
    if not papers:
        return "暂无可用论文。"

    sections: list[str] = []
    for index, paper in enumerate(papers, start=1):
        info = paper.get("extracted_info") or {}
        sections.append(
            "\n".join(
                [
                    f"[{index}] {paper.get('title', 'Untitled')}",
                    f"- paper_id: {_clean_text(paper.get('paper_id')) or 'unknown'}",
                    f"- year: {_safe_int(paper.get('year')) or 'unknown'}",
                    f"- source: {_clean_text(paper.get('source')) or 'unknown'}",
                    f"- matched_methods: {_render_scalar(paper.get('matched_methods') or [])}",
                    f"- validated_for: {_render_scalar(paper.get('validated_for') or [])}",
                    f"- authors: {_render_scalar(paper.get('authors') or [])}",
                    f"- doi: {_clean_text(paper.get('doi')) or 'N/A'}",
                    f"- url: {_clean_text(paper.get('url')) or 'N/A'}",
                    f"- abstract: {_clean_text(paper.get('abstract')) or 'N/A'}",
                    f"- summary: {_clean_text(paper.get('summary')) or 'N/A'}",
                    f"- extracted_method: {_render_scalar(info.get('method'))}",
                    f"- extracted_research_question: {_render_scalar(info.get('research_question'))}",
                    f"- extracted_dataset: {_render_scalar(info.get('dataset'))}",
                    f"- extracted_metrics: {_render_scalar(info.get('metrics'))}",
                    f"- extracted_results: {_render_scalar(info.get('results'))}",
                ]
            )
        )
    return "\n\n".join(sections)


def _fallback_dimension_summary(dimension: str, record: dict[str, Any], paper_lookup: dict[str, dict[str, Any]]) -> str:
    if not record.get("coverage"):
        return "未找到原始论文，以下分析仅供参考"

    paper = paper_lookup.get(_clean_text(record.get("paper_key")))
    if not paper:
        return "原论文未明确说明"

    if dimension == "检索策略":
        return _seed_core_idea(paper, True)
    if dimension == "局限性":
        info = paper.get("extracted_info") or {}
        results = _render_scalar(info.get("results"))
        return results if results != "原论文未明确说明" else "原论文未明确说明"
    return "原论文未明确说明"


def _build_fallback_sections(method_records: list[dict[str, Any]], paper_lookup: dict[str, dict[str, Any]]) -> str:
    lines = ["## 多维度对比"]
    if not method_records:
        lines.append("现有检索结果不足，无法形成可靠的多维度对比。")
    else:
        for dimension in _DIMENSIONS:
            parts = [
                f"{record['method']}：{_fallback_dimension_summary(dimension, record, paper_lookup)}"
                for record in method_records
            ]
            lines.append(f"- {dimension}：{'；'.join(parts)}")

    lines.append("")
    lines.append("## 选型建议")
    covered_methods = [record["method"] for record in method_records if record.get("coverage")]
    missing_methods = [record["method"] for record in method_records if not record.get("coverage")]
    if covered_methods:
        lines.append(
            "当前已覆盖的方法包括："
            + "、".join(covered_methods)
            + "。建议优先阅读方法概览表中的原始论文，再结合任务场景、算力预算和是否允许微调做最终选型。"
        )
    else:
        lines.append("当前未检索到足够的原始论文，建议补充更精确的方法名、作者名或论文标题后重试。")
    if missing_methods:
        lines.append("覆盖缺口：{}。未找到原始论文，以下分析仅供参考。".format("、".join(missing_methods)))
    return "\n".join(lines)


def _extract_comparison_tail(report: str) -> str:
    text = report.strip()
    if not text:
        return ""
    if "## 多维度对比" in text:
        return "## 多维度对比" + text.split("## 多维度对比", 1)[1]
    if "### 多维度对比" in text:
        return "## 多维度对比" + text.split("### 多维度对比", 1)[1]
    if "## 选型建议" in text:
        return text[text.index("## 选型建议") :]
    return ""


def _ensure_advice_section(body: str, method_records: list[dict[str, Any]], paper_lookup: dict[str, dict[str, Any]]) -> str:
    if "## 选型建议" in body:
        return body
    return body.rstrip() + "\n\n" + _build_fallback_sections(method_records, paper_lookup).split("## 选型建议", 1)[1].join(["## 选型建议", ""])


def _search_once(query: str, limit: int, year_from: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    try:
        result = run_search(query=query, target_count=limit, year_from=year_from)
    except Exception as exc:
        logger.error("Comparison search failed for query '%s': %s", query, exc, exc_info=True)
        return [], [
            {
                "type": "agent_status",
                "agent": "comparison_agent",
                "step": f"Search failed for query '{query}': {exc}",
            }
        ]

    papers = _dedupe_papers(list(result.get("papers", [])))[:limit]
    return papers, list(result.get("events", []))


def _upsert_paper_record(
    paper_lookup: dict[str, dict[str, Any]],
    paper: dict[str, Any],
    *,
    sub_question_id: int,
    sub_question_type: str,
    search_query: str,
    matched_methods: list[str],
    is_primary: bool,
) -> None:
    key = _paper_key(paper)
    if not key:
        return

    existing = paper_lookup.get(key)
    if existing is None:
        existing = {**paper}
        existing["matched_subquestion_ids"] = []
        existing["matched_methods"] = []
        existing["search_queries"] = []
        existing["sub_question_types"] = []
        existing["primary_for"] = []
        existing["validated_for"] = []
        paper_lookup[key] = existing

    _append_unique(existing["matched_subquestion_ids"], sub_question_id)
    _append_unique(existing["search_queries"], search_query)
    _append_unique(existing["sub_question_types"], sub_question_type)
    for method in matched_methods:
        _append_unique(existing["matched_methods"], method)
        if is_primary:
            _append_unique(existing["primary_for"], method)


def _analyze_papers(paper_lookup: dict[str, dict[str, Any]], events: list[dict[str, str]]) -> None:
    # 只分析确认为某方法原始论文的 primary 论文
    # 补充性论文（compare 子问题收集的）跳过，避免大量 LLM 调用导致超时
    # 用户如需深入分析某篇论文可在对话中追问
    from concurrent.futures import ThreadPoolExecutor, as_completed

    target_papers = [
        paper for paper in paper_lookup.values()
        if (paper.get("primary_for") or paper.get("validated_for"))
        and _clean_text(paper.get("paper_id"))
        and _clean_text(paper.get("abstract"))
    ]

    if not target_papers:
        return

    def _analyze_one(paper: dict[str, Any]) -> tuple[str, Any]:
        paper_id = _clean_text(paper.get("paper_id"))
        analysis = run_analysis(
            paper_id=paper_id,
            paper_title=_clean_text(paper.get("title")),
            paper_content=_clean_text(paper.get("abstract")),
            persist_to_vectordb=False,
        )
        return paper_id, analysis

    for paper in target_papers:
        events.append(
            {
                "type": "agent_status",
                "agent": "comparison_agent",
                "step": f"Analyzing paper abstract: {_clean_text(paper.get('paper_id'))}",
            }
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_paper = {executor.submit(_analyze_one, paper): paper for paper in target_papers}
        for future in as_completed(future_to_paper, timeout=120):
            paper = future_to_paper[future]
            paper_id = _clean_text(paper.get("paper_id"))
            try:
                _, analysis = future.result()
                paper["summary"] = _clean_text(analysis.get("summary"))
                paper["extracted_info"] = analysis.get("extracted_info", {})
                paper["analysis_source"] = "abstract"
                events.extend(list(analysis.get("events", [])))
            except Exception as exc:
                logger.error("Analysis failed for paper '%s': %s", paper_id, exc, exc_info=True)
                events.append(
                    {
                        "type": "agent_status",
                        "agent": "comparison_agent",
                        "step": f"Analysis failed for {paper_id}: {exc}",
                    }
                )


def _generate_report(
    user_query: str,
    overview_table: str,
    coverage_notes: str,
    warning_block: str,
    papers: list[dict[str, Any]],
    method_records: list[dict[str, Any]],
    paper_lookup: dict[str, dict[str, Any]],
    events: list[dict[str, str]],
) -> str:
    fallback_sections = _build_fallback_sections(method_records, paper_lookup)
    fallback_report_parts = [warning_block, "## 方法概览表", overview_table, "", fallback_sections]
    fallback_report = "\n".join(part for part in fallback_report_parts if part).strip()

    prompt = COMPARISON_PROMPT.format(
        user_query=user_query,
        overview_table=overview_table,
        papers_info=_format_papers_for_prompt(papers),
        coverage_notes=coverage_notes,
    )
    events.append(
        {
            "type": "agent_status",
            "agent": "comparison_agent",
            "step": "Generating comparison report.",
        }
    )

    try:
        response = invoke_llm(
            [HumanMessage(content=prompt)],
            source="comparison.report",
        )
    except Exception as exc:
        logger.error("Comparison report generation failed: %s", exc, exc_info=True)
        events.append(
            {
                "type": "agent_status",
                "agent": "comparison_agent",
                "step": f"LLM report generation failed: {exc}",
            }
        )
        return fallback_report

    body = _extract_comparison_tail(_response_to_text(response))
    if not body:
        return fallback_report

    if "## 选型建议" not in body:
        fallback_advice = _build_fallback_sections(method_records, paper_lookup)
        if "## 选型建议" in fallback_advice:
            body = body.rstrip() + "\n\n## 选型建议" + fallback_advice.split("## 选型建议", 1)[1]

    parts = [warning_block, "## 方法概览表", overview_table, "", body]
    report = "\n".join(part for part in parts if part).strip()

    # 统计补充论文数量
    supplementary_count = sum(
        1 for paper in papers
        if not paper.get("primary_for") and not paper.get("validated_for")
    )
    if supplementary_count > 0:
        report += (
            f"\n\n---\n> 💡 本报告基于各方法的原始论文进行分析。"
            f"另有 {supplementary_count} 篇补充论文（对比类文献）未展开分析，"
            f"如需深入了解某篇论文或某个方法的具体实验细节，可直接追问。"
        )

    return report


def run_comparison(
    user_query: str,
    sub_questions: list[dict[str, Any]],
    session_id: str = "",
) -> dict[str, Any]:
    """Run the dedicated method-comparison workflow."""
    events: list[dict[str, str]] = []
    if session_id:
        events.append(
            {
                "type": "agent_status",
                "agent": "comparison_agent",
                "step": f"Starting comparison session: {session_id}",
            }
        )

    coverage: dict[int, bool] = {}
    paper_lookup: dict[str, dict[str, Any]] = {}
    method_records: list[dict[str, Any]] = []
    compare_records: list[dict[str, Any]] = []
    current_year = datetime.now(timezone.utc).year

    for index, sub_question in enumerate(sub_questions, start=1):
        sub_q_id = _subquestion_id(sub_question, index)
        sub_q_type = _clean_text(sub_question.get("type")) or "find_topic"
        search_query = _clean_text(sub_question.get("question")) or user_query
        priority = _safe_int(sub_question.get("priority"), 2)
        entities = _subquestion_entities(sub_question)
        method = _method_name(sub_question)
        limit = 3 if sub_q_type == "find_paper" else 5
        year_from = 1990 if sub_q_type == "find_paper" else max(1990, current_year - 5)

        events.append(
            {
                "type": "agent_status",
                "agent": "comparison_agent",
                "step": f"Searching sub-question {sub_q_id}: {search_query}",
            }
        )
        papers, search_events = _search_once(search_query, limit, year_from)
        events.extend(search_events)

        best_candidate = _select_best_candidate(papers, entities)
        primary_paper = _select_primary_paper(papers, entities) if sub_q_type == "find_paper" else None

        if priority == 1 and sub_q_type == "find_paper" and primary_paper is None:
            retry_query = f"{search_query} arxiv paper"
            events.append(
                {
                    "type": "agent_status",
                    "agent": "comparison_agent",
                    "step": f"Knowledge gap detected for sub-question {sub_q_id}, retrying with: {retry_query}",
                }
            )
            retry_papers, retry_events = _search_once(retry_query, limit, 1990)
            events.extend(retry_events)
            papers = _dedupe_papers(papers + retry_papers)
            best_candidate = _select_best_candidate(papers, entities)
            primary_paper = _select_primary_paper(papers, entities)

        selected_papers = _prioritize_paper(papers, primary_paper or best_candidate, limit)
        if sub_q_type == "find_paper":
            coverage[sub_q_id] = primary_paper is not None
            row_paper = primary_paper or best_candidate
            method_record = {
                "sub_question_id": sub_q_id,
                "method": method,
                "coverage": coverage[sub_q_id],
                "paper_key": _paper_key(row_paper) if row_paper else "",
            }
            method_records.append(method_record)
            if not coverage[sub_q_id]:
                events.append(
                    {
                        "type": "agent_status",
                        "agent": "comparison_agent",
                        "step": f"Method '{method}' still lacks a confirmed original paper after retry.",
                    }
                )
        else:
            coverage[sub_q_id] = any(_is_valid_paper(paper) for paper in selected_papers)
            compare_records.append({"sub_question_id": sub_q_id})

        matched_methods = entities or ([method] if sub_q_type == "find_paper" else [])
        primary_key = _paper_key(primary_paper) if primary_paper else ""
        for paper in selected_papers:
            key = _paper_key(paper)
            _upsert_paper_record(
                paper_lookup,
                paper,
                sub_question_id=sub_q_id,
                sub_question_type=sub_q_type,
                search_query=search_query,
                matched_methods=matched_methods,
                is_primary=bool(primary_key and key == primary_key),
            )

        if sub_q_type == "find_paper" and primary_key:
            primary_record = paper_lookup.get(primary_key)
            if primary_record is not None:
                _append_unique(primary_record["validated_for"], method)

    _analyze_papers(paper_lookup, events)

    papers = list(paper_lookup.values())
    papers.sort(
        key=lambda paper: (
            0 if paper.get("primary_for") else 1,
            0 if paper.get("validated_for") else 1,
            -_safe_int(paper.get("citation_count"), 0),
            _safe_int(paper.get("year"), 0) or 9999,
        )
    )

    overview_table = _build_overview_table(method_records, paper_lookup)
    coverage_notes = _build_coverage_notes(method_records, coverage, compare_records, paper_lookup)
    warning_block = _build_warning_block(method_records)
    output = _generate_report(
        user_query=user_query,
        overview_table=overview_table,
        coverage_notes=coverage_notes,
        warning_block=warning_block,
        papers=papers,
        method_records=method_records,
        paper_lookup=paper_lookup,
        events=events,
    )

    return {
        "output": output,
        "papers": papers,
        "coverage": coverage,
        "events": events,
    }
