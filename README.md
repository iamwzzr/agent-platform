# agent-platform

这是用于亲手复现 `agent-platform-demo` 的独立学习项目。

当前已完成阶段 0–6 的离线里程碑，并完成待提交的阶段 7 Run、异常恢复和后台 API；下一步进入固定评测。真实 OpenAI live smoke 仍按用户决定延期。`agent-platform-demo` 只作为对照答案和最终验收夹具；学习参与证据仍只记录学习者亲手实现、运行、解释并提交的内容。

完整阶段、参与门禁和当前状态见 [`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md)。

## 学习规则

1. 先预测输入、输出和失败路径，再写代码。
2. 每次只实现一个可运行的最小模块。
3. 每个模块至少包含一段亲手代码、一个测试、一次故障观察和一次口述。
4. 不整文件复制 `agent-platform-demo`。
5. 真实参与证据记录在 `PARTICIPATION.md`；Codex 创建的空白脚手架不计作学习者代码。

## 当前结构

```text
agent-platform/
├── backend/
│   ├── app/main.py
│   ├── tests/test_health.py
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/
│   └── src/
├── evals/
├── docs/
│   ├── PRODUCT_SCOPE.md
│   └── DEVELOPMENT_ROADMAP.md
├── .gitignore
└── PARTICIPATION.md
```

## 已完成

- 阶段 0：产品合同、有证据 case、无证据 case、非目标和固定质量标准。
- 阶段 1：FastAPI liveness route、自动测试、200/404/405、故障注入与恢复。

```text
GET /api/v1/health/live
→ 200
→ {"status": "ok"}
```

## 当前关：数据库与 API

```text
Job + Document
→ FastAPI 创建/查询 API
→ SQLAlchemy 持久化
→ workspace 隔离
```

阶段 2 只建立可靠的领域数据入口；暂不添加 RAG、LangGraph、真实 LLM 或 React。
