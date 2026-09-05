# agent-platform

这是用于亲手复现 `agent-platform-demo` 的独立学习项目。

当前已完成阶段 0–6 的离线里程碑，阶段 7 Run、异常恢复和后台 API 已提交；阶段 8 的 3-case 离线 smoke 切片也已完成，正式 10-case 固定评测仍待完成。真实 OpenAI live smoke 仍按用户决定延期。`agent-platform-demo` 只作为对照答案和最终验收夹具；学习参与证据仍只记录学习者亲手实现、运行、解释并提交的内容。

完整阶段、参与门禁和当前状态见 [`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md)。

## 固定评测 smoke

在 `backend/` 中运行：

```text
uv run python -m app.eval_cli
uv run python -m app.eval_cli --format json
```

当前 `smoke-v1` 固定有证据、无证据 gap 和伪造引用阻断三个合成案例；详细合同见 [`docs/EVALUATION.md`](docs/EVALUATION.md)。

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
│   ├── app/
│   │   ├── eval_cli.py
│   │   ├── evaluation.py
│   │   └── schemas/evaluation.py
│   ├── tests/
│   │   ├── test_eval_cli.py
│   │   └── test_evaluation.py
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/
│   └── src/
├── evals/datasets/smoke-v1/cases.json
├── docs/
│   ├── PRODUCT_SCOPE.md
│   ├── DEVELOPMENT_ROADMAP.md
│   └── EVALUATION.md
├── .gitignore
└── PARTICIPATION.md
```

## 当前里程碑

- 阶段 0–7：离线后端闭环、结构化产物、LangGraph、Provider adapter、可查询且可恢复的 Run 已完成；真实 OpenAI live smoke 仍延期。
- 阶段 8 开发初期切片：冻结 3 个 synthetic case，运行完整生产数据/Agent 链路，并输出 retrieval、citation、coverage、gap 和 guardrail 指标。
- 正式 Stage 8：仍需新增一个不可变的 10-case 数据集版本；不能原地扩写 `smoke-v1`。

```text
smoke-v1 cases
→ 临时 SQLite + 独立 workspace
→ ingestion / retrieval / graph / validator / persistence
→ 稳定报告与退出码 0 / 1 / 2
```
