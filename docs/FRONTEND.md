# Stage 9 React 操作台

Stage 9 把已经可查询、可恢复的后端 Run 变成一个本地可操作的产品闭环。它是 React + TypeScript + Vite 的申请工作台：既能创建一次申请，也能在当前 workspace 中查看、搜索和分页浏览已保存的岗位；它仍不是账号系统或生产部署。

## 用户流程

```text
职位标题与描述 + 证据文档
→ 创建 Job
→ 创建 Document
→ 摄取并切分 Document
→ 使用单一 Idempotency-Key 启动 Run
→ 打开可恢复的 Run URL
→ queued/running 轮询
→ 成功查看材料、引用和 gap
   或失败后从 checkpoint 恢复
```

创建链会保存每个成功步骤返回的 ID。失败后只重试当前步骤，不重做前面的写入；启动请求结果未知时仍复用同一个幂等键。Job 与 Document 的创建接口本身没有幂等合同，因此连接中断后的手动重试会明确提示可能产生重复记录。

岗位列表是一个独立的只读入口：页面地址为 `/workspaces/:workspaceId/jobs?q=Python&page=1`。提交搜索、翻页或切换 workspace 时，页面会取消过期请求并只显示最新条件的结果；手动刷新同一页失败时保留最后一次可信列表，并提供重试按钮。它不自动轮询，避免把浏览岗位变成持续网络请求。

## 页面与模块

- `/`：创建页，收集 workspace、职位和证据，并展示四步写入状态。
- `/workspaces/:workspaceId/jobs`：当前 workspace 的已保存岗位页；支持标题搜索、上一页/下一页、加载、空结果、错误重试和手动刷新。查询条件保存在 URL，刷新或复制链接不会丢失。
- `/workspaces/:workspaceId/runs/:runId`：Run 页，可直接刷新或分享本地路径；展示状态、尝试次数、Event、Artifact、引用原文、gap 与恢复入口。
- `src/api/`：镜像后端 snake_case DTO，封装 fetch、脱敏错误和全部 Stage 9 API。
- `src/state/workbenchReducer.ts`：创建链状态机、输入快照、已完成响应和幂等键。
- `src/hooks/useJobs.ts`：负责岗位列表的 abort、过期响应丢弃、首次加载、刷新保留旧数据与重试。
- `src/hooks/useRunPolling.ts`：请求完成后再安排下一次轮询；页面隐藏、路由变化和卸载时取消；终态停止。
- `src/components/`：纯展示状态、时间线、Artifact、引用检查器和错误提示。

Run 页只相信后端提供的 `citation_sources`、`terminal_validation` 与 `can_resume`。前端不会自行跨 workspace 查询引用、猜测租约是否过期或从开放的 Event JSON 推导安全决定。未知 Event 只显示安全的 “System event”，不会渲染原始数据。

## 本地运行

后端使用默认 Mock Provider：

```text
cd backend
uv run uvicorn app.main:app --reload
```

前端：

```text
cd frontend
npm install
npm run dev
```

开发期 `/api` 由 Vite 代理到 `http://127.0.0.1:8000`。Docker Compose 已提供同源 Nginx `/api` 代理的本地演示环境；跨来源 CORS、PostgreSQL migration、生产 Secret 与公开部署仍不在这个前端切片内。

## 验收

```text
cd frontend
npm test
npm run typecheck
npm run lint
npm run build
```

三个 MSW smoke case 固定为：

1. 有可信证据：完整创建链，running → succeeded，引用可展开，终态停止轮询。
2. 无可信证据：Run 成功但不生成 claim/citation，明确显示 evidence gap。
3. 可恢复失败：failed + `can_resume`，只 POST 一次 Resume，attempt 2 成功后停止轮询。

另有两个展示层测试确认 `validation_failed` 和永久 `failed` 都不会错误显示 Resume。

岗位列表另有三个 MSW 测试：搜索和分页携带正确的 URL 参数、刷新失败时保留可信旧数据并可重试、首次加载失败时展示重试入口。

这些测试默认不连接真实后端或 OpenAI。后端合同和完整生产链仍由 pytest 与 Stage 8 evaluator 独立回归。

## 安全与当前边界

- 不把证据正文、Artifact 或引用原文写入浏览器持久存储。
- 网络轮询失败时保留最后一次可信快照，不伪造业务失败。
- `validation_failed` 是安全拦截终态，不是普通 HTTP 错误，也不展示未发布 Artifact。
- `current_node` 只表示最后完成的 checkpoint，不当作实时进度百分比。
- 目前没有认证、授权 UI、文件上传、Run 历史列表、WebSocket 或 durable worker；岗位列表也不是跨 workspace 的搜索或协作共享功能。
- 真实 OpenAI live smoke 仍按决定延期；Stage 9 的产品闭环只在 deterministic Mock 下验收。
