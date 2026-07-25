# OA 流水线 API 触发指南

> 面向外部系统/脚本主动触发 `oa.communicate_todos`（沟通待办采集）与
> `oa.communicate_forward`（沟通批量转发）两条流水线，以及通过 API 创建定时调度（§4）。
> Base URL 缺省 `http://localhost:8900`（`BACKEND_PORT` 可在 `.env` 覆盖）。
> 与代码不一致时以代码为准（`backend/api/executions.py`、`backend/api/schedules.py`、
> `engine/pipelines/oa/*`）。

## 1. 触发方式（两条流水线共用）

唯一入口：`POST /api/executions`

- **异步语义**：立即返回 `201` + execution 记录（`status=pending`），后台执行
- 流水线不存在：`404`；流水线被停用：`400`；请求体格式错误：`422`

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `pipeline` | string | 是 | `oa.communicate_todos` / `oa.communicate_forward` |
| `trigger_type` | string | 否 | 固定 `"api"`（缺省即 `"api"`），仅作记录归类 |
| `config` | object \| null | 否 | 本次执行的入参（见各流水线参数表） |

### 响应（201，关键字段）

`id`（后续查询/取消用）、`status`（pending → running → success/failed/cancelled）、
`result_summary`（终态后的业务统计，如采集/转发条数）、`error_message`（失败原因）、
`pipeline_version`（触发时版本快照）。

### 通用 config 键（可选，两条流水线均支持）

不属于流水线自身参数，是平台运行行为。缺省取「系统设置 → 运行设置」全局值；
在 `config` 中显式传入即对本次执行覆盖（execution 优先于全局）。

| config 键 | 类型 | 全局缺省 | 作用 |
|-----------|------|----------|------|
| `headless` | boolean | `true` | 无头模式；`false` 显示浏览器窗口（调试用） |
| `close_browser` | boolean | `true` | 执行结束后关闭浏览器；`false` 保留进程供排查 |
| `page_load_timeout` | int（毫秒） | `15000` | 页面跳转后等待加载完成的时长 |
| `element_visible_timeout` | int（毫秒） | `5000` | 等待页面元素出现的时长 |
| `action_settle_timeout` | int（毫秒） | `500` | 每次点击/输入等操作后的固定稳定等待 |

## 2. oa.communicate_todos（OA 沟通待办采集）

采集沟通待办列表，提取元数据与附件写入 `inbox_documents` 表（按 `task_id` 去重，附件入 MinIO）。

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

### config 参数

| 键 | 类型 | 必填 | 缺省 | 作用 |
|----|------|------|------|------|
| `username` | string | **是** | — | OA 登录用户名 |
| `password` | string | **是** | — | OA 登录密码 |
| `login_url` | string | 否 | `https://ioa.sd-port.net/login.jsp` | OA 登录页地址（环境变更时覆盖） |
| `max_pages` | integer | 否 | `100` | 最大采集页数（翻页防死循环保险丝） |
| `max_verify_rounds` | integer | 否 | `2` | 详情采集后列表级复核的最大轮数（抓采集期间新进消息；熔断防死循环） |
| `concurrency` | integer | 否 | `1` | 详情页并发采集数（同一浏览器 context 内并行标签页上限；调大需评估 OA 限流） |

另可加 §1「通用 config 键」做本次覆盖。

> **前端执行配置弹窗未显示新增字段？** pipelines 表的 config_schema 由后端启动时
> 与代码**逐字段内容对比**同步（有差异即覆盖，spec 1 二十七次修订起不再依赖
> version 变化）。`max_verify_rounds` / `concurrency` 字段**重启后端**后即出现。

调试示例（有头 + 保留浏览器 + 只采 3 页）：

```bash
curl -X POST http://localhost:8900/api/executions \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline": "oa.communicate_todos",
    "trigger_type": "api",
    "config": {
      "username": "your_oa_username",
      "password": "your_oa_password",
      "max_pages": 3,
      "headless": false,
      "close_browser": false
    }
  }'
```

> **附件下载**：`inbox_documents.attachment_urls` 为**附件 URL 字符串数组**（仅上传成功项），
> 每个元素是平台代理下载地址 `{平台地址}/api/files/{object_key}`，**永不过期**，
> 直接 GET 即可下载（后端自 MinIO 取流转发，消费方无需可达 MinIO）。

## 3. oa.communicate_forward（OA 沟通批量转发）

共用一次登录，按 `forwards` 列表逐条转发沟通待办，每条成功后立即回写 `fwd=1`
（逐条独立 commit：进程崩溃后 DB 与 OA 真实状态一致，已成功的条目重跑会跳过——
但仍建议调用方自行保证 `forwards` 内容幂等）。

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
          "cc_recipients": ["李四", "王五"],
          "title": null,
          "urgent": false
        },
        {
          "task_id": "2a8b0c...另一条待办fdId",
          "recipients": ["赵六"],
          "title": "请优先处理",
          "urgent": true
        }
      ]
    }
  }'
```

### config 参数

| 键 | 类型 | 必填 | 缺省 | 作用 |
|----|------|------|------|------|
| `username` | string | **是** | — | OA 登录用户名 |
| `password` | string | **是** | — | OA 登录密码 |
| `login_url` | string | 否 | `https://ioa.sd-port.net/login.jsp` | OA 登录页地址 |
| `forwards` | array&lt;object&gt; | **是** | — | 转发任务列表，逐条执行（元素结构见下） |

### forwards 元素

| 键 | 类型 | 必填 | 缺省 | 作用 |
|----|------|------|------|------|
| `task_id` | string | **是** | — | 待办 fdId（须已采集入库，否则该条报「DB 中不存在」） |
| `recipients` | array&lt;string&gt; | **是** | — | 接收者姓名列表（OA 通讯录姓名，须唯一匹配） |
| `cc_recipients` | array&lt;string&gt; | 否 | — | 抄送人姓名列表 |
| `title` | string \| null | 否 | `null` | 覆盖标题；`null`/缺省 = 保留原标题；空字符串 `""` = 显式清空标题 |
| `urgent` | boolean | 否 | `false` | 是否标记紧急 |

另可加 §1「通用 config 键」做本次覆盖。转发结果在 `result_summary` 中：
`{total, forwarded, skipped, failed, errors}`；有失败条时 `status=failed` 但成功条已生效。

## 4. 定时调度（以「每 10 分钟采集待办」为例）

调度由平台内置调度器执行，创建即注册生效，无需人工触发。适合 `oa.communicate_todos`
定时采集；`oa.communicate_forward` 声明的触发方式为 api/manual（每次 forwards 内容不同），
一般不配调度。

调度执行的 config 取自 `config_override`（全局运行设置打底，`config_override` 优先），
键名与 §1-§3 的 config 完全相同；重试按调度自身的 `max_retries` / `retry_delay_seconds`。

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
    "name": "每10分钟采集沟通待办",
    "trigger_type": "interval",
    "interval_seconds": 600,
    "config_override": {
      "username": "your_oa_username",
      "password": "your_oa_password"
    },
    "enabled": true,
    "max_retries": 0,
    "retry_delay_seconds": 60
  }'
```

### 请求体参数（ScheduleCreate）

| 字段 | 类型 | 必填 | 缺省 | 说明 |
|------|------|------|------|------|
| `pipeline_id` | string(UUID) | 是 | — | 流水线 id（步骤 1 获取，非 name） |
| `name` | string | 是 | — | 调度名称（展示用） |
| `trigger_type` | string | 是 | — | `interval` 固定间隔 / `cron` 表达式 / `once` 单次 |
| `interval_seconds` | int | interval 必填 | — | 间隔秒数（600 = 10 分钟） |
| `cron_expr` | string | cron 必填 | — | cron 表达式（5 段，如 `"*/5 * * * *"`） |
| `run_at` | datetime | once 必填 | — | 执行时刻（ISO 8601，不可早于当前时间） |
| `config_override` | object | 否 | `null` | 执行入参（同 API 触发的 config；todos 至少给 username/password） |
| `enabled` | boolean | 否 | `true` | 是否启用 |
| `max_retries` | int | 否 | `0` | 失败后自动重试次数 |
| `retry_delay_seconds` | int | 否 | `60` | 重试间隔秒数 |

触发时机语义：`interval` 首次触发在**创建后一个间隔**（不会注册即执行）；
`cron` 在下一个匹配时刻；`once` 到点触发一次后自动停用。

### 调度管理

| 操作 | 方法 & 路径 | 说明 |
|------|-------------|------|
| 列表 | `GET /api/schedules` | 含 `next_run_at`（下次触发时刻） |
| 单条 | `GET /api/schedules/{id}` | |
| 修改 | `PUT /api/schedules/{id}` | 字段同创建，按需携带 |
| 启停 | `PATCH /api/schedules/{id}` `{"enabled": false}` | 显式目标态，幂等 |
| 删除 | `DELETE /api/schedules/{id}` | 级联移除调度器中的任务 |

## 5. 触发后查询（简要）

| 操作 | 方法 & 路径 |
|------|-------------|
| 查终态 | `GET /api/executions/{id}`（轮询 `status` 至 success/failed/cancelled） |
| 查日志 | `GET /api/executions/{id}/logs` |
| 实时日志 | `GET /api/executions/{id}/logs/stream`（SSE，含已落库日志回放 + 终态 complete 事件） |
| 取消 | `POST /api/executions/{id}/cancel`（仅 pending/running 可取消） |

## 6. 失败语义

- 登录失败 / 元素超时等业务失败：`status=failed`，`error_message` 含原因，
  步骤日志定位到具体 step（login / locate_list / crawl / forward 等）
- **登录冷启动韧性**：OA 冷状态登录可能 302 跳转到不可达的 SSO 地址——
  `oa_login` 检测到导航失败（chrome-error 页）会**自动完整重试 1 次**
  （首次尝试已在服务端建立 SSO 状态，重试走本地认证直达 portal）；
  重试仍失败才报 `LoginTimeout`，错误消息含真实原因（spec 3 2026-07-24 修订五）
- API 触发的执行缺省**不自动重试**（全局 `run_default_max_retries` 缺省 0）；
  调度触发的执行按调度自身的 `max_retries` / `retry_delay_seconds` 重试；
  需要重试请调整对应配置，或由调用方按终态自行重新触发
