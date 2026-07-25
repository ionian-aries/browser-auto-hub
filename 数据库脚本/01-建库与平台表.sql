-- 01-建库与平台表.sql
-- 创建 browser_auto_hub 库 + 平台 5 张表（pipelines / schedules / task_executions /
-- task_logs / system_settings），顺序按外键依赖排列。
-- 平台启动不做 create_all，库表须先于应用创建，应用仅连接。
-- 全部 IF NOT EXISTS，可重复执行。

CREATE DATABASE IF NOT EXISTS browser_auto_hub
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE browser_auto_hub;

-- 流水线注册表。无需种子：后端启动时自动将代码注册的 pipeline 同步进来
-- （按 name 匹配，新增插入 / 定义字段内容对比更新 / 代码删除软归档 archived）。
CREATE TABLE IF NOT EXISTS `pipelines` (
  `id` varchar(36) NOT NULL COMMENT 'UUID 主键',
  `name` varchar(100) NOT NULL COMMENT '流水线标识，如 oa.communicate_todos',
  `display_name` varchar(200) NOT NULL COMMENT '中文显示名',
  `description` text NOT NULL COMMENT '描述',
  `trigger_modes` json NOT NULL COMMENT '支持的触发方式，如 ["cron","api","manual"]',
  `config_schema` json DEFAULT NULL COMMENT 'config 的 JSON Schema（前端动态渲染表单）',
  `status` enum('active','disabled','archived') NOT NULL DEFAULT 'active' COMMENT '状态；非 active 不可触发',
  `version` varchar(50) NOT NULL DEFAULT '1.0.0' COMMENT '代码声明版本，sync 按版本差异决定是否更新定义',
  `created_at` datetime NOT NULL DEFAULT (utc_timestamp()),
  `updated_at` datetime NOT NULL DEFAULT (utc_timestamp()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_pipelines_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='流水线注册表（启动自动同步）';

-- 调度定义表。FK 依赖 pipelines。
CREATE TABLE IF NOT EXISTS `schedules` (
  `id` varchar(36) NOT NULL COMMENT 'UUID 主键',
  `pipeline_id` varchar(36) NOT NULL COMMENT '关联 pipelines.id',
  `name` varchar(200) NOT NULL COMMENT '调度名称',
  `trigger_type` enum('cron','interval','once') NOT NULL COMMENT '触发类型：cron表达式/固定间隔/单次',
  `cron_expr` varchar(100) DEFAULT NULL COMMENT 'cron 表达式（trigger_type=cron 时必填）',
  `interval_seconds` int DEFAULT NULL COMMENT '间隔秒数（trigger_type=interval 时必填）',
  `run_at` datetime(6) DEFAULT NULL COMMENT '执行时刻（trigger_type=once 时必填，UTC）',
  `config_override` json DEFAULT NULL COMMENT '执行入参；调度触发时原样作为 execution.config',
  `enabled` tinyint(1) NOT NULL COMMENT '是否启用',
  `max_retries` int NOT NULL COMMENT '失败自动重试次数',
  `retry_delay_seconds` int NOT NULL COMMENT '重试间隔秒数',
  `created_at` datetime NOT NULL DEFAULT (utc_timestamp()),
  `updated_at` datetime NOT NULL DEFAULT (utc_timestamp()),
  PRIMARY KEY (`id`),
  KEY `pipeline_id` (`pipeline_id`),
  CONSTRAINT `schedules_ibfk_1` FOREIGN KEY (`pipeline_id`) REFERENCES `pipelines` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='调度定义表';

-- 执行记录表。运行时由平台自动写入。FK 依赖 pipelines / schedules。
CREATE TABLE IF NOT EXISTS `task_executions` (
  `id` varchar(36) NOT NULL COMMENT 'UUID 主键',
  `pipeline_id` varchar(36) NOT NULL COMMENT '关联 pipelines.id',
  `schedule_id` varchar(36) DEFAULT NULL COMMENT '调度触发时关联 schedules.id，否则 NULL',
  `trigger_type` enum('scheduled','api','manual') NOT NULL COMMENT '触发方式',
  `status` enum('pending','running','success','failed','cancelled') NOT NULL COMMENT '执行状态',
  `config` json DEFAULT NULL COMMENT '本次执行的入参快照',
  `retry_count` int NOT NULL COMMENT '已重试次数',
  `started_at` datetime DEFAULT NULL COMMENT '开始时间（UTC）',
  `finished_at` datetime DEFAULT NULL COMMENT '结束时间（UTC）',
  `error_message` text COMMENT '失败原因',
  `result_summary` json DEFAULT NULL COMMENT '业务统计（如采集/转发条数）',
  `pipeline_version` varchar(50) DEFAULT NULL COMMENT '触发时 pipeline 版本快照',
  `created_at` datetime NOT NULL DEFAULT (utc_timestamp()),
  PRIMARY KEY (`id`),
  KEY `pipeline_id` (`pipeline_id`),
  KEY `schedule_id` (`schedule_id`),
  CONSTRAINT `task_executions_ibfk_1` FOREIGN KEY (`pipeline_id`) REFERENCES `pipelines` (`id`),
  CONSTRAINT `task_executions_ibfk_2` FOREIGN KEY (`schedule_id`) REFERENCES `schedules` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='执行记录表（运行时自动写入）';

-- 步骤日志表。运行时由平台自动写入。FK 依赖 task_executions。
CREATE TABLE IF NOT EXISTS `task_logs` (
  `id` varchar(36) NOT NULL COMMENT 'UUID 主键',
  `execution_id` varchar(36) NOT NULL COMMENT '关联 task_executions.id',
  `timestamp` datetime(6) NOT NULL DEFAULT (utc_timestamp(6)) COMMENT '日志时间（UTC，微秒精度）',
  `level` enum('info','warn','error') NOT NULL COMMENT '级别',
  `step_name` varchar(100) NOT NULL COMMENT '步骤名，如 login / crawl / forward[xxxxxxxx]',
  `message` text NOT NULL COMMENT '日志内容',
  PRIMARY KEY (`id`),
  KEY `execution_id` (`execution_id`),
  CONSTRAINT `task_logs_ibfk_1` FOREIGN KEY (`execution_id`) REFERENCES `task_executions` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='执行步骤日志表（运行时自动写入）';

-- 系统设置表（运行旋钮）。无需种子：代码对所有 run_* 键均有默认值兜底，
-- 在「系统设置」页保存后才会出现对应行。
CREATE TABLE IF NOT EXISTS `system_settings` (
  `key` varchar(100) NOT NULL COMMENT '设置键，如 run_headless / run_default_max_retries',
  `value` text NOT NULL COMMENT '设置值（统一按字符串存储）',
  `updated_at` datetime NOT NULL DEFAULT (utc_timestamp()),
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统设置表（代码默认值兜底，无需种子）';
