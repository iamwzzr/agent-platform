# 个人参与记录

> 只记录学习者亲手完成并能解释的内容。当前项目的空白目录与初始文档由 Codex 创建，不计作学习者编码参与。

| 日期 | 模块 | 亲手完成的代码 | 测试/命令 | 制造的失败 | 60 秒口述 | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-01 | FastAPI 最小垂直切片与自动测试 | 创建 `backend/app/__init__.py`、`backend/app/main.py`、`backend/tests/test_health.py`；通过 uv 命令将 TestClient 的开发依赖从 `httpx` 迁移到 `httpx2` | `uv sync`；`uv run python --version`；`uv run python -c "import fastapi; print(fastapi.__version__)"`；`uv run uvicorn app.main:app --reload`；用 `curl` 验证 200、404、405；`uv run python -m pytest tests/test_health.py -q` | 请求错误 Path `GET /api/v1/health/liv`，观察 404；对正确 Path 发送 `POST`，观察 405；处理 `ModuleNotFoundError: app`；处理 TestClient 的 `httpx` 弃用 warning；将响应临时改为 `broken` 并观察断言 FAILED，再恢复为 `ok` | `uv` 管理 Python 项目环境和依赖；Uvicorn 监听端口并把请求交给 FastAPI；FastAPI 按 HTTP Method + Path 匹配路由并调用处理函数；TestClient 不经过真实端口即可调用 ASGI app。404 表示 Path 不存在，405 表示 Path 存在但 Method 不允许；ERROR 表示测试在导入、收集或准备阶段未正常执行，FAILED 表示测试已经执行但断言不满足；liveness 不依赖数据库或 LLM，以免外部故障造成无意义重启。 | `8019397` |
| 2026-09-01 | 产品合同与证据边界 | 亲手创建 `docs/PRODUCT_SCOPE.md`，写出目标用户、两个核心输入与防编造约束，并提出 Python 有证据 / 只有 C 证据的对照案例；其余合同字段由 Codex协助整理 | 人工合同测试：有证据时只生成来源支持的事实；无证据时输出 gap；三类失败按 API 前置校验、Provider 调用、draft 后 validator 区分 | 首稿保留约束占位符；把“会 Python”重复当作证据；一度混淆检索无结果、Provider 失败和引用校验失败，后续完成纠正 | 核心输入是职位描述与候选人证据；成功 Run 生成带引用的 `ApplicationArtifact`；无证据产生 gap；固定输入、节点、输出和重试上限使它成为有界 Agent；未通过引用校验的 Artifact 不能成功落库 | `10b7c7a` |
| 2026-09-01 | 配置与异步数据库基础设施 | 创建 `backend/app/config.py`、`backend/app/db.py`、`backend/tests/test_config.py`、`backend/tests/test_db.py`；实现环境变量配置、AsyncEngine、AsyncSession 工厂、Declarative Base、FastAPI Session dependency 和内存 SQLite 连接测试；通过 uv 添加数据库及异步测试依赖 | 检查 `sqlite+aiosqlite` driver 与 `AsyncSession`；运行 `uv run python -m pytest tests/test_config.py -q`、`uv run python -m pytest tests/test_db.py -q`、`uv run python -m pytest tests -q`；最终结果为 `4 passed in 0.20s` | 默认 URL 预期漏写 `aiosqlite`，观察断言 FAILED 后修正；目标测试文件未保存，观察 file-not-found ERROR；真实执行 `SELECT 1` 暴露缺少 greenlet，改用 `sqlalchemy[asyncio]` 后恢复；误传 `-uv`、`-fuv`，观察 pytest 参数解析 ERROR 后使用正确命令 | URL 是数据库连接入口；Engine 惰性保存连接配置并管理连接池，不等于已经执行数据库操作；Session 表示一组数据库工作；Base 是 ORM 模型登记的共同基类；`SELECT 1` 才触发真实异步 SQL 路径，因此此前才暴露 greenlet 依赖缺失。 | `a160eed` |
| 2026-09-02 | Job ORM 模型与持久化约束 | 创建 `backend/app/models/__init__.py`、`backend/app/models/job.py`、`backend/tests/test_job_model.py`；实现 UUID 主键、workspace 作用域字段、职位标题/描述、UTC 创建时间、非空白 CheckConstraint，以及跨 Session 持久化和空白描述约束测试 | `uv run python -m pytest tests/test_job_model.py -q` 得到 `2 passed in 0.14s`；提交前全量回归为 `6 passed in 0.24s` | 先写测试并观察 `No module named 'app.models'`；在仓库根目录运行导致 file-not-found；误将目录建成单数 `app/model`，重命名为 `app/models` 后恢复；空白 description 在 commit 时触发 `IntegrityError`，由 `pytest.raises` 验证并 rollback | ORM 将类映射为表、对象映射为行、属性映射为列；`add` 不等于持久化，commit 后新 Session 能读回才证明跨 Session 落库；`nullable=False` 拒绝 NULL，CheckConstraint 拒绝纯空白；失败事务需 rollback 清理；workspace 字段不会自动隔离，查询必须主动限定。 | `8f1052c` |
| 2026-09-02 | 纯文本 Document ORM 模型 | 创建 `backend/app/models/document.py`、`backend/tests/test_document_model.py` 并更新 `backend/app/models/__init__.py`；实现可跨职位复用的 workspace 级证据文档、UUID、名称、原始文本、UTC 时间与非空白约束 | `uv run python -m pytest tests/test_document_model.py -q` 得到 `2 passed in 0.13s`；提交前全量回归为 `8 passed in 0.21s` | 在仓库根目录运行导致 file-not-found；将测试文件误命名为 `tesrt_document_model.py` 后重命名；测试先行观察 `No module named 'app.models.document'`；空白 content 的 commit 由 `pytest.raises(IntegrityError)` 验证 | Document 属于 Workspace 而非单一 Job，因此同一简历可复用于多个职位；原文保存于 Document，RAG 后续引用具体 Chunk；模型包中 Job/Document 的导入顺序在两者无互相依赖时不影响功能。 | `f22774f` |

> 上述阶段记录由 Codex 根据学习者真实完成的代码、终端输出和口述整理。提交前由学习者核对；未亲手完成的工作不得计入个人参与。

## 后续阶段记录模板

每完成一个模块，复制下面这一行并替换所有占位内容。文件路径、命令、失败现象和 Commit 必须能够在项目中核验。

| YYYY-MM-DD | 模块名称与目标 | 我亲手创建或修改的精确文件路径；实现了什么 | 我实际运行的命令；关键结果 | 我主动制造或真实遇到的失败；如何定位与恢复 | 我能独立解释的请求链、设计边界和失败语义 | 提交短哈希 |
