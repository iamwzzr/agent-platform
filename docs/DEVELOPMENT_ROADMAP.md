# Agent Platform 开发路线

本项目以“职位描述 + 候选人证据文档 → 有引用、可校验、可恢复的求职申请材料”为垂直场景，技术栈固定为 FastAPI、SQLAlchemy、React/TypeScript、LangGraph、真实 LLM 和 RAG。

`agent-platform-demo` 只作为对照和最终验收参考，不整文件复制。每个阶段都必须由学习者亲手完成代码、测试、故障观察和口述。

## 每阶段统一门禁

1. 开始前预测输入、输出和至少一种失败。
2. 学习者亲手实现至少一个有意义的函数或组件。
3. 学习者亲手编写至少一个自动测试。
4. 主动制造一次失败并读懂错误信息。
5. Codex 审查实现并运行自动验收。
6. 学习者完成 60 秒口述。
7. 将证据写入 `PARTICIPATION.md`，再完成一个小提交。

未通过当前阶段时，不提前堆叠下一阶段框架。

## 阶段路线

| 阶段 | 目标 | 最小产物 | 关键验收 |
| --- | --- | --- | --- |
| 0. 产品合同 | 固定用户、输入、输出、非目标和质量标准 | 一页 scope、一个有证据 case、一个无证据 case | 能解释为什么它是有界 Agent workflow，而非通用聊天机器人 |
| 1. FastAPI 基线 | 打通最小 HTTP 垂直切片 | `app/main.py`、liveness route、`test_health.py` | GET 返回 `200 {"status":"ok"}`；测试经历红→绿；观察 404/405 |
| 2. 数据库与 API | 建立可靠领域数据入口 | Settings、异步 SQLAlchemy、Job/Document、创建与查询 API | 跨 session 可读取；约束和 workspace 隔离测试通过 |
| 3. 文档摄取与 RAG | 从证据文档得到可追踪检索结果 | parser、chunk、embedding/ranker、Chunk 表、retrieve | 相关 chunk 排前；无关查询可返回空；来源 ID 可追溯 |
| 4. 结构化输出与 Mock | 先离线固定 Agent 数据合同 | Requirement/Evidence/Claim/Gap/ApplicationArtifact、Provider 接口、Mock、validator | 合法 Artifact 通过；伪造引用失败；无证据进入 gap |
| 5. LangGraph | 把业务步骤编排成有界状态图 | extract→retrieve→draft→validate→revise/terminal | 节点顺序可观察；修订有上限；失败类型不混淆 |
| 6. 真实 LLM | 在不破坏离线测试的前提下接真实 Provider | Provider adapter、环境变量、strict structured output、live smoke test | 缺 key 明确失败；测试默认不联网；真实调用结果脱敏记录 |
| 7. Run 与异常恢复 | 把执行过程变成可查询、可恢复的数据 | AgentRun、RunEvent、Artifact、幂等、重试、checkpoint/resume | transient 有界重试；permanent 不重试；重复 key 不重复付费；resume 不重做完成节点 |
| 8. 固定评测 | 防止 Prompt、检索和模型升级导致质量回退 | 版本化 10-case 数据集、retrieval/citation/coverage/gap 指标、CLI | 低于阈值退出非 0，并准确列出失败 case |
| 9. React 操作台 | 让用户完成真实业务闭环 | Job/Document 表单、启动 Run、状态轮询、事件、引用、gap、恢复 UI | loading/empty/error/success 均可验证；生产 build 通过 |
| 10. 安全与部署 | 构建可复现的运行环境 | readiness、API key、CORS、`.env.example`、PostgreSQL、Docker Compose、CI | 重启后数据仍在；Secret 不进仓库；后端/前端/评测门禁全过 |
| 11. 面试交付 | 在固定时间内展示价值与工程判断 | seed、README、架构图、故障演示、两分钟脚本 | clean start 可复现；本人能说明实现、取舍、边界和未验证项 |

## 当前状态

- 已完成：阶段 0 产品合同；阶段 1 FastAPI liveness、自动测试、故障注入、口述和 Git 提交。
- 已建立：Python 3.12/uv 环境、FastAPI/Uvicorn/pytest/httpx2 依赖、`uv.lock` 与 `main` 分支提交历史。
- 正在准备：阶段 2 数据库与 API，先定义 Settings、Job、Document 和 workspace 隔离边界。
- 尚未开始：数据库业务实现、RAG、LangGraph、真实 LLM、Run 恢复、固定评测、React 和 Docker。
- 当前环境限制：本机尚未安装 Docker；阶段 2 先用 SQLite 开发，不阻塞当前学习。

## 第一阶段合同

```text
GET /api/v1/health/live
→ HTTP 200
→ {"status":"ok"}
```

Liveness 只回答“FastAPI 进程是否活着”，不访问数据库、LLM 或任何外部服务。依赖检查以后放在 readiness endpoint。

## 第二阶段边界

阶段 2 只实现领域数据入口和持久化：Settings、异步 SQLAlchemy、Job、Document、创建/查询 API、约束与 workspace 隔离测试。暂不实现文档切块、向量检索、LangGraph、Provider 或前端。
