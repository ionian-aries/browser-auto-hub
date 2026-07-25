-- 03-默认数据-每10分钟采集待办调度.sql
-- 默认调度：每 10 分钟执行一次 oa.communicate_todos（沟通待办采集）。
--
-- 前提：pipelines 表已有 oa.communicate_todos 行——即后端至少启动过一次
-- （启动时自动同步 pipeline 注册表）。若本语句影响行数为 0，先启动后端再重跑。
--
-- 幂等：可重复执行；已存在「同 pipeline + interval 600s」的调度时不再插入。
--
-- 注意：config_override 中的 username/password 为占位符，默认 enabled=0（停用）。
-- 请改为真实 OA 凭据后，再到「调度」页面启用（或执行下方 UPDATE）。

USE browser_auto_hub;

INSERT INTO schedules
  (id, pipeline_id, name, trigger_type, interval_seconds, config_override, enabled, max_retries, retry_delay_seconds)
SELECT
  UUID(),
  p.id,
  '每10分钟采集沟通待办',
  'interval',
  600,
  JSON_OBJECT(
    'username', 'your_oa_username',
    'password', 'your_oa_password'
  ),
  0,   -- enabled：占位凭据下默认停用，填好凭据后再启用
  0,   -- max_retries：失败不自动重试，可按需调整
  60   -- retry_delay_seconds
FROM pipelines p
WHERE p.name = 'oa.communicate_todos'
  AND NOT EXISTS (
    SELECT 1 FROM schedules s
    WHERE s.pipeline_id = p.id
      AND s.trigger_type = 'interval'
      AND s.interval_seconds = 600
  );

-- 填好凭据后的启用示例（二选一：页面操作或 SQL）：
-- UPDATE schedules SET
--   config_override = JSON_SET(config_override,
--     '$.username', '真实OA用户名',
--     '$.password', '真实OA密码'),
--   enabled = 1
-- WHERE name = '每10分钟采集沟通待办';
