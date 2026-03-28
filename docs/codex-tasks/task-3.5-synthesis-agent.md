# Codex 执行指令 — 任务 3.5：Synthesis Agent（综合报告）

## 任务目标

实现跨论文综合分析 Agent，生成方法对比表格、文献综述、研究时间线、Research Gap 分析。

## 前置依赖

- 任务 3.2 已完成（Supervisor + LLM 工厂）
- 参考文档：`docs/02-dev-standards.md` Agent 开发模板

## 需要创建的文件

### 1. `agent/app/prompts/synthesis.py`

```python
"""
Prompt: Synthesis Agent Prompts
版本: v1.0
"""

COMPARISON_PROMPT = """你是一个学术论文对比分析专家。

## 论文信息
{papers_info}

## 任务
请生成一个方法对比表格（Markdown 格式），列包含：
- 论文标题
- 核心方法
- 使用的数据集
- 关键指标及结果
- 主要优点
- 主要局限

然后用 2-3 段文字总结这些方法的异同和各自适用场景。

## 输出格式
先输出 Markdown 表格，再输出文字总结。
"""

SURVEY_PROMPT = """你是一个学术综述写作专家。

## 论文信息
{papers_info}

## 研究主题
{topic}

## 任务
请基于以上论文信息，撰写一段结构化的文献综述（800-1500字），要求：

1. 开头段：概述该研究领域的背景和重要性
2. 主体段（2-3段）：按方法类别或时间线组织，介绍各论文的贡献
3. 总结段：归纳当前研究的整体趋势和共识

引用格式：使用 [1][2] 等数字标注引用对应论文。

在文末附上参考文献列表：
[1] Author et al. "Title". Year.
[2] ...
"""

TIMELINE_PROMPT = """你是一个学术研究脉络分析专家。

## 论文信息
{papers_info}

## 任务
请按时间顺序梳理这些论文的研究脉络，输出 Markdown 格式的时间线：

## 研究时间线

### {year1}
- **论文标题** — 核心贡献一句话描述

### {year2}
- **论文标题** — 核心贡献一句话描述

...

最后用一段话总结研究演进趋势。
"""

GAP_ANALYSIS_PROMPT = """你是一个学术研究方向分析专家。

## 已有研究
{papers_info}

## 研究主题
{topic}

## 任务
基于以上已有研究，分析当前研究的覆盖范围，识别尚未被充分探索的方向。

请输出：
1. 当前研究覆盖的主要方向（3-5个）
2. 潜在的研究空白（Research Gap）（3-5个），每个包含：
   - 方向名称
   - 为什么这是一个 gap（现有研究缺少什么）
   - 可能的研究思路
3. 一段总结性建议
"""
```

### 2. `agent/app/agents/synthesis_agent.py`

```python
"""
Agent: Synthesis Agent
职责: 跨论文综合分析，生成对比报告、文献综述、时间线、Research Gap
绑定工具: comparison_table_gen, timeline_gen, report_template
"""

import logging
from typing import TypedDict, Literal

from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from app.prompts.synthesis import (
    COMPARISON_PROMPT,
    SURVEY_PROMPT,
    TIMELINE_PROMPT,
    GAP_ANALYSIS_PROMPT,
)

logger = logging.getLogger(__name__)


class SynthesisState(TypedDict):
    papers: list[dict]          # 已分析的论文列表（含五元组）
    topic: str                  # 研究主题
    task_type: str              # comparison | survey | gap_analysis | full
    output: str                 # 最终报告（Markdown）
    comparison_table: str       # 对比表格
    survey_text: str            # 文献综述
    timeline: str               # 时间线
    gap_analysis: str           # Research Gap 分析
    events: list


def _format_papers_info(papers: list[dict]) -> str:
    """将论文列表格式化为 Prompt 输入。"""
    parts = []
    for i, p in enumerate(papers, 1):
        info = p.get("extracted_info", {})
        part = f"""### [{i}] {p.get('title', 'Unknown Title')}
- 作者: {', '.join(p.get('authors', [])[:3])}
- 年份: {p.get('year', 'N/A')}
- 引用数: {p.get('citation_count', 0)}
- 研究问题: {info.get('research_question', 'N/A')}
- 方法: {info.get('method', 'N/A')}
- 数据集: {', '.join(info.get('dataset', [])) if isinstance(info.get('dataset'), list) else info.get('dataset', 'N/A')}
- 指标: {info.get('metrics', 'N/A')}
- 结果: {info.get('results', 'N/A')}
"""
        parts.append(part)
    return "\n".join(parts)


def generate_comparison(state: SynthesisState) -> dict:
    """生成方法对比表格。"""
    if state["task_type"] not in ("comparison", "full"):
        return {}

    from app.agents.llm import get_llm

    events = state.get("events", [])
    events.append({
        "type": "agent_status",
        "agent": "synthesis_agent",
        "step": "正在生成方法对比表格...",
    })

    llm = get_llm()
    papers_info = _format_papers_info(state["papers"])
    prompt = COMPARISON_PROMPT.format(papers_info=papers_info)
    response = llm.invoke([HumanMessage(content=prompt)])

    return {
        "comparison_table": response.content,
        "events": events,
    }


def generate_survey(state: SynthesisState) -> dict:
    """生成文献综述。"""
    if state["task_type"] not in ("survey", "full"):
        return {}

    from app.agents.llm import get_llm

    events = state.get("events", [])
    events.append({
        "type": "agent_status",
        "agent": "synthesis_agent",
        "step": "正在撰写文献综述...",
    })

    llm = get_llm()
    papers_info = _format_papers_info(state["papers"])
    prompt = SURVEY_PROMPT.format(papers_info=papers_info, topic=state["topic"])
    response = llm.invoke([HumanMessage(content=prompt)])

    return {
        "survey_text": response.content,
        "events": events,
    }


def generate_timeline(state: SynthesisState) -> dict:
    """生成研究时间线。"""
    if state["task_type"] not in ("survey", "full"):
        return {}

    from app.agents.llm import get_llm

    events = state.get("events", [])
    events.append({
        "type": "agent_status",
        "agent": "synthesis_agent",
        "step": "正在梳理研究时间线...",
    })

    llm = get_llm()
    papers_info = _format_papers_info(state["papers"])
    prompt = TIMELINE_PROMPT.format(papers_info=papers_info, year1="20XX", year2="20XX")
    response = llm.invoke([HumanMessage(content=prompt)])

    return {
        "timeline": response.content,
        "events": events,
    }


def generate_gap_analysis(state: SynthesisState) -> dict:
    """生成 Research Gap 分析。"""
    if state["task_type"] not in ("gap_analysis", "full"):
        return {}

    from app.agents.llm import get_llm

    events = state.get("events", [])
    events.append({
        "type": "agent_status",
        "agent": "synthesis_agent",
        "step": "正在分析 Research Gap...",
    })

    llm = get_llm()
    papers_info = _format_papers_info(state["papers"])
    prompt = GAP_ANALYSIS_PROMPT.format(papers_info=papers_info, topic=state["topic"])
    response = llm.invoke([HumanMessage(content=prompt)])

    return {
        "gap_analysis": response.content,
        "events": events,
    }


def assemble_report(state: SynthesisState) -> dict:
    """组装最终报告。"""
    events = state.get("events", [])
    sections = []

    if state.get("survey_text"):
        sections.append("## 文献综述\n\n" + state["survey_text"])

    if state.get("comparison_table"):
        sections.append("## 方法对比\n\n" + state["comparison_table"])

    if state.get("timeline"):
        sections.append("## 研究时间线\n\n" + state["timeline"])

    if state.get("gap_analysis"):
        sections.append("## Research Gap 分析\n\n" + state["gap_analysis"])

    output = f"# {state['topic']} — 研究报告\n\n" + "\n\n---\n\n".join(sections)

    events.append({
        "type": "agent_status",
        "agent": "synthesis_agent",
        "step": f"报告生成完成（{len(sections)} 个章节）",
    })

    return {
        "output": output,
        "events": events,
    }


def build_synthesis_graph() -> StateGraph:
    """构建 Synthesis Agent 的 LangGraph 状态机。

    流程：
    START → generate_comparison → generate_survey → generate_timeline
          → generate_gap_analysis → assemble_report → END
    """
    graph = StateGraph(SynthesisState)

    graph.add_node("generate_comparison", generate_comparison)
    graph.add_node("generate_survey", generate_survey)
    graph.add_node("generate_timeline", generate_timeline)
    graph.add_node("generate_gap_analysis", generate_gap_analysis)
    graph.add_node("assemble_report", assemble_report)

    graph.set_entry_point("generate_comparison")
    graph.add_edge("generate_comparison", "generate_survey")
    graph.add_edge("generate_survey", "generate_timeline")
    graph.add_edge("generate_timeline", "generate_gap_analysis")
    graph.add_edge("generate_gap_analysis", "assemble_report")
    graph.add_edge("assemble_report", END)

    return graph.compile()


synthesis_graph = build_synthesis_graph()


def run_synthesis(
    papers: list[dict],
    topic: str,
    task_type: str = "full",
) -> dict:
    """Run the synthesis agent.

    Args:
        papers: List of paper dicts with extracted_info.
        topic: Research topic string.
        task_type: "comparison" | "survey" | "gap_analysis" | "full"

    Called by Supervisor Agent's dispatch logic.
    """
    initial_state = SynthesisState(
        papers=papers,
        topic=topic,
        task_type=task_type,
        output="",
        comparison_table="",
        survey_text="",
        timeline="",
        gap_analysis="",
        events=[],
    )
    return synthesis_graph.invoke(initial_state)
```

### 3. `agent/tests/test_synthesis.py`

```python
"""Test Synthesis Agent."""

from app.agents.synthesis_agent import (
    build_synthesis_graph,
    _format_papers_info,
    SynthesisState,
)


def test_graph_builds():
    graph = build_synthesis_graph()
    assert graph is not None


def test_format_papers_info():
    papers = [
        {
            "title": "RAG-Fusion",
            "authors": ["Author A", "Author B"],
            "year": 2024,
            "citation_count": 50,
            "extracted_info": {
                "research_question": "How to improve RAG?",
                "method": "Reciprocal rank fusion",
                "dataset": ["NQ", "TriviaQA"],
                "metrics": {"EM": "45.2"},
                "results": "Improved by 5%",
            },
        },
        {
            "title": "Self-RAG",
            "authors": ["Author C"],
            "year": 2023,
            "citation_count": 120,
            "extracted_info": {
                "research_question": "How to make RAG self-reflective?",
                "method": "Self-reflection tokens",
                "dataset": ["PopQA"],
                "metrics": {"EM": "48.1"},
                "results": "SOTA on PopQA",
            },
        },
    ]
    result = _format_papers_info(papers)
    assert "RAG-Fusion" in result
    assert "Self-RAG" in result
    assert "[1]" in result
    assert "[2]" in result


def test_initial_state():
    state = SynthesisState(
        papers=[],
        topic="RAG optimization",
        task_type="full",
        output="",
        comparison_table="",
        survey_text="",
        timeline="",
        gap_analysis="",
        events=[],
    )
    assert state["task_type"] == "full"
```

## 验收标准

### 1. 编译检查

```bash
cd agent
python -c "from app.agents.synthesis_agent import synthesis_graph; print('OK')"
```

### 2. 测试

```bash
cd agent
python -m pytest tests/test_synthesis.py -v
```

### 3. 验收 Checklist

- [ ] `from app.agents.synthesis_agent import synthesis_graph` 无报错
- [ ] Graph 包含 5 个节点：generate_comparison, generate_survey, generate_timeline, generate_gap_analysis, assemble_report
- [ ] 方法对比：生成 Markdown 表格（论文/方法/数据集/指标/优缺点）
- [ ] 文献综述：800-1500 字，包含引用标注 [1][2]，附参考文献列表
- [ ] 时间线：按年份组织，每篇论文一句话描述贡献
- [ ] Research Gap：3-5 个潜在研究方向，含原因和思路
- [ ] task_type 控制：comparison/survey/gap_analysis 只生成对应部分，full 生成全部
- [ ] 最终报告为合法 Markdown，包含标题和分隔线
- [ ] `run_synthesis()` 函数可被 Supervisor 直接调用
- [ ] 测试通过

## 提交

```bash
git add agent/
git commit -m "feat(agent): implement Synthesis Agent for cross-paper analysis

- Method comparison table generation (Markdown)
- Literature survey writing with citations [1][2]
- Research timeline by year
- Research Gap identification (3-5 directions)
- Configurable task_type: comparison/survey/gap_analysis/full
- LangGraph state machine with sequential generation pipeline"
```

## 注意事项

1. 各生成步骤通过 task_type 控制是否执行，避免不必要的 LLM 调用
2. `_format_papers_info` 是所有 Prompt 的共用输入格式化函数
3. 论文列表为空时各步骤会生成空内容，不会报错
4. 后续可优化为并行生成（comparison 和 timeline 无依赖关系），当前串行足够
