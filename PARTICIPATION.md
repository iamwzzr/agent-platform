# 个人参与记录

> 只记录学习者亲手完成并能解释的内容。当前项目的空白目录与初始文档由 Codex 创建，不计作学习者编码参与。

| 日期 | 模块 | 亲手完成的代码 | 测试/命令 | 制造的失败 | 60 秒口述 | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-01 | FastAPI 最小垂直切片与自动测试 | 创建 `backend/app/__init__.py`、`backend/app/main.py`、`backend/tests/test_health.py`；通过 uv 命令将 TestClient 的开发依赖从 `httpx` 迁移到 `httpx2` | `uv sync`；`uv run python --version`；`uv run python -c "import fastapi; print(fastapi.__version__)"`；`uv run uvicorn app.main:app --reload`；用 `curl` 验证 200、404、405；`uv run python -m pytest tests/test_health.py -q` | 请求错误 Path `GET /api/v1/health/liv`，观察 404；对正确 Path 发送 `POST`，观察 405；处理 `ModuleNotFoundError: app`；处理 TestClient 的 `httpx` 弃用 warning；将响应临时改为 `broken` 并观察断言 FAILED，再恢复为 `ok` | `uv` 管理 Python 项目环境和依赖；Uvicorn 监听端口并把请求交给 FastAPI；FastAPI 按 HTTP Method + Path 匹配路由并调用处理函数；TestClient 不经过真实端口即可调用 ASGI app。404 表示 Path 不存在，405 表示 Path 存在但 Method 不允许；ERROR 表示测试在导入、收集或准备阶段未正常执行，FAILED 表示测试已经执行但断言不满足；liveness 不依赖数据库或 LLM，以免外部故障造成无意义重启。 | `8019397` |

> 上述阶段记录由 Codex 根据学习者真实完成的代码、终端输出和口述整理。提交前由学习者核对；未亲手完成的工作不得计入个人参与。

## 后续阶段记录模板

每完成一个模块，复制下面这一行并替换所有占位内容。文件路径、命令、失败现象和 Commit 必须能够在项目中核验。

| YYYY-MM-DD | 模块名称与目标 | 我亲手创建或修改的精确文件路径；实现了什么 | 我实际运行的命令；关键结果 | 我主动制造或真实遇到的失败；如何定位与恢复 | 我能独立解释的请求链、设计边界和失败语义 | 提交短哈希 |
