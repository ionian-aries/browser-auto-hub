# OA 流水线 CURL 调用手册

> 三个最常用场景的即用 curl：**主动触发 todos 采集**、**主动触发 forward 转发**、
> **创建每 5 分钟采集 todos 的定时调度**。每个入参的含义与必填性见各节表格。
> Base URL 缺省 `http://localhost:8900`（docker 部署用 `8901`）。
> 更完整的说明（调试参数、SSE 日志、失败语义）见 `OA流水线API触发指南.md`。

## 1. 主动触发 todos（OA 沟通待办采集）

采集待办列表 → 提取元数据与附件 → 写入 `inbox_documents` 表（按 `task_id` 去重）。
**异步**：立即返回 `201` + `id`，后台执行；用 §4 的查询接口看结果。

```bash
curl -X POST http://localhost:8900/api/executions \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline": "oa.communicate_todos",
    "trigger_type": "api",
    "config": {
      "username": "your_oa_username",
      "password": "your_oa_password"
    }
  }'
```

### 请求体入参

| 字段 | 类型 | 必填 | 缺省 | 作用 |
|------|------|------|------|------|
| `pipeline` | string | **是** | — | 固定 `oa.communicate_todos` |
| `trigger_type` | string | 否 | `"api"` | 触发方式标记，仅作记录归类 |
| `config` | object | 否 | `null` | 执行入参（见下表）；schema 允许 null，但两条 OA 流水线必须提供（含登录凭据） |

### config 入参

| 键 | 类型 | 必填 | 缺省 | 作用 |
|----|------|------|------|------|
| `username` | string | **是** | — | OA 登录用户名 |
| `password` | string | **是** | — | OA 登录密码 |
| `login_url` | string | 否 | `https://ioa.sd-port.net/login.jsp` | OA 登录页地址（环境变更时覆盖） |
| `max_pages` | integer | 否 | `100` | 最大采集页数（翻页防死循环保险丝） |
| `max_verify_rounds` | integer | 否 | `2` | 详情采集后列表级复核的最大轮数（抓采集期间新进消息；熔断防死循环） |
| `concurrency` | integer | 否 | `1` | 详情页并发采集数（同一浏览器内并行标签页上限；调大需评估 OA 限流） |

另可加「通用 config 键」（见 §5）做本次覆盖，如 `"headless": false` 调试。

## 2. 主动触发 forward（OA 沟通批量转发）

共用一次登录，按 `forwards` 列表逐条转发，每条成功后立即回写 `fwd=1`。

```bash
curl -X POST http://localhost:8900/api/executions \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline": "oa.communicate_forward",
    "trigger_type": "api",
    "config": {
      "username": "your_oa_username",
      "password": "your_oa_password",
      "forwards": [
        {
          "task_id": "19f7fa590e4d644a234b8264566b1ca7",
          "recipients": ["张三"],
          "cc_recipients": ["李四"],
          "title": null,
          "urgent": false
        }
      ]
    }
  }'
```

### config 入参

| 键 | 类型 | 必填 | 缺省 | 作用 |
|----|------|------|------|------|
| `username` | string | **是** | — | OA 登录用户名 |
| `password` | string | **是** | — | OA 登录密码 |
| `login_url` | string | 否 | `https://ioa.sd-port.net/login.jsp` | OA 登录页地址 |
| `forwards` | array&lt;object&gt; | **是** | — | 转发任务列表，逐条执行（元素结构见下） |

### forwards 元素入参

| 键 | 类型 | 必填 | 缺省 | 作用 |
|----|------|------|------|------|
| `task_id` | string | **是** | — | 待办 fdId（须已采集入库，否则该条报「DB 中不存在」） |
| `recipients` | array&lt;string&gt; | **是** | — | 接收者姓名列表（OA 通讯录姓名，须唯一匹配） |
| `cc_recipients` | array&lt;string&gt; | 否 | — | 抄送人姓名列表 |
| `title` | string \| null | 否 | `null` | 覆盖标题；`null`/缺省 = 保留原标题；`""` = 显式清空 |
| `urgent` | boolean | 否 | `false` | 是否标记紧急 |

结果在 `result_summary`：`{total, forwarded, skipped, failed, errors}`；
有失败条时 `status=failed` 但成功条已生效。

## 3. 定时调度：每 5 分钟采集 todos

调度由平台内置调度器执行，创建即生效，无需人工触发。
执行的 config 取自 `config_override`（键名与 §1 完全相同）。

### 步骤 1：获取 pipeline id

```bash
curl -s http://localhost:8900/api/pipelines | python3 -m json.tool
# 在返回列表中按 "name": "oa.communicate_todos" 找到对应 "id"（UUID）
```

### 步骤 2：创建调度

```bash
curl -X POST http://localhost:8900/api/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline_id": "步骤1取得的UUID",
    "name": "每5分钟采集沟通待办",
    "trigger_type": "interval",
    "interval_seconds": 300,
    "config_override": {
      "username": "your_oa_username",
      "password": "your_oa_password"
    },
    "enabled": true,
    "max_retries": 1,
    "retry_delay_seconds": 60
  }'
```

### 请求体入参（ScheduleCreate）

| 字段 | 类型 | 必填 | 缺省 | 作用 |
|------|------|------|------|------|
| `pipeline_id` | string(UUID) | **是** | — | 流水线 id（步骤 1 获取，**非 name**） |
| `name` | string | **是** | — | 调度名称（展示用） |
| `trigger_type` | string | **是** | — | `interval` 固定间隔 / `cron` 表达式 / `once` 单次 |
| `interval_seconds` | int | interval 必填 | — | 间隔秒数（**300 = 5 分钟**） |
| `cron_expr` | string | cron 必填 | — | cron 表达式（5 段，如 `"*/5 * * * *"`） |
| `run_at` | datetime | once 必填 | — | 执行时刻（ISO 8601，不可早于当前时间） |
| `config_override` | object | 否 | `null` | 执行入参（todos 至少给 username/password） |
| `enabled` | boolean | 否 | `true` | 是否启用 |
| `max_retries` | int | 否 | `0` | 失败后自动重试次数（建议调度任务设 1） |
| `retry_delay_seconds` | int | 否 | `60` | 重试间隔秒数 |

**触发时机**：interval 首次触发在**创建后一个间隔**（5 分钟后首跑，不会立即执行）。

### 调度管理

| 操作 | 方法 & 路径 | 说明 |
|------|-------------|------|
| 列表 | `GET /api/schedules` | 含 `next_run_at`（下次触发时刻） |
| 修改 | `PUT /api/schedules/{id}` | 字段同创建，按需携带 |
| 启停 | `PATCH /api/schedules/{id}` `{"enabled": false}` | 显式目标态，幂等 |
| 删除 | `DELETE /api/schedules/{id}` | 级联移除调度器中的任务 |

## 4. 查询执行结果

```bash
curl -s http://localhost:8900/api/executions/{id}        # 轮询 status 至终态
curl -s http://localhost:8900/api/executions/{id}/logs   # 步骤日志（定位失败原因）
```

`status`：`pending → running → success / failed / cancelled`；
失败时 `error_message` 含原因（登录 SSO 冷启动会自动重试 1 次，仍失败才报错）。

## 5. 通用 config 键（可选，todos/forward 均支持）

缺省取「系统设置 → 运行设置」全局值；在 config / config_override 中传入即本次覆盖。

| config 键 | 类型 | 全局缺省 | 作用 |
|-----------|------|----------|------|
| `headless` | boolean | `true` | 无头模式；`false` 显示浏览器窗口（调试用） |
| `close_browser` | boolean | `true` | 执行结束后关闭浏览器；`false` 保留进程供排查 |
| `page_load_timeout` | int（毫秒） | `15000` | 页面跳转后等待加载完成的时长 |
| `element_visible_timeout` | int（毫秒） | `5000` | 等待页面元素出现的时长 |
| `action_settle_timeout` | int（毫秒） | `500` | 每次点击/输入后的固定稳定等待 |
