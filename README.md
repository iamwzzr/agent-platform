# agent-platform

这是用于亲手复现 `agent-platform-demo` 的独立学习项目：输入职位描述和候选人证据，生成带可信引用、明确证据缺口且执行过程可恢复的求职申请材料。

当前已经打通 Stage 1–9 的本地离线产品闭环；真实 OpenAI live、正式 10-case 固定评测和生产部署仍未完成。`agent-platform-demo` 只作为对照答案和最终验收夹具；学习参与证据仍只记录学习者亲手实现、运行、解释并提交的内容。

完整阶段、参与门禁和当前状态见 [`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md)。

## 端到端流程

```text
Job + Evidence Document
→ ingestion / chunking
→ workspace-scoped retrieval
→ extract / draft / validate / bounded revise
→ RunEvent + checkpoint + Artifact or explicit gap
→ React workbench polling / evidence inspection / resume
```

## Stage 1–9 总结

| 阶段 | 已实现 | 验证与边界 |
| --- | --- | --- |
| Stage 1 · FastAPI 基线 | 建立 FastAPI 应用、liveness endpoint 和最小自动测试；`GET /api/v1/health/live` 返回固定健康响应。 | 已验证 200、404 和 405；liveness 只表示进程存活，不检查数据库或 Provider。 |
| Stage 2 · 数据库与领域 API | 建立 Settings、异步 SQLAlchemy、SQLite、Job/Document 模型，以及 workspace-scoped 创建与查询 API。 | 已覆盖跨 Session 持久化、数据库约束、404/422 和 workspace 隔离；workspace path 不是身份认证。 |
| Stage 3 · 文档摄取与 RAG | 实现文本解析、固定窗口分块、稳定 Chunk 来源、幂等摄取、确定性检索和 scoped retrieval API。 | 引用可追溯到 Document/Chunk；当前检索适合离线确定性测试，不代表真实语义 embedding 质量。 |
| Stage 4 · 结构化输出与校验 | 定义 Requirement、Evidence、Claim、Gap、ApplicationArtifact，加入 Deterministic Mock Provider 和可信引用 validator。 | 合法 Artifact 通过；伪造引用、跨 requirement 借证据、缺失 coverage 和错误 gap 会被拒绝。 |
| Stage 5 · 有界 LangGraph | 实现 `extract → retrieve → draft → validate → revise/terminal` 状态图、有限修订和明确终态。 | 修订后必须重新校验；提取错误、依赖失败和 validation failure 使用不同失败语义。 |
| Stage 6 · OpenAI Provider 离线适配 | 接入 Responses API adapter、strict Pydantic parse、SecretStr 配置、脱敏错误和显式 Provider factory。 | 默认 Mock 和 fake client 测试通过；真实 OpenAI live 已明确延期，因此只能称为离线适配完成。 |
| Stage 7 · Run 与异常恢复 | 实现 AgentRun、RunEvent、ArtifactRecord、202 后台执行、幂等键、错误分类、有界 retry、checkpoint/resume、租约和 execution-token fencing。 | 后端离线回归与并发防护通过；`BackgroundTasks` 只适合单进程本地演示，供应商调用不保证 exactly-once。 |
| Stage 8 · 固定评测 smoke | 冻结 `smoke-v1` 三个离线案例：可信证据成功、无证据 gap、伪造 citation 阻断；提供指标、报告和退出码 `0/1/2`。 | 当前是开发初期 3-case smoke，不等于路线图要求的正式不可变 10-case Stage 8。 |
| Stage 9 · React 操作台 | 建立 React/TypeScript/Vite 工作台，完成 Job → Document → ingestion → Run；支持 URL 恢复、轮询、事件、引用原文、gap 和条件 Resume。 | 3-case MSW smoke、typecheck、lint、production build 和本地 Mock 前后端联调通过；它不是公网部署。 |

## 固定评测 smoke

在 `backend/` 中运行：

```text
uv run python -m app.eval_cli
uv run python -m app.eval_cli --format json
```

当前 `smoke-v1` 固定有证据、无证据 gap 和伪造引用阻断三个合成案例；详细合同见 [`docs/EVALUATION.md`](docs/EVALUATION.md)。

## 本地 React 操作台

先在一个终端启动默认 Mock 后端：

```text
cd backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

再在另一个终端启动前端：

```text
cd frontend
npm install
npm run dev
```

打开终端显示的本地地址。开发服务器会把 `/api` 代理到 `127.0.0.1:8000`，因此 Stage 9 不需要提前放宽 CORS，也不会调用真实 OpenAI。前端架构、恢复语义和 smoke 场景见 [`docs/FRONTEND.md`](docs/FRONTEND.md)。

## 开发检查

后端：

```text
cd backend
uv run python -m pytest tests -q
uvx --from ruff==0.16.5 ruff check app tests
uv lock --check
```

前端：

```text
cd frontend
npm test
npm run typecheck
npm run lint
npm run build
```

## 当前边界

- Stage 6 的真实 OpenAI API 连接、真实模型输出及 deterministic validator 兼容性尚未验证。
- Stage 8 尚未建立正式不可变的 10-case 数据集；不得原地扩写已冻结的 `smoke-v1`。
- Stage 9 默认使用 Mock，只提供当前会话工作台；没有账号、认证、历史列表、文件上传或 WebSocket。
- SQLite、Vite proxy 和 FastAPI `BackgroundTasks` 用于本地闭环，不等同于 PostgreSQL、durable worker 或生产部署。
- Secret/CORS、PostgreSQL migration、Docker Compose 和 CI 属于 Stage 10。

## 学习规则

1. 先预测输入、输出和失败路径，再写代码。
2. 每次只实现一个可运行的最小模块。
3. 每个模块至少包含一段亲手代码、一个测试、一次故障观察和一次口述。
4. 不整文件复制 `agent-platform-demo`。
5. 真实参与证据记录在 `PARTICIPATION.md`；Codex 创建的脚手架或直接实现不自动计作学习者亲手代码。

## 当前结构

```text
agent-platform/
├── backend/
│   ├── app/
│   │   ├── agent/
│   │   ├── api/
│   │   ├── models/
│   │   ├── rag/
│   │   ├── schemas/
│   │   ├── eval_cli.py
│   │   ├── evaluation.py
│   │   ├── openai_provider.py
│   │   └── run_service.py
│   ├── tests/
│   │   ├── test_eval_cli.py
│   │   └── test_evaluation.py
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── pages/
│   │   └── state/
│   ├── package.json
│   └── vite.config.ts
├── evals/datasets/smoke-v1/cases.json
├── docs/
│   ├── PRODUCT_SCOPE.md
│   ├── DEVELOPMENT_ROADMAP.md
│   ├── EVALUATION.md
│   └── FRONTEND.md
├── .gitignore
└── PARTICIPATION.md
```
