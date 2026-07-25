# 局域网 HTTP 调用速查

> 面向**同局域网同事**：直接调用本机已运行的 docker 部署，无需自行安装。
> Base URL：`http://10.242.134.202:8901`（后端 API）；前端页面 `http://10.242.134.202:3201`。
> 前提：与本机同局域网（或 VPN 接入）。更完整的参数细节见 `OA流水线API触发指南.md`。

## 1. 触发 todos（OA 沟通待办采集）

采集待办 → 写入 `inbox_documents` 表（按 task_id 去重，附件入 MinIO）。
**异步**：立即返回 `201` + `id`，用 §4 查询进度。

```bash
curl -X POST http://10.242.134.202:8901/api/executions \
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
| `config` | object | 否 | `null` | 执行入参；本流水线必须提供（含凭据），见下表 |

### config 入参

| 键 | 类型 | 必填 | 缺省 | 作用 |
|----|------|------|------|------|
| `username` | string | **是** | — | OA 登录用户名 |
| `password` | string | **是** | — | OA 登录密码 |
| `login_url` | string | 否 | `https://ioa.sd-port.net/login.jsp` | OA 登录页地址 |
| `max_pages` | integer | 否 | `100` | 最大采集页数（翻页防死循环保险丝） |
| `max_verify_rounds` | integer | 否 | `2` | 详情采集后列表级复核的最大轮数（抓采集期间新进消息） |
| `concurrency` | integer | 否 | `1` | 详情页并发采集数（并行标签页上限；调大需评估 OA 限流） |

## 2. 触发 forward（OA 沟通批量转发）

共用一次登录，按 `forwards` 逐条转发，每条成功后立即回写 `fwd=1`。

```bash
curl -X POST http://10.242.134.202:8901/api/executions \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline": "oa.communicate_forward",
    "trigger_type": "api",
    "config": {
      "username": "your_oa_username",
      "password": "your_oa_password",
      "forwards": [
        {"task_id": "19f7fa590e4d644a234b8264566b1ca7", "recipients": ["张三"], "urgent": false}
      ]
    }
  }'
```

### config 入参

| 键 | 类型 | 必填 | 缺省 | 作用 |
|----|------|------|------|------|
| `username` / `password` | string | **是** | — | OA 登录凭据 |
| `login_url` | string | 否 | 同 §1 | OA 登录页地址 |
| `forwards` | array&lt;object&gt; | **是** | — | 转发任务列表（元素见下） |

### forwards 元素入参

| 键 | 类型 | 必填 | 缺省 | 作用 |
|----|------|------|------|------|
| `task_id` | string | **是** | — | 待办 fdId（须已采集入库） |
| `recipients` | array&lt;string&gt; | **是** | — | 接收者姓名（OA 通讯录，须唯一匹配） |
| `cc_recipients` | array&lt;string&gt; | 否 | — | 抄送人姓名列表 |
| `title` | string \| null | 否 | `null` | 覆盖标题；null = 保留原标题；`""` = 清空 |
| `urgent` | boolean | 否 | `false` | 是否标记紧急 |

## 3. 设置定时任务（以每 5 分钟采集 todos 为例）

创建即生效，无需人工触发；**首次触发在创建后一个间隔**。

```bash
# 步骤 1：取 pipeline id
curl -s http://10.242.134.202:8901/api/pipelines | python3 -m json.tool
# 按 "name": "oa.communicate_todos" 找对应 "id"

# 步骤 2：创建调度
curl -X POST http://10.242.134.202:8901/api/schedules \
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
| `pipeline_id` | string(UUID) | **是** | — | 流水线 id（**非 name**） |
| `name` | string | **是** | — | 调度名称（展示用） |
| `trigger_type` | string | **是** | — | `interval` 固定间隔 / `cron` 表达式 / `once` 单次 |
| `interval_seconds` | int | interval 必填 | — | 间隔秒数（300 = 5 分钟） |
| `cron_expr` | string | cron 必填 | — | cron 表达式（5 段，如 `"*/5 * * * *"`） |
| `run_at` | datetime | once 必填 | — | 执行时刻（ISO 8601） |
| `config_override` | object | 否 | `null` | 执行入参（键名同 §1 config） |
| `enabled` | boolean | 否 | `true` | 是否启用 |
| `max_retries` | int | 否 | `0` | 失败后自动重试次数 |
| `retry_delay_seconds` | int | 否 | `60` | 重试间隔秒数 |

### 调度管理

| 操作 | 方法 & 路径 | 说明 |
|------|-------------|------|
| 列表 | `GET /api/schedules` | 含 `next_run_at`（下次触发时刻） |
| 修改 | `PUT /api/schedules/{id}` | 字段同创建，按需携带 |
| 启停 | `PATCH /api/schedules/{id}` `{"enabled": false}` | 显式目标态，幂等 |
| 删除 | `DELETE /api/schedules/{id}` | 级联移除调度器中的任务 |

## 4. 查看任务进度 / 状态

### 4.1 单条执行详情（轮询至终态）

```bash
curl -s http://10.242.134.202:8901/api/executions/{id} | python3 -m json.tool
```

响应关键字段：

| 字段 | 含义 |
|------|------|
| `status` | `pending` 排队 → `running` 执行中 → `success` / `failed` / `cancelled`（终态） |
| `result_summary` | 终态后的业务统计。todos：`{total, inserted, skipped, extract_failures, attachment_failures}`；forward：`{total, forwarded, skipped, failed, errors}` |
| `error_message` | 失败原因（登录 SSO 冷启动会自动重试 1 次，仍失败才报错） |
| `started_at` / `finished_at` | 起止时间（UTC 存储） |
| `pipeline_version` | 触发时流水线版本快照 |
| `retry_count` | 已重试次数 |

### 4.2 步骤日志（定位失败原因）

```bash
curl -s http://10.242.134.202:8901/api/executions/{id}/logs | python3 -m json.tool
```

每条含 `timestamp` / `level`（info/warn/error）/ `step`（login、crawl、extract、verify、forward 等）/ `message`。

实时日志（SSE 流）：`GET /api/executions/{id}/logs/stream`。

### 4.3 执行列表（筛选 + 分页）

```bash
curl -s "http://10.242.134.202:8901/api/executions?pipeline=oa.communicate_todos&status=failed&page=1&page_size=20"
```

| 查询参数 | 必填 | 缺省 | 作用 |
|----------|------|------|------|
| `pipeline` | 否 | — | 按流水线 name 过滤 |
| `status` | 否 | — | 按状态过滤，逗号分隔多值（如 `failed,cancelled`） |
| `start` / `end` | 否 | — | 按创建时间范围过滤（ISO 8601） |
| `page` | 否 | `1` | 页码 |
| `page_size` | 否 | `20` | 每页条数（最大 100） |

返回 `{total, items}`，按创建时间倒序。

### 4.4 取消执行

```bash
curl -X POST http://10.242.134.202:8901/api/executions/{id}/cancel
```

仅 `pending` / `running` 可取消。

## 5. 附件下载

`inbox_documents.attachment_urls` 中的链接形如
`http://10.242.134.202:8901/api/files/{object_key}`（平台代理，永不过期），
局域网内直接 GET 下载，无需可达 MinIO。
（注意：本次调整前入库的旧链接以 `117.187.178.213` 为前缀，内网可能打不开。）
