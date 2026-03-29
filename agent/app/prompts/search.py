"""
Prompt: Search Agent Prompts
版本: v1.0
"""

KEYWORD_EXTRACTION_PROMPT = """从以下用户查询中提取学术搜索关键词。
用户查询：{query}

要求：
1. 提取 3-5 个英文关键词（学术论文通常是英文）
2. 包含核心概念和相关术语
3. 如果用户用中文，翻译为对应的英文学术术语

输出 JSON 格式：
```json
{{"keywords": ["keyword1", "keyword2", "keyword3"]}}
```
"""

QUERY_EXPANSION_PROMPT = """当前搜索结果不足，需要扩展搜索。
原始查询：{original_query}
已使用的关键词：{used_keywords}
当前找到论文数：{current_count}
目标论文数：{target_count}

请生成 2-3 个新的搜索 query，使用不同的关键词组合或同义词，以找到更多相关论文。
输出 JSON 格式：
```json
{{"queries": ["new query 1", "new query 2"]}}
```
"""