# Docker 一日版本

本配置把 Agent Platform 打包为可重复构建的本地演示环境。它固定使用 Deterministic Mock Provider，不读取 OpenAI API key，也不把本地 `.env`、虚拟环境、依赖目录或 SQLite 数据库复制进镜像。

## 运行拓扑

```text
Browser http://127.0.0.1:8080
  -> frontend: non-root Nginx :8080
       -> /api/* -> backend:8000
       -> /*     -> React SPA
  -> backend: non-root FastAPI/Uvicorn, one worker
       -> /data/agent-platform.db
  -> agent_data: Docker named volume
```

只有 frontend 发布到宿主机回环地址。浏览器对页面和 API 使用同一 origin，因此该本地切片不需要放宽 CORS。Compose 中的 `backend` 是容器网络 DNS 名称，只能由其他容器解析。

## 前置条件

- Docker Engine 或 Docker Desktop
- Docker Compose v2（命令形式为 `docker compose`）
- 运行自动 smoke 时还需要 `bash` 和 `curl`

## 启动

直接启动：

```bash
docker compose up --build --wait
```

打开 <http://127.0.0.1:8080>。如需修改宿主机端口：

```bash
cp .env.example .env
# 编辑 AGENT_PLATFORM_HTTP_PORT 后重新启动
```

`.env` 只用于 Compose 插值，不会被复制进镜像或自动注入容器。当前 Compose 显式强制后端使用 `mock`。

## 自动 smoke

```bash
./scripts/docker-smoke.sh
```

脚本会：

1. 检查 Docker、Compose v2、daemon 和 curl；
2. 验证 Compose 配置；
3. 从无构建缓存的上下文构建两个镜像；
4. 启动并等待两个服务健康；
5. 从 frontend 的真实发布端口验证代理健康接口和 SPA 深链接；
6. 验证两个运行容器都不是 UID 0；
7. 用宿主哨兵确认 `.venv` 和 `node_modules` 没有被复制进镜像；
8. 检查容器没有注入 API key/token/secret/password，并扫描本次启动后的日志是否含 traceback、权限错误或疑似凭据。

成功后脚本会保留服务，供浏览器完成业务验收；失败时会打印脱敏日志，但不会删除容器或数据卷。

## 数据持久化验收

1. 在浏览器完成 Job → Document → ingestion → Run → Artifact，并保存 Run 详情 URL。
2. 执行 `docker compose restart`，刷新原 URL，确认 Run 和 Artifact 仍可读取。
3. 执行普通停止和重新创建：

   ```bash
   docker compose down
   docker compose up -d --wait
   ```

4. 再次刷新原 URL，确认终态数据仍存在。

普通 `docker compose down` 会保留 named volume。以下命令会永久删除本地演示数据，只能在明确需要清空环境时使用：

```bash
docker compose down -v
```

## 当日验收门禁

以下结果在 2026-09-07 的 Apple Silicon macOS、Docker Desktop 4.89.0、Engine 29.7.2 与 Compose v5.5.0 上实测通过：

- [x] `docker compose config --quiet` 成功。
- [x] 两个镜像从干净上下文构建，不依赖宿主 `.venv`、`node_modules`、`dist` 或数据库。
- [x] `docker compose up --build --wait` 后 backend/frontend 均为 healthy。
- [x] 从 frontend 发布端口访问 `/api/v1/health/live` 返回 `200 {"status":"ok"}`。
- [x] 浏览器完成 Job → Document → ingestion → Run → Artifact。
- [x] 直接刷新 Run 深链接仍可打开 React 页面。
- [x] 普通 `down/up` 后原 Run 和 Artifact 仍可读取，named volume 保持不变。
- [x] backend/frontend 分别以 UID 10001 和 101 运行。
- [x] 完整业务流程及容器重建后的日志没有 traceback、权限错误或疑似 Secret，浏览器控制台没有 warning/error。
- [x] 原有 Uvicorn/Vite 开发方式继续可用；后端 `235 passed, 1 skipped`、Ruff lint 和 lockfile 通过，固定 evaluator 3/3；前端 `5 passed`，类型检查、ESLint 和 build 通过。

## 当前边界

- SQLite、`create_all()` 与单 Uvicorn worker 只用于本地单实例；这不是 PostgreSQL migration 或多副本部署。
- 现有 liveness 只证明 FastAPI 进程响应，不检查数据库，因此不等于生产 readiness。
- FastAPI `BackgroundTasks` 不是 durable worker。只承诺已经完成的 Run/Artifact 在容器重建后仍存在；执行中断的 Run 可能需要等待租约过期后手动 Resume。
- 当前不包含真实 OpenAI、Secret 注入、认证授权、TLS/域名、Kubernetes、CI/CD、备份或可观测平台。
