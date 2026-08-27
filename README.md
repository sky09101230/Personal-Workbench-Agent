# Personal Workbench Agent

Personal Workbench Agent 是部署在项目机器上的轻量观察客户端。它直接读取本机真实项目与手动提供的运行清单，并通过 HTTP JSON API 主动向 Personal Workbench 的 `ProjectActivity` 上报当前状态。

它存在的原因是：训练目录、输出和 checkpoint 经常被 `.gitignore` 排除，运行在日常电脑上的 Personal Workbench 无法通过 GitHub 看见这些真实状态。

```text
RTX 5090 / GPU Server                 日常工作电脑

local projects
      │
Workbench Agent ── outbound HTTP ──> Personal Workbench
                                           │
                                     ProjectActivity
```

Personal Workbench **不会 SSH 或主动连接项目机器**。Agent 不接收入站请求、不开放端口，也不启动 FastAPI、Flask 或 WebSocket server。尽管名称中有 Agent，它不是 AI/LLM Agent，也不执行自主决策。

## v0.1 范围

v0.1 支持：

- JSON 配置与部署诊断；
- Device heartbeat；
- 配置中的 ProjectSource 幂等上报；
- 手动读取标准 `workbench-run.json` 并上报 ActivityRun；
- Bearer token；
- 无写入的 `doctor` 和 `sync --dry-run`。

它不扫描 Git、`runs/`、输出或 checkpoint，不保存本地状态，不推断状态变化，不自动创建 ActivityEvent，也不提供 watcher、scheduler、daemon 或 Windows Service。

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

复制 `config.example.json`，不要把真实配置或 token 提交到 Git。

默认配置位置：

```text
%USERPROFILE%\.workbench-agent\config.json
```

也可以显式指定：

```powershell
workbench-agent --config D:\path\to\config.json doctor
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

token 只从 `server.token_env` 指向的环境变量读取：

```powershell
$env:WORKBENCH_AGENT_TOKEN="replace-with-real-token"
```

Agent 不会输出 token，也不会从示例配置读取真实 secret。所有 HTTP 请求都发送：

```http
Authorization: Bearer <token>
```

## 使用

### doctor

```powershell
workbench-agent --config D:\path\to\config.json doctor
```

检查配置、token 环境变量、`/api/health` 和所有项目路径。它只发送 health GET，绝不发送 heartbeat、source 或 run POST。任一检查失败时退出码非零。

### heartbeat

```powershell
workbench-agent --config D:\path\to\config.json heartbeat
```

幂等上报当前 Device。

### sync

```powershell
workbench-agent --config D:\path\to\config.json sync
```

先验证全部本地路径，然后 heartbeat 一次，并为每个配置项目 observe 一次 ProjectSource。返回的 source id 只用于本次进程，不持久化。

预览而不写入：

```powershell
workbench-agent --config D:\path\to\config.json sync --dry-run
```

`--dry-run` 检查路径并显示准备提交的非敏感字段，发送 0 个 HTTP 请求。

### observe-run

```powershell
workbench-agent --config D:\path\to\config.json observe-run `
  --project semantic-segmentation `
  --manifest D:\path\to\workbench-run.json
```

调用顺序固定为：heartbeat → observe source → observe run。用户无需手动提供 source id。该命令不会创建 ActivityEvent。

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

HTTP client 与 Personal Workbench 源代码完全解耦。两者唯一共享边界是上述 JSON API。

## 后续方向

基础链路经过真实联通验证后，可以分别增加 run manifest scanner、Git observer、本地 previous state、observation diff → ActivityEvent，以及 scheduler/daemon。它们不属于 v0.1。
