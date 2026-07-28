export interface Pipeline {
  id: string;
  name: string;
  display_name: string;
  description: string;
  trigger_modes: string[];
  config_schema: Record<string, unknown> | null;
  status: string;
  version: string;
  created_at: string;
  updated_at: string;
}

export interface Schedule {
  id: string;
  pipeline_id: string;
  pipeline_name: string | null;
  pipeline_display_name: string | null;
  name: string;
  trigger_type: "cron" | "interval" | "once";
  cron_expr: string | null;
  interval_seconds: number | null;
  run_at: string | null;
  config_override: Record<string, unknown> | null;
  enabled: boolean;
  next_run_at: string | null;
  max_retries: number;
  retry_delay_seconds: number;
  created_at: string;
  updated_at: string;
}

export interface Execution {
  id: string;
  pipeline_id: string;
  pipeline_name: string | null;
  pipeline_display_name: string | null;
  schedule_id: string | null;
  trigger_type: "scheduled" | "api" | "manual";
  status: "pending" | "running" | "success" | "failed" | "cancelled";
  config: Record<string, unknown> | null;
  pipeline_version: string | null;
  retry_count: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  result_summary: Record<string, unknown> | null;
  created_at: string;
}

export interface LogEntry {
  timestamp: string;
  level: "info" | "warn" | "error";
  step: string;
  message: string;
}

export interface ExecutionStats {
  today_count: number;
  today_success: number;
  today_failed: number;
  success_rate: number;
  running_count: number;
}

export interface SystemInfo {
  scheduler_status: "running" | "paused";
  active_schedules: number;
}

export interface SystemSettings {
  log_retention_days: number;
  scheduler_enabled: boolean;
  // 全局运行设置（三级覆盖链底层）
  run_headless: boolean;
  run_close_browser: boolean;
  run_page_load_timeout: number;
  run_element_visible_timeout: number;
  run_action_settle_timeout: number;
  run_default_max_retries: number;
  run_default_retry_delay_seconds: number;
}
