"""
Prompt: Search Agent Prompts
版本: v1.1
"""

KEYWORD_EXTRACTION_PROMPT = """从以下用户查询中提取学术搜索关键词。
用户查询：{query}

要求：
1. 提取 2-3 个英文关键词，不要超过 3 个
2. 第一个关键词必须是用户查询的核心概念直接翻译，不得替换或泛化
3. 其余关键词可以是核心概念的重要子领域术语
4. 禁止用宽泛的上位概念替换具体术语（例如不能用 "sequential decision making" 替换 "reinforcement learning"）
5. 如果用户用中文，翻译为对应的英文学术术语

示例：
- 用户查询"强化学习" → ["reinforcement learning", "deep reinforcement learning"]
- 用户查询"RAG优化" → ["retrieval augmented generation", "RAG optimization"]

输出 JSON 格式：
```json
{{"keywords": ["keyword1", "keyword2"]}}
```
"""

QUERY_EXPANSION_PROMPT = """当前搜索结果不足，需要扩展搜索。
原始查询：{original_query}
已使用的关键词：{used_keywords}
当前找到论文数：{current_count}
目标论文数：{target_count}

请生成 2-3 个新的搜索 query，要求：
1. 聚焦原始查询的核心概念，不要偏移到其他领域
2. 使用同义词或子领域术语（例如把 RAG 扩展为 "retrieval augmented generation"）
3. 每个 query 必须是简短的自然语言短语（2-5个词），不要使用任何特殊语法
4. 禁止使用：site:、OR、AND、引号组合、after:、before: 等布尔/过滤语法
5. 禁止使用会议名称（EMNLP、ICLR、NeurIPS 等）作为查询词

示例好的 query：["dense retrieval transformer", "RAG hallucination reduction"]
示例坏的 query：["(RAG OR retrieval) site:arxiv.org after:2023", "EMNLP 2024 RAG"]

输出 JSON 格式：
```json
{{"queries": ["new query 1", "new query 2"]}}
```
"""
