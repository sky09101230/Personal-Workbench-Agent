# Personal Workbench Agent

Personal Workbench Agent 是部署在项目机器上的 outbound-only execution client。它提供两个彼此独立的 capability：

- **ProjectActivity Observer**：读取本机项目与手动提供的运行清单，向 `ProjectActivity` 上报真实状态；
- **Paper Research Worker**：由 Codex CLI 使用 Zotero 研究上下文和外部检索生成严格结构化的论文推荐，并写入 Workbench Papers。

它存在的原因是：训练目录、输出和 checkpoint 经常被 `.gitignore` 排除，运行在日常电脑上的 Personal Workbench 无法通过 GitHub 看见这些真实状态。

```text
RTX 5090 / GPU Server                 日常工作电脑

local projects ─┐
                ├─ Workbench Agent ── outbound HTTP ──> Personal Workbench
Codex Research ─┘                                      ├─ ProjectActivity
                                                       └─ Papers / AI Research
```

Personal Workbench **不会 SSH 或主动连接项目机器**。Agent 不接收入站请求、不开放端口，也不启动 FastAPI、Flask 或 WebSocket server。

## v0.1 范围

ProjectActivity Observer v0.1 支持：

- JSON 配置与部署诊断；
- Device heartbeat；
- 配置中的 ProjectSource 幂等上报；
- 手动读取标准 `workbench-run.json` 并上报 ActivityRun；
- Bearer token；
- 无写入的 `doctor` 和 `sync --dry-run`。

Paper Research Worker v0.1 支持：

- 独立 JSON ResearchTask；
- Codex CLI 原生 JSON Schema structured output；
- Agent 侧 ingest schema v1 验证；
- `research run` 与真实研究但不写 Workbench 的 `--dry-run`；
- 复用现有 Bearer HTTP client 写入 Workbench。

Agent 不扫描 Git、`runs/`、输出或 checkpoint，不保存第二份论文数据库，不自动创建 ActivityEvent，也不提供 watcher、scheduler、daemon 或 Windows Service。

仓库还包含一个与 Agent/Workbench 完全解耦的项目级 Codex Skill：**Literature Radar V0**。它读取长期 Research Profile，并用只读 zotero-cli 文献库上下文和外部学术检索生成本地推荐文件；它不会调用 ResearchTask、不会写入 Zotero、也不会上传 Workbench。

## 安装

需要 Python 3.10 或更高版本。

```powershell
cd D:\WHT\workbench_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
workbench-agent --help
```

开发环境可安装测试依赖：

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

也可以直接运行：

```powershell
python -m workbench_agent --help
```

## 配置

在 Agent 项目根目录复制 `config.example.json` 为 `config.json`。不要把真实配置或 token 提交到 Git。

默认配置位置：

```text
<AGENT_PROJECT>\config.json
```

也可以显式指定：

```powershell
workbench-agent doctor
```

配置 contract：

```json
{
  "server": {
    "url": "http://WORKBENCH_HOST:8000",
    "token_env": "WORKBENCH_AGENT_TOKEN"
  },
  "device": {
    "id": "lab-5090",
    "name": "Lab RTX 5090"
  },
  "projects": [
    {
      "key": "semantic-segmentation",
      "project_id": "TODO_PROJECT_ID",
      "path": "D:\\PATH\\TO\\Semantic-Segmentation",
      "source_type": "remote_workspace",
      "source_key": "workspace:semantic-segmentation"
    }
  ]
}
```

- `key` 是 Agent 本地 CLI alias，且必须唯一。
- `project_id` 是 Personal Workbench Todo `Project.id`；Agent 将其视为 opaque string。
- `path` 是这台项目机器上的真实目录。
- `source_key` 是 ProjectSource 的稳定 identity，不应直接使用可能变化的绝对路径。
- `device.id` 是机器的稳定 identity，例如 `lab-5090`。

Agent 启动时会自动读取 `config.json` 同目录下的 `.env`。已有进程环境变量优先，不会被 `.env` 覆盖。token 仍只从 `server.token_env` 指向的环境变量读取：

```powershell
Copy-Item .env.example .env
# 编辑 .env 后直接执行：
workbench-agent doctor
```

Agent 不会输出 token，也不会从示例配置读取真实 secret。所有 HTTP 请求都发送：

```http
Authorization: Bearer <token>
```

## Research task

ResearchTask 与主配置分离，默认目录为：

```text
<AGENT_PROJECT>\research_tasks\
```

仓库中的 `research_tasks/d2nn-recent-papers.json` 是首个任务，可以直接作为默认任务使用；topic、keywords、排除偏好、回溯天数和结果数量均由该 JSON 管理，不硬编码在 Python 中。

现有 Paper Research Worker 仍要求 Codex CLI 登录和 Zotero MCP；独立 Literature Radar V0 不调用该 Worker，并默认通过 zotero-cli 读取个人文献库。

## Literature Radar Skill

项目级 Skill 位于：

```text
.agents/skills/literature-radar/
```

默认长期兴趣配置位于：

```text
research_profiles/d2nn.json
```

在 Codex 中运行：

```text
$literature-radar

使用 research_profiles/d2nn.json。
通过 zotero-cli 读取 Zotero（只读）。
运行一次 Literature Radar。
最多推荐 5 篇。
不要修改 Zotero。
不要上传 Workbench。
把结果保存到 research_outputs/<timestamp>/。
```

Skill 会自动按 PATH → Windows `zotero-cli.exe` → `uv tool dir --bin` 的顺序定位可执行文件，并先执行只读 `zotero-cli config` preflight。成功运行会生成 `result.json` 和 `report.md`。`research_outputs/` 已被 Git 忽略。这个 Skill 不调用 `workbench-agent research run`，也不复用或修改现有 Paper Research Worker。

## 使用

### doctor

```powershell
workbench-agent doctor
```

检查配置、token 环境变量、`/api/health` 和所有项目路径。它只发送 health GET，绝不发送 heartbeat、source 或 run POST。任一检查失败时退出码非零。

### heartbeat

```powershell
workbench-agent heartbeat
```

幂等上报当前 Device。

### sync

```powershell
workbench-agent sync
```

先验证全部本地路径，然后 heartbeat 一次，并为每个配置项目 observe 一次 ProjectSource。返回的 source id 只用于本次进程，不持久化。

预览而不写入：

```powershell
workbench-agent sync --dry-run
```

`--dry-run` 检查路径并显示准备提交的非敏感字段，发送 0 个 HTTP 请求。

### observe-run

```powershell
workbench-agent observe-run `
  --project semantic-segmentation `
  --manifest D:\path\to\workbench-run.json
```

调用顺序固定为：heartbeat → observe source → observe run。用户无需手动提供 source id。该命令不会创建 ActivityEvent。

### research run

先执行完整 Codex、Zotero 与外部论文检索，但不向 Workbench 写入：

```powershell
workbench-agent research run d2nn-recent-papers --dry-run
```

确认推荐质量后执行 ingest：

```powershell
workbench-agent research run d2nn-recent-papers
```

每次新执行会生成唯一 `run_key`；同一次执行只在验证成功后 POST。Codex 输出必须通过 Agent 侧 schema v1、task key、时区、论文数量、分数、URL/标识符等验证，不能直接转发。

## Run manifest contract

v0.1 不猜测各科研仓库的私有文件结构，只接受一个手动指定的中间协议：

```json
{
  "run_id": "exp_034",
  "experiment_name": "baseline",
  "status": "finished",
  "created_at": null,
  "started_at": "2026-08-27T10:00:00+08:00",
  "ended_at": "2026-08-27T13:00:00+08:00",
  "latest_metrics": {
    "loss": 0.132,
    "accuracy": 0.928
  },
  "summary": {
    "epochs": 100
  },
  "config_summary": {
    "learning_rate": 0.001,
    "batch_size": 64
  },
  "relative_path": "runs/exp_034",
  "has_best_checkpoint": true
}
```

`created_at`、`started_at`、`ended_at` 可为 `null`；非空时必须是带时区的 ISO 8601 datetime。Agent 拒绝没有时区的时间，不猜本机时区。metrics、summary 和 config summary 可为 JSON object 或 `null`。

## HTTP contract

Agent 使用 10 秒默认 timeout，访问：

| 方法 | 路径 | v0.1 用途 |
|---|---|---|
| GET | `/api/health` | doctor 连通性检查 |
| POST | `/api/project-activity/devices/heartbeat` | Device upsert |
| POST | `/api/project-activity/sources/observe` | ProjectSource upsert |
| POST | `/api/project-activity/runs/observe` | ActivityRun upsert |
| POST | `/api/project-activity/events` | 仅提供 client primitive，v0.1 service/CLI 不调用 |
| POST | `/api/news/papers/research/ingest` | 写入验证后的 AI Research 推荐 |

HTTP client 与 Personal Workbench 源代码完全解耦。两者唯一共享边界是上述 JSON API。

## 后续方向

后续可分别增加 automatic scheduling、Workbench-managed Research Tasks，以及 feedback / personalization；它们不属于本轮 v0.1。
