# Agent 配置、操作与产出核验指南

Agent Platform 把一条 JD 和你提供的经历资料处理成一个带引用的材料包。当前版本是本地单机演示：固定六节点编排，默认 Mock，无登录和成员权限。它适合演示结构化输出、证据引用、校验、运行恢复与计数，不代表已验证真实模型的求职效果。

## 一次运行具体做什么

| 节点 | 输入 | 当前处理与输出 |
| --- | --- | --- |
| `extract` | JD 正文 | 按换行或英文句末拆分，超过 800 字符继续切片，保留最多 20 条；首条优先级 high，其余 medium。输出要求列表。 |
| `retrieve` | 要求、workspace、选定 Document ID | 对每条要求执行词频余弦检索，取最多 5 个正分片段；核对来源、位置和数据库原文，生成最多 800 字符的证据摘录。 |
| `draft` | 要求和证据 | Provider 输出一个结构化材料包草稿，包含要求、claims、简历要点、缺口和引用。 |
| `validate` | 草稿、可信要求和证据 | 用程序检查引用范围、逐字对应、要求覆盖、重复标识及不支持的内容，输出校验结果。 |
| `revise` | 草稿、校验问题、原要求和原证据 | Provider 重新生成草稿，再次校验；默认最多 2 轮，不重新提取或检索。 |
| `terminal` | 最后一次校验结果 | 通过则 `succeeded` 并发布一个材料包；否则 `validation_failed`，不发布草稿。 |

正常路径是 `extract → retrieve → draft → validate → terminal`，修订分支是 `validate → revise → validate`。六个节点属于一个固定 Agent 工作流；仅 draft 和 revise 调用 Provider，模型不会自主选工具，也没有多个 Agent 分工协作。

提取节点不会理解语义或判断真正的重要程度。检索把词频组成向量后计算余弦相似度，没有调用语义 embedding 模型或向量数据库。相似度大于零不等于经历满足职位要求；连续中文会被当前分词方式当成较长 token，同义表达和中文召回尤其需要人工检查。

每个完成节点保存 checkpoint 和事件。`current_node` 表示最后完成的节点，不是实时进度百分比。暂时的 Provider 故障有独立重试；解析不出结构化输出等错误可能直接成为 `failed`，不会自动进入业务修订分支。能否恢复以 Run 返回的 `can_resume` 为准。

## Agent 怎样配置

Agent 的行为不仅是“选一个模型”，还由以下代码合同组成：

| 配置维度 | 当前实现位置与内容 |
| --- | --- |
| 编排与状态 | `backend/app/agent/graph.py` 定义节点、条件路由和修订预算；`state.py` 保存 requirements、evidence、artifact、validation、node_trace 等共享状态。 |
| 依赖与工具 | `backend/app/application_executor.py` 绑定规则提取、检索器、证据 verifier、Provider 和 validator；它们由程序调用，不是模型自由选择的工具列表。 |
| 模型指令 | `backend/app/openai_provider.py` 的 `draft_artifact` / `revise_artifact` 分别定义起草和修订的 system 指令；要求仅使用提供的要求与证据，不编造事实或引用。Mock 不执行这些提示词。 |
| 每次输入 | 起草发送 run_id、requirements、evidence；修订额外发送上一版 artifact 与 validation 反馈。 |
| 输出和发布门禁 | `backend/app/schemas/artifact.py` 定义 ApplicationArtifact 结构；`backend/app/validation.py` 执行独立发布校验。提示词约束不能代替程序校验。 |

目前没有网页 Prompt 编辑器、工具市场、temperature 配置或多 Agent 角色配置；这些不应被描述成已经实现的能力。

本地后端从工作目录的 `.env` 和进程环境读取配置。按 README 从 `backend/` 启动时，对应 `backend/.env`；进程环境变量优先。配置是部署级设置，前端只能查看，修改后需要重启后端。

| 设置 | 默认与范围 | 用途 |
| --- | --- | --- |
| `AGENT_PLATFORM_LLM_PROVIDER` | `mock`；可选 `mock` / `openai` | 选择生成 Provider。 |
| `AGENT_PLATFORM_OPENAI_API_KEY` | 默认无；OpenAI 模式必填 | 服务端模型凭据，不粘贴进 JD、证据或前端页面。 |
| `AGENT_PLATFORM_OPENAI_MODEL` | 默认无；OpenAI 模式必填 | 明确指定要使用的模型 ID。 |
| `AGENT_PLATFORM_AGENT_MAX_REVISIONS` | `2`；0–5 | 草稿通过结构解析但未通过业务校验时，最多修订几轮。设为 0 即仅起草和校验。 |
| `AGENT_PLATFORM_PROVIDER_RETRY_MAX_ATTEMPTS` | `3`；1–5 | 每次 Provider 调用因临时错误而尝试的总次数，包含首次调用。 |
| `AGENT_PLATFORM_PROVIDER_RETRY_INITIAL_DELAY_SECONDS` | `0.5` 秒；0–60 | 临时错误重试的初始退避延时，后续按退避规则增加。 |

默认最多一次起草加两次修订，最多调用三次生成操作。每个生成操作默认又最多尝试三次，但材料仍属于同一个 Run，不会因此变成九份材料。额度不足、鉴权失败和无效结构响应等错误不会按普通临时错误一直重试。

Mock 的模型标识是 `deterministic-mock-v1`。它不调用模型：每条有证据的要求选择最高分摘录，复制为一条 claim 和一条简历要点；无证据则输出 gap。切换到 OpenAI 后，draft/revise 使用 Responses 结构化输出，但真实连接、费用和输出质量尚未验证，不能将 Mock 的稳定结果当成真实模型效果。

当前 validator 要求 claim 逐字等于证据摘录，简历要点逐字等于其引用的 claim。`cover_letter` 虽存在于结构中，任何非空求职信都不能通过发布校验。因此即使配置真实模型，也不等于启用了自由润色、完整简历或求职信生成；模型改写原文可能导致校验失败。这是当前输出合同的限制。

Docker Compose 显式强制 `AGENT_PLATFORM_LLM_PROVIDER=mock`，且数据库位于独立的 named volume。修改本地 `backend/.env` 不会切换容器 Provider，也不会修改容器中的使用记录。Docker 和本地进程应分别打开概览核对配置。

## 平台怎样用

先按 [README 快速开始](../README.md#快速开始) 启动本地前后端，或使用 Docker。开发地址是 `http://127.0.0.1:5173`，Docker 地址是 `http://127.0.0.1:8080`。

1. 打开 `/` 创建页，选择一个自己能识别的 workspace，例如 `my-application-review`。workspace 仅是资源过滤标识；不要把地址可访问性当成账号权限。
2. 填写职位标题，粘贴要评估的真实 JD 原文。当前规则最多保留 20 条、每条 800 字符；如果描述包含大量公司介绍，运行后应检查要求列表是否遗漏实际要求，不要假设模型已经理解全部正文。
3. 填写证据名称，粘贴你自己的履历、项目过程、结果或作品说明。只写能够核对的经历，尽量保留完整事实和上下文。创建页支持纯文本，不支持 PDF/Word 上传；网页链接本身不会自动抓取内容。
4. 提交后，页面依次执行保存 Job、保存 Document、摄取并分块 Document、启动 Run。每一步成功后记录其 ID；摄取完成才启动生成。当前创建页一次提交一份证据 Document，底层 Run API 支持选择 1–100 份已有资料。
5. 启动返回 `202 Accepted` 后进入 `/workspaces/{workspace_id}/runs/{run_id}`。等待 queued/running 进入终态，查看节点事件、尝试次数和校验信息。可保存本地 Run URL，刷新继续查看；不要把接收成功视为材料生成成功。
6. 若 succeeded，检查 Artifact 的要求、简历要点、gap 和引用原文。特别检查证据是否真能说明你满足要求，是否包含不宜公开的内容。仅有 gap 也可能是成功结果，此时要补充自己的证据，而不是把缺口当作生成了可投递材料。
7. 若 validation_failed，阅读校验问题；系统不会发布未通过的草稿。若 failed 且 `can_resume=true`，使用恢复入口；网络状态未知时复用原请求的幂等键。Job/Document 创建接口没有同等的幂等保证，创建阶段的未知结果重试可能留下重复记录。
8. 打开 `/workspaces/{workspace_id}/overview` 核对配置和实际产出，或去 `/workspaces/{workspace_id}/jobs` 搜索已保存的岗位。概览统计随数据变化；历史 Run 自己记录的 provider/model 才是该次运行身份，当前配置卡不能替代历史信息。

产物目前在页面中阅读和核对。没有完整简历版式导出、自动职位搜索或自动投递；引用通过也不能替代使用前的人工审核。

## 概览页与 API 返回什么

页面地址是 `/workspaces/{workspace_id}/overview`，对应只读接口：

```text
GET /api/v1/workspaces/{workspace_id}/overview
```

接口返回当前部署的公开配置白名单、生成时间和该 workspace 的使用统计。配置包括 provider/model、修订上限、重试参数、检索方法与 Top-K；不会返回 API key、数据库地址、环境变量全集、JD、证据正文或材料内容。统计查询不会启动 Run 或发起模型调用。

该接口有 workspace 资源范围过滤，但没有登录或成员权限控制。当前服务仅用于本地单机演示，不应把它直接当成可公开存放私人履历的生产服务。

## 多少 JD 产生几份材料

| 计数 | 准确定义与注意事项 |
| --- | --- |
| 已保存 JD | Job 记录数，不等于去重后的真实职位数；重复创建也会增加。 |
| 参与运行的 JD | 至少有一个 Run 的不同 Job 记录数。 |
| Run | 一次工作流执行记录；一个 JD 可以有多个 Run。原 Run 恢复和同幂等键复用不会新建记录。 |
| 成功 Run | 到达 succeeded 的执行记录；允许输出只有 gap 的包。 |
| 发布材料包 | ArtifactRecord 数，每个成功 Run 最多一个；失败和校验失败不会发布。 |
| 有发布包的 JD | 至少有一个已发布包的不同 Job 记录数；不能和包数互换。 |
| 含简历要点的包 | 至少一条 resume bullet 的包，仍需人工检查是否可用。 |
| 仅缺口包 | 简历要点和 claim 均为空、无求职信但有 gap 的包；这是已记录的资料缺口。 |
| 简历要点 / gap | 包内条目总数，不是文件数、职位数或独立材料包数。 |
| Mock / OpenAI Run | 根据各 Run 保存的 provider 分开统计；真实模型运行数量也不等于已测质量。 |

概览的发布包计数只接受 succeeded Run 下、存储校验标记为通过、结构能解析且 run_id 对应的记录；格式损坏的历史记录会被排除。统计过程不重新做语义判断，也不能代替逐条查看产物。

例子：一个 JD 发起两次不同 Run，两次都成功，可产生两个包；每包五条要点，则是一个 JD、两次 Run、两个包、十条要点。第二个包如果只有 gap，仍计一个成功包，但不计入含简历要点的包。

2026-09-09 对原始 3 条演示数据完成只读核验后，将三个指定 workspace 各补到 100 条 JD。297 条新增记录均是明确标记的合成演示数据；它们没有 Run 或材料包：

| 数据来源 / workspace | 已保存 JD 记录 | 成功 Mock Run | 发布包 | 要点 | gap | 求职信 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Docker / `docker-acceptance` | 100 | 1 | 1 | 1 | 0 | 0 |
| 本地 SQLite / `test-grounded` | 100 | 1 | 1 | 1 | 0 | 0 |
| 本地 SQLite / `test-gap` | 100 | 1 | 1 | 0 | 1 | 0 |

合计口径：300 条已保存 JD、3 条参与运行的 JD、3 次成功 Mock Run、3 个包、2 个含简历要点的包、1 个仅 gap 包、2 条要点、1 个 gap、0 封求职信。三组记录属于两个数据库部署中的三个 workspace，不能描述为 300 个真实职位或 300 次 Agent 处理。冻结的 `smoke-v1` 三个 case 是另一套合成离线回归，也不是用户处理量。当前没有证据支持节省时间百分比、命中率提升或求职成功率等结论。

## 300 条演示 JD 怎样生成

仓库中的 `scripts/seed-demo-jobs.py` 只允许操作 `docker-acceptance`、`test-grounded` 和 `test-gap` 三个演示 workspace。默认是 dry-run；只有显式提供 `--apply` 才提交。它在事务中补到目标数量，已有数量超过目标时拒绝删除，稳定 ID 使重复运行保持 0 新增。

本地数据库先预览、再写入：

```bash
python3 scripts/seed-demo-jobs.py \
  --database backend/agent-platform.db \
  --workspace test-grounded \
  --workspace test-gap

python3 scripts/seed-demo-jobs.py \
  --database backend/agent-platform.db \
  --workspace test-grounded \
  --workspace test-gap \
  --apply
```

Docker 演示库位于容器数据卷，先临时复制同一脚本，再预览和写入：

```bash
docker compose cp scripts/seed-demo-jobs.py backend:/tmp/seed-demo-jobs.py
docker compose exec -T backend python /tmp/seed-demo-jobs.py \
  --database /data/agent-platform.db \
  --workspace docker-acceptance
docker compose exec -T backend python /tmp/seed-demo-jobs.py \
  --database /data/agent-platform.db \
  --workspace docker-acceptance \
  --apply
```

脚本直接写 Job 表，因此它是受控的本地演示数据工具，不是生产数据导入 API。每条新增正文以 `SYNTHETIC DEMO DATA` 开头；不要删除该标记或把这些记录计入真实模型实验。

## 怎样建立自己的评测台账

先确定你要评估的是完整流程是否可靠、检索是否找到正确资料，还是最终要点是否适合使用。三者应分别记录，避免把无异常运行误当成内容质量。保留冻结的 `smoke-v1`；新增自有样本应使用新的独立版本，不能改写既有三个合成 case 来提高分数。

1. 选择你有权使用的真实 JD 与个人资料，为每组分配匿名样本编号。记录 JD 来源及日期、资料版本，人工标注每条要求的相关原文和预期 gap；不要把“没有在资料中找到”标成“这个人没有该技能”。
2. 在运行前固定样本和判定规则，例如引用是否对应原文、是否遗漏预期证据、缺口是否正确、要点是否能直接使用或需要修改。真实模型与 Mock 分列；模型、配置或资料变化后另建实验批次。
3. 逐条运行，保留 workspace、Job ID、Run ID、provider/model、终态、修订次数、包数、要点数和 gap 数。失败也记入台账，并保留错误类别；不能只统计成功样本。
4. 对每个发布包人工核对原始证据与职位要求，给出“可用 / 需修改 / 不可用”及理由。分别计算运行成功率、含要点包比例、标注证据召回、缺口判断准确率和人工可用率；报告分子、分母和不适用项。
5. 要报告提升，先用相同样本、相同规则建立可复现基线，再比较改进版本。时间或费用目前没有完整产品统计，若自行实测，应记录测量方法和失败开销；没有配对数据就不填写提升率。

可用的最小台账字段：

| 字段组 | 建议内容 |
| --- | --- |
| 样本与版本 | 匿名 sample_id、JD 来源日期、资料版本、数据集版本 |
| 运行身份 | 部署、workspace、Job ID、Run ID、provider、model、修订/重试配置 |
| 结果计数 | 终态、发布包数、要点数、gap 数、是否仅缺口 |
| 人工核验 | 引用原文是否一致、语义是否相关、预期证据是否遗漏、可用性和修改理由 |
| 比较依据 | 基线批次、评测规则、实际测量时间/费用及其来源（如已测） |

台账使用匿名 ID，把 JD/履历正文与可公开的统计报告分开保管；截图和演示数据移除联系方式、住址、客户机密与凭据。OpenAI 模式会把选出的要求和证据发往模型服务，应只选有权提供的资料。当前 workspace 过滤没有成员授权能力，分享本地页面地址不构成受控协作。

## 可以怎样介绍这个项目

“我实现了基于 LangGraph 的固定六节点求职材料工作流，把 JD、证据检索、结构化输出、引用校验、最多两轮默认修订、节点级恢复和运行统计串成了本地可演示的闭环。默认 Mock 做可重复回归，OpenAI adapter 与它分离。当前校验保证逐字证据对应与结构约束，语义相关性和源资料真实性仍需人工检查。”

这段表述对应现有实现。不要将其扩写为多 Agent 自主规划、语义向量检索、事实真实性保证、完整简历与求职信自动生成、大规模真实用户验证或生产级 ML 平台。
