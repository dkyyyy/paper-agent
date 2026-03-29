# Codex 并行执行提示词

## 线程 1：Go Gateway 开发

你是一个 Go 后端开发专家。请按顺序执行以下任务，每个任务完成后输出"任务 X 完成"，然后继续下一个。

**项目路径**：`D:/Code/agent/paper-agent`

**任务列表**：
1. task-2.1：Go 项目初始化与配置管理
2. task-2.2：Redis 会话管理
3. task-2.3：gRPC 客户端封装
4. task-2.4：HTTP 聊天接口（SSE + WebSocket）
5. task-2.5：文件上传接口
6. task-2.6：健康检查与中间件

**执行方式**：
- 每个任务的详细指令在 `docs/codex-tasks/task-X.md`
- 严格按照文档中的文件路径、代码模板、验收标准执行
- 每个任务完成后运行验收检查（编译、测试）
- 验收通过后提交代码（使用文档中的 commit message）
- 遇到错误时输出完整错误信息，不要继续下一个任务

**开始执行**：从 task-2.1 开始。

---

## 线程 2：Python Agent 开发

你是一个 Python AI Agent 开发专家。请按顺序执行以下任务，每个任务完成后输出"任务 X 完成"，然后继续下一个。

**项目路径**：`D:/Code/agent/paper-agent`

**任务列表**：
1. task-3.1：Python gRPC Server 骨架
2. task-3.2：Supervisor Agent（LangGraph 状态机）
3. task-3.3：Search Agent（多源文献检索）
4. task-3.4：Analysis Agent（论文分析 + RAG）
5. task-3.5：Synthesis Agent（综合报告）
6. task-5.3：分层检索器
7. task-6.1：Redis 搜索缓存
8. task-6.2：Token 预算控制

**执行方式**：
- 每个任务的详细指令在 `docs/codex-tasks/task-X.md`
- 严格按照文档中的文件路径、代码模板、验收标准执行
- 每个任务完成后运行验收检查（编译、测试）
- 验收通过后提交代码（使用文档中的 commit message）
- 遇到错误时输出完整错误信息，不要继续下一个任务

**开始执行**：从 task-3.1 开始。

---

## 线程 3：Vue3 前端开发

你是一个 Vue3 + TypeScript 前端开发专家。请按顺序执行以下任务，每个任务完成后输出"任务 X 完成"，然后继续下一个。

**项目路径**：`D:/Code/agent/paper-agent`

**任务列表**：
1. task-7.1：Vue3 项目初始化（Vite + TypeScript + Element Plus）
2. task-7.2：WebSocket 通信层
3. task-7.3：聊天界面（流式显示 + Markdown 渲染）
4. task-7.6：会话管理侧边栏

**执行方式**：
- 每个任务的详细指令在 `docs/codex-tasks/task-X.md`
- 严格按照文档中的文件路径、代码模板、验收标准执行
- 每个任务完成后运行验收检查（TypeScript 编译、启动测试）
- 验收通过后提交代码（使用文档中的 commit message）
- 遇到错误时输出完整错误信息，不要继续下一个任务

**开始执行**：从 task-7.1 开始。
