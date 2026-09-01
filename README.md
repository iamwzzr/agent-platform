# agent-platform

这是用于亲手复现 `agent-platform-demo` 的独立学习项目。

当前业务目录仍为空，没有复制 demo 的业务代码或测试；后端已经完成 `uv` 初始化并加入 FastAPI、Uvicorn、pytest 和 httpx。`agent-platform-demo` 只作为对照答案和最终验收夹具；这里的每个功能模块由学习者亲手实现、运行、解释并提交。

完整阶段、参与门禁和当前状态见 [`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md)。

## 学习规则

1. 先预测输入、输出和失败路径，再写代码。
2. 每次只实现一个可运行的最小模块。
3. 每个模块至少包含一段亲手代码、一个测试、一次故障观察和一次口述。
4. 不整文件复制 `agent-platform-demo`。
5. 真实参与证据记录在 `PARTICIPATION.md`；Codex 创建的空白脚手架不计作学习者代码。

## 空白结构

```text
agent-platform/
├── backend/
│   ├── app/
│   └── tests/
├── frontend/
│   └── src/
├── evals/
├── docs/
├── .gitignore
└── PARTICIPATION.md
```

## 第一关

由学习者亲手创建最小 FastAPI 应用，并实现：

```text
GET /api/v1/health/live
→ 200
→ {"status": "ok"}
```

暂时不要创建数据库、LangGraph、RAG 或 React。先证明自己能解释：HTTP 请求怎样进入 FastAPI route，响应怎样返回调用方。
