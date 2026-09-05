# Stage 1–9 参与与工程记录

本文件用于区分三件不同的事：

1. 仓库中已经存在并通过验证的工程能力；
2. 学习者亲手完成、实际运行并能够解释的个人参与；
3. 经用户授权后由 Codex 直接实施的工程工作。

只有同时具备可核验的代码修改、测试命令、故障观察和独立口述，才计作学习者完整参与。Codex 创建或直接修改的代码不会因为已经提交而自动变成学习者亲手成果。

## 总览

| 阶段 | 工程目标 | 参与归属 | 功能提交 | 当前状态 |
| --- | --- | --- | --- | --- |
| Stage 1 | FastAPI 基线与 liveness | 学习者亲手实现、测试并完成口述 | `8019397` | 完成 |
| Stage 2 | 异步数据库、Job/Document 与 scoped API | 学习者分模块亲手实现、测试并完成口述 | `a160eed` 至 `00cac71` | 完成 |
| Stage 3 | Chunk、幂等摄取与 scoped RAG | 学习者分模块亲手实现、测试并完成口述 | `30f4660`、`b662f97`、`db8be36`、`114e57b` | 完成 |
| Stage 4 | 结构化 Artifact、Mock 与可信校验 | 学习者亲手实现、测试并完成口述 | `1bc5e88` | 完成 |
| Stage 5 | 有界 LangGraph | 学习者亲手实现、测试并完成口述 | `9681214` | 完成 |
| Stage 6 | OpenAI Responses Provider adapter | 学习者完成离线实现、测试与口述 | `b6bdaf2` | 离线适配完成；真实 live 延期 |
| Stage 7 | Run、事件、幂等、重试与恢复 | Codex 经授权直接实施；不计学习者亲手编码 | `9e976ca` | 工程完成；学习者口述待补 |
| Stage 8 | 固定评测框架与 3-case smoke | Codex 经授权直接实施；无个人参与门禁证据 | `a787fd8` | 初期 smoke 完成；正式 10-case 待办 |
| Stage 9 | React 本地操作台 | Codex 多代理经授权直接实施；学习者完成手工运行检查 | `8a5f307` | 本地 Mock 闭环完成 |

## Stage 1 · FastAPI 基线

- **日期与目标**：2026-09-01；建立最小 HTTP 垂直切片，让应用能够启动并返回稳定 liveness 响应。
- **参与归属**：学习者亲手创建 `backend/app/__init__.py`、`backend/app/main.py` 和 `backend/tests/test_health.py`，并通过 uv 调整 TestClient 开发依赖。
- **核心实现**：`GET /api/v1/health/live` 返回 `200 {"status":"ok"}`；liveness 不访问数据库、Provider 或外部服务。
- **验证与故障观察**：实际运行 Uvicorn、curl 和 pytest；观察错误路径 404、错误 Method 405、`ModuleNotFoundError: app`、httpx 弃用提示，以及临时把响应改成 `broken` 后的断言失败。
- **可解释的判断**：能够区分 ERROR 与 FAILED、404 与 405，并解释为什么 liveness 必须与外部依赖解耦。
- **相关提交**：功能 `8019397`；参与记录 `9f60625`。

## Stage 2 · 数据库与领域 API

- **日期与目标**：2026-09-01 至 2026-09-02；建立可靠的持久化基础、Job/Document 领域模型和 workspace-scoped HTTP 入口。
- **参与归属**：学习者分模块亲手实现 Settings、AsyncEngine/AsyncSession、Declarative Base、Job/Document ORM、Pydantic Schema、API Router 和 FastAPI lifespan，并编写对应测试。
- **核心实现**：跨 Session SQLite 持久化、UUID/UTC 字段、非空白约束、Job/Document POST/GET、404/422 语义、workspace 查询限定、启动建表和关闭释放 Engine。
- **验证与故障观察**：观察缺少 `aiosqlite` driver、greenlet 依赖、错误目录和文件名、空白字段 `IntegrityError`、重复 Schema 定义、未注册 Router，以及 lifespan 中 `yield` 顺序错误；通过红灯和代码审查逐项恢复。
- **可解释的判断**：Engine 不等于已执行数据库操作，Session 表示事务工作单元；`nullable=False` 与 CheckConstraint 作用不同；workspace path 是数据作用域而不是认证；`create_all` 不能替代 migration。
- **相关提交**：`a160eed`、`8f1052c`、`f22774f`、`6d2fcbd`、`23714d9`、`138fca6`、`00cac71`，以及对应 participation commits。

## Stage 3 · 文档摄取与 scoped RAG

- **日期与目标**：2026-09-02 至 2026-09-03；把纯文本证据转成可追溯 Chunk，并在限定 workspace/document 的范围内检索。
- **参与归属**：学习者亲手实现分块、DocumentChunk ORM、幂等 ingestion、确定性稀疏 embedding/ranking、retrieval service/API 和自动测试。
- **核心实现**：固定 word window + overlap、Chunk position/source、复合外键、重复摄取复用原 UUID、Top-K/min-score 排序、Document 可见性整批校验和来源可追溯响应。
- **验证与故障观察**：观察 splitter 尾块/循环边界、SQLite 默认未启用外键、单列外键不能保证 workspace 一致、重复摄取唯一约束、首次/回读 UTC 表示差异、浮点自相似度超过 1，以及缩进错误导致 `UnboundLocalError`。
- **可解释的判断**：幂等不能 delete/recreate，否则旧 citation 会失效；Document 是存在性与归属事实来源；当前数值向量基于字面 token，不能宣称真实语义检索质量。
- **相关提交**：`30f4660`、`b662f97`、`db8be36`、`114e57b`。

## Stage 4 · 结构化 Artifact 与可信校验

- **日期与目标**：2026-09-04；建立 Agent 输入输出合同，并阻止结构合法但事实不可信的材料发布。
- **参与归属**：学习者亲手创建 Artifact schemas、deterministic validator、Provider Protocol/Mock 和对应测试。
- **核心实现**：Requirement、Evidence、Claim、ResumeBullet、Gap、Citation、ApplicationArtifact；以可信 run/workspace/requirements/evidence 校验引用、coverage、重复 ID、Gap 和构造后变异。
- **验证与故障观察**：主动制造伪造 citation、跨 requirement 借证据、未覆盖 requirement、Claim/Gap 冲突、重复 ID、无关 citation、错误 run ID、已有 Evidence 却输出 Gap，以及构造后清空列表的红灯。
- **可解释的判断**：Pydantic 只证明字段和类型满足结构，不能证明内容真实；只有外部可信 Evidence 与确定性发布前校验才能建立事实边界。
- **相关提交**：功能 `1bc5e88`；参与记录 `cb33fba`。

## Stage 5 · 有界 LangGraph

- **日期与目标**：2026-09-04；把提取、检索、起草、校验和修订编排成可观察且不会无限循环的状态图。
- **参与归属**：学习者亲手创建 `backend/app/agent/state.py`、`graph.py`、图测试，并扩展 Mock Provider 的 revise 合同。
- **核心实现**：`extract → retrieve → draft → validate → revise/terminal`；重复/空 requirement 前置拒绝，修订后重新校验，耗尽预算返回 `validation_failed`。
- **验证与故障观察**：经历 graph 文件拼写错误、重复 requirement 拒绝太晚、失败 draft 直接进入 terminal、`max_revisions` 参数缺失、Mock Provider 没有 revise 或返回 `None`，以及空 requirement 进入 draft。
- **可解释的判断**：修订不能保证正确，因此必须回到 validate；提取合同错误、依赖异常和校验预算耗尽必须保留不同失败语义。
- **相关提交**：功能 `9681214`；参与记录 `28c0835`。

## Stage 6 · OpenAI Responses Provider 离线适配

- **日期与目标**：2026-09-05；在不破坏默认离线测试的前提下建立真实 Provider adapter 和配置边界。
- **参与归属**：学习者完成 adapter、配置、factory、fake-client 测试和安全口述；真实 OpenAI live 经明确决定延期。
- **核心实现**：Responses Pydantic parse、draft/revise、completed/parsed 检查、`store=False`、SecretStr、显式 Provider factory、默认 Mock、固定脱敏错误和 opt-in live smoke。
- **验证与故障观察**：观察模块/字段/factory/revise 缺失、client 注入参数错误、空白 key/model 未拒绝、incomplete response 被接受、Pydantic marker 泄漏，以及 model-level ValidationError 携带原始假 key；改用字段级校验并补安全红测。
- **可解释的判断**：SecretStr 只隐藏字段自身显示；Structured Outputs 只保证结构和类型，不保证事实、workspace、引用或 coverage；默认 Mock 和显式 live 开关阻止测试意外联网。
- **相关提交**：功能 `b6bdaf2`；离线参与记录 `d8d7de6`。
- **未验证边界**：真实 API 连接、真实模型输出、费用，以及真实输出能否通过 deterministic validator。

## Stage 7 · Run、事件与异常恢复

- **日期与目标**：2026-09-05；把一次 Agent 执行变成可查询、可安全恢复、可从 checkpoint 继续的持久化 Run。
- **参与归属**：本阶段由用户明确授权 Codex 直接修改，属于工程实施记录，不计作学习者亲手编码、故障实验或已完成口述。
- **核心实现**：AgentRun、RunEvent、ArtifactRecord、`queued → running → succeeded/validation_failed/failed` 状态机、202 BackgroundTasks、幂等启动、错误分类、有界 retry、逐节点 checkpoint/resume、租约、heartbeat 和 execution-token fencing。
- **隔离与发布**：Job/Document/Chunk 运行前整批按 workspace 校验；执行路径 verifier 重新核对 Chunk identity/content；只有 deterministic validator 通过的 Artifact 才与 succeeded 状态同事务发布。
- **验证与修复**：工程验收记录覆盖同步等待拿不到 run ID、跨 workspace 关系、旧 worker token、heartbeat/终态竞态、证据内容伪造、executor DTO 变异、终态写失败、UTC 和默认 OpenAI client 生命周期。
- **可解释边界**：同 key/同请求复用 Run，异参冲突；transient 有界重试、permanent fail-fast；BackgroundTasks 不是 durable worker，外部调用结果未知时也不能保证供应商端 exactly-once。
- **相关提交**：功能 `9e976ca`；工程记录 `925e256`。
- **学习者待补**：独立解释 `202 → running → background → checkpoint/event → terminal`、幂等、retry 分类、token fencing、`validation_failed` 不发布 Artifact 以及 exactly-once 边界。

## Stage 8 · 固定评测 smoke

- **日期与目标**：2026-09-05；为检索、引用、coverage、gap 和 guardrail 建立可重复的离线回归门禁。
- **参与归属**：本阶段由用户授权 Codex 直接实施；当前没有学习者亲手代码、测试故障或口述记录，不能计作完整个人参与。
- **核心实现**：版本化 `smoke-v1`、隔离临时 SQLite/workspace、生产 ingestion/retrieval/Run/Graph/validator/persistence 路径、文本/JSON CLI 和退出码 `0/1/2`。
- **三个案例**：可信证据生成 cited Artifact；无证据生成明确 Gap；schema-valid forged citation 最终 `validation_failed` 且不发布 ArtifactRecord。
- **验证结果**：当前 evaluator 为 `3/3`；retrieval recall@5、citation validity/coverage、requirement coverage、gap accuracy 和 guardrail 均满足冻结阈值。
- **相关提交**：`a787fd8`。
- **未完成边界**：这只是开发初期 3-case smoke，不是路线图要求的正式不可变 10-case；也不衡量真实模型质量、延迟、token 或成本。

## Stage 9 · React 本地操作台

- **日期与目标**：2026-09-05；把可查询、可恢复的后端 Run 暴露为用户可操作的本地产品闭环。
- **参与归属**：React/Vite 前端及后端可信读桥接由 Codex 多代理经用户授权直接实施，不计作学习者亲手编码；学习者完成了本地服务启动、结果截图和故障复验。
- **核心实现**：Job → Document → ingestion → Run 创建链、单一 Idempotency-Key、可刷新 Run URL、串行自调度轮询、页面隐藏暂停与请求取消、五类状态、已知运行事件的人类可读展示与未知事件安全 fallback、Artifact/引用原文/Gap、`terminal_validation`、`can_resume` 和条件 Resume。
- **可信 UI 边界**：后端重新限定并批量提供 `citation_sources`；前端不渲染原始 Event JSON、不自行猜租约状态，网络错误保留最后可信快照。
- **验证结果**：3 个 MSW workflow smoke 与 2 个状态展示测试通过，TypeScript、ESLint 和 production build 通过；本地 Mock 前后端真实联调及浏览器刷新恢复通过。
- **真实故障观察**：首次手工保存 Role 时，Vite 5173 正常但 Uvicorn 8000 未启动，代理返回服务错误；启动后端并只重试当前步骤后，Attempt 1 到达 `COMPLETE / Application ready`，显示 1/1 verified、可信 `resume.txt` excerpt、8 条事件和 0 gaps。
- **相关提交**：`8a5f307`。
- **未完成边界**：这是本地 Mock 操作台，不是公网部署；没有认证、历史列表、文件上传、WebSocket、PostgreSQL、durable worker 或真实 OpenAI 验收。

## 当前综合验收

以下结果于 2026-09-06 在本地重新验证：

- 后端：`235 passed, 1 skipped`；唯一 skip 是明确延期的 OpenAI live smoke。
- Stage 8 evaluator：`3/3`，适用质量指标及 guardrail 均为 `1.0`。
- 前端：`5 passed`，typecheck、ESLint 和 production build 通过。
- Stage 9 手工链路：前端 5173、后端 8000、Vite proxy 和 Run detail 均返回成功；结果页刷新恢复且控制台无 error/warn。

## 个人参与边界与待补门禁

- Stage 1–6 可以按本文件记录计作学习者亲手实践；Stage 6 只能表述为“OpenAI Provider 离线适配”，不能表述为真实模型接通。
- Stage 7 代码由 Codex 直接实施，学习者口述仍待补；在完成口述之前，不能把该阶段标记为学习者完整参与。
- Stage 8–9 当前只有工程成果；Stage 9 可计一次真实手工运行与故障观察，但不足以证明亲手编码。
- 若要把 Stage 7–9 计入完整个人参与，学习者仍需各自完成一个有意义的代码修改、一个自动测试、一次可解释失败和 60 秒口述，并产生独立提交。

## 前置产品合同

Stage 0 的产品核心句和“Python 有证据 / 只有 C 证据”的对照案例由学习者提出；其余边界由 Codex 协助整理。对应产品合同为 `docs/PRODUCT_SCOPE.md`，提交 `10b7c7a`，参与记录提交 `1711e56`。

## 后续阶段记录模板

每完成一个模块，补充：日期与目标、参与归属、精确文件、实际命令与结果、真实失败及修复、能够独立解释的边界、功能提交。未经核验的内容不得写入个人参与。
