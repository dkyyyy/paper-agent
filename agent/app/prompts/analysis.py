"""
Prompt: Analysis Agent Prompts
版本: v1.0
"""

EXTRACT_INFO_PROMPT = """你是一个学术论文分析专家。请从以下论文内容中提取关键信息。
## 论文内容
{content}

## 提取要求
请提取以下五元组信息，如果某项信息在文中未明确提及，填写“未明确提及”。
输出 JSON 格式：
```json
{{
  "research_question": "该论文要解决的核心研究问题",
  "method": "提出的核心方法/模型/算法的简要描述",
  "dataset": ["使用的数据集列表"],
  "metrics": {{"指标名": "最佳结果值"}},
  "results": "主要实验结论的一句话总结"
}}
```
"""

SECTION_SUMMARY_PROMPT = """请为以下论文章节生成简洁的学术摘要（100-200字）。
## 章节标题
{section_title}

## 章节内容
{section_content}

要求：
- 保留关键术语和数据
- 使用学术语言
- 不超过 200 字
"""

PAPER_SUMMARY_PROMPT = """请为以下论文生成一段全面的学术摘要（300-500字）。
## 论文标题
{title}

## 论文全文
{content}

要求：
- 涵盖研究背景、方法、实验、结论
- 保留关键数据和结论
- 使用学术语言
- 300-500 字
"""