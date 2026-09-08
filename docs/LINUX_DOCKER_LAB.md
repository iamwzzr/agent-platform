# Linux 与 Agent Platform Docker 实操

目标：能自己启动服务、查看日志和端口、读懂并修复文件权限、按层定位连接失败，并解释容器网络、数据卷和非 root 运行。建议预留 45–60 分钟，先手动完成，再运行自动检查。

本机是 macOS，Docker Desktop 在 Linux 虚拟机中运行本项目的 Linux 容器。下面的 `uname`、`ps`、`netstat`、`chmod` 等在容器内执行；本轮覆盖容器内 Linux 操作，不包括 Linux 主机安装、SSH、systemd 或防火墙管理。

## 1. 启动服务并确认入口（5 分钟）

在项目根目录的终端执行：

```bash
cd /Users/wzr/Documents/ChatGPT/Codex/setting/agent-platform
docker compose config --quiet
docker compose up -d --no-build --wait --wait-timeout 60
docker compose ps
docker compose port frontend 8080
curl --noproxy '*' -i --max-time 5 http://127.0.0.1:8080/api/v1/health/live
```

预期：两个服务均为 `healthy`，发布端口为 `127.0.0.1:8080`，HTTP 返回 `200` 和 `{"status":"ok"}`。这里复用现有镜像；首次尚未构建或修改应用代码后，改用 `docker compose up -d --build --wait`。

当前请求路径：

```text
浏览器 / curl（Mac）
  → 127.0.0.1:8080
  → frontend 容器的 Nginx :8080
  → /api/* 代理到 backend:8000
  → backend 容器的 FastAPI
  → /data/agent-platform.db → agent_data 数据卷
```

`up` 创建或启动服务，`-d` 让服务在后台运行，`--wait` 等待健康状态。`Up` 只说明容器进程存在；本项目的 `healthy` 检查还要求 HTTP 可访问，但 liveness 不验证数据库或模型质量。

完成标志：能找到真实发布端口，并说出为什么从浏览器访问后端要走 `8080/api`。

## 2. 查看 Linux 用户、进程、日志和端口（10 分钟）

```bash
docker compose exec backend sh
```

进入后端容器后逐条运行，再用 `exit` 返回 Mac：

```sh
uname -srm
pwd
id
ls -ldn /data
ls -ln /data/agent-platform.db
exit
```

然后在 Mac 终端运行：

```bash
docker compose exec -T frontend sh -c 'id; ps; netstat -lnt'
docker compose logs --tail=30 --timestamps backend frontend
docker compose logs --follow --tail=10 backend
```

最后一个命令持续跟随日志。在另一个终端请求一次健康接口，观察新增的 `GET ... 200`；按 `Ctrl+C` 退出日志跟随，服务会继续运行。`-T` 用于脚本，关闭交互终端分配。

本项目的后端 UID/GID 为 `10001:10001`，前端为 `101:101`。`netstat -lnt` 查看监听中的 TCP 端口，前端应出现 `0.0.0.0:8080`。精简的后端镜像未安装 `ss`，不能把 `ss: not found` 当作没有端口监听；可以用前端镜像自带的 `netstat`，结合后端 HTTP 探测验证链路。

完成标志：能把一次请求与日志中的路径和状态码对应起来，能区分进程是否存在、端口是否监听、HTTP 是否成功三个检查。

## 3. 复现一次连接失败并修复（10 分钟）

故意从前端容器访问其自身的 8000 端口：

```bash
docker compose exec -T frontend wget -T 3 -qO- http://127.0.0.1:8000/api/v1/health/live
```

预期出现 `Connection refused`。此处 `127.0.0.1` 指前端容器自身，它没有服务监听 8000。改为 Compose 服务名：

```bash
docker compose exec -T frontend wget -T 3 -qO- http://backend:8000/api/v1/health/live
```

应返回 `{"status":"ok"}`。查看两端是否在同一网络：

```bash
docker inspect --format '{{json .NetworkSettings.Networks}}' agent-platform-frontend-1
docker inspect --format '{{json .NetworkSettings.Networks}}' agent-platform-backend-1
docker inspect --format '{{json .NetworkSettings.Ports}}' agent-platform-backend-1
```

默认网络名为 `agent-platform_default`，内部 DNS 用 `backend` 服务名解析地址。后端的 `8000/tcp: null` 表示没有宿主机端口映射；`EXPOSE`/Compose `expose` 不会自动发布端口。不要把易变的容器 IP 写死到前端配置。[Docker Compose 网络说明](https://docs.docker.com/compose/how-tos/networking/)

排查时按顺序问：从哪台主机/哪个容器发起？域名能否解析？目标端口有无监听？代理能否连接上游？最后才检查业务接口。

| 现象 | 优先检查 | 本轮状态 |
| --- | --- | --- |
| `bad address` / 无法解析主机 | 服务名拼写、是否加入共享 Docker 网络 | 自动练习已复现并恢复 |
| `Connection refused` | 请求地址对应哪个容器、目标端口是否监听 | 手动命令及自动练习已复现并恢复 |
| 超时 | 网络路径、防火墙、服务响应是否卡住 | 解释项，本轮未注入 |
| HTTP 502 | Nginx 日志、上游服务名、端口及后端进程 | 解释项，本轮未注入 |
| HTTP 404 | 路径与路由是否匹配 | 说明 HTTP 服务已响应，继续查接口路径 |

完成标志：看到连接失败时，先定位失败层；能解释为什么修改 URL 就能恢复这次连接。

## 4. 在临时目录里处理权限（10 分钟）

下面只操作前端容器中新建的 `/tmp` 目录。进入前端容器：

```bash
docker compose exec frontend sh
```

在容器里逐条执行，观察第三条之后的失败；不要整段放进 `set -e` 脚本：

```sh
practice_dir=$(mktemp -d /tmp/agent-permissions.XXXXXX)
id
chmod 500 "$practice_dir"
ls -ldn "$practice_dir"
touch "$practice_dir/result.txt"
```

预期 `Permission denied`。当前用户拥有目录，但模式 `500` 没有写权限。修复并验证：

```sh
chmod 750 "$practice_dir"
touch "$practice_dir/result.txt"
ls -ldn "$practice_dir"
ls -ln "$practice_dir/result.txt"
rm -- "$practice_dir/result.txt"
rmdir -- "$practice_dir"
exit
```

`r/w/x` 的数值为 `4/2/1`；`750` 对应所有者 `rwx`、同组 `r-x`、其他用户无权限。对于目录，`x` 表示可以进入/遍历，创建文件通常需要目录的 `w+x`。`chmod` 改权限位，`chown` 改所有者和组。

自动练习还覆盖另一种情况：root 创建 `700` 目录，UID 101 无法写入；临时 root 进程只对练习目录执行 `chown 101:101` 与 `chmod 750`，之后回到 UID 101 验证可写。实际应用 `/data` 的权限不作改动。

非 root 运行限制进程能修改的资源。后端对 `/data` 有明确的写权限，因此 UID 10001 仍能使用 SQLite；修复权限应该对准所需目录与 UID/GID。运行整个服务为 root 或开放 `777` 会扩大权限范围。[Docker 容器用户说明](https://docs.docker.com/engine/containers/run/)

完成标志：在修复前读出 UID/GID 和模式，说明应改所有者还是权限位，修复后再次用非 root 身份验证。

## 5. 验证数据卷并运行完整练习（10 分钟）

查看现有后端 `/data` 挂载：

```bash
docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Type}} {{.Name}} -> {{.Destination}}{{end}}{{end}}' agent-platform-backend-1
```

默认得到 `volume agent-platform_agent_data -> /data`。容器可写层随容器删除而丢失，named volume 独立保存；所以必须通过删除并重新创建容器来验证持久化，仅执行 `restart` 不能证明这一点。普通 Compose `down` 保留 named volume，`down -v` 会删除数据卷。[Docker 数据卷说明](https://docs.docker.com/engine/storage/volumes/)

运行本次新增脚本：

```bash
bash scripts/docker-ops-lab.sh
```

脚本使用已有镜像，依次执行 8 项检查：启动/健康、Linux 观察、端口/HTTP/日志、错地址恢复、缺少网络恢复、权限恢复、容器重建持久化、现有应用数据/健康复核。所有故障在探测请求或独立短生命周期容器中制造。每次练习使用唯一标签和独立 volume；退出时只清理本次拥有的练习资源，应用数据卷不参与写入或删除。

预期失败会显示 `Expected failure`，这是故障复现成功；末尾应显示 `8/8 exercises passed` 且退出码为 0。其他失败会以非零退出。日志输出做常见凭据模式脱敏，但这不是完整的敏感信息审计器。已有 `scripts/docker-smoke.sh` 仍负责镜像干净构建与部署验收；本脚本负责运维练习。

## 本轮实际结果（2026-09-08）

- 环境：macOS 宿主机，Linux `7.0.12-linuxkit aarch64` 容器。
- 8 项自动实操全部通过，两个现有服务保持 healthy。
- 前端 UID 101、后端 UID 10001；对外入口 `127.0.0.1:8080`，后端无宿主机端口映射。
- 3 类故障已复现并恢复：错误 loopback 地址、缺少共享网络、UID/目录权限不匹配。
- 临时容器重建后 volume 标记保留，旧容器 `/tmp` 标记消失；专用练习数据卷已清理。
- 现有数据库在本轮前后均为 1 个 Job、1 个 Run、1 个 Artifact，最终健康接口返回 200。

这记录的是 Codex 已执行并验证的演练。个人熟练度需要你脱离提示再完成一次，并解释下面的问题：

1. 前端容器里的 `127.0.0.1:8000` 为什么失败，而 `backend:8000` 成功？
2. `ps` 有进程、端口在监听、HTTP 返回 200，各自能证明什么？
3. `chmod` 和 `chown` 分别解决什么问题？为什么修复后要以非 root 用户验证？
4. `restart` 与删除重建容器有什么区别？数据库为什么要放在 named volume？
5. 如果页面能打开但 API 返回 502，你按什么顺序查看哪些证据？
