export interface Pipeline {
  id: string;
  name: string;
  display_name: string;
  description: string;
  trigger_modes: string[];
  config_schema: Record<string, unknown> | null;
  max_concurrent: number;
  timeout_seconds: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Schedule {
  id: string;
  pipeline_id: string;
  pipeline_name: string | null;
  name: string;
  trigger_type: "cron" | "interval" | "once";
  cron_expr: string | null;
  interval_seconds: number | null;
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
  schedule_id: string | null;
  trigger_type: "scheduled" | "api" | "manual";
  status: "pending" | "running" | "success" | "failed" | "cancelled";
  config: Record<string, unknown> | null;
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
  screenshot_key: string | null;
}

export interface ExecutionStats {
  today_count: number;
  today_success: number;
  today_failed: number;
  success_rate: number;
  running_count: number;
}

export interface SystemInfo {
  uptime_seconds: number;
  scheduler_status: "running" | "paused";
  active_schedules: number;
  db_pool: { pool_size: number; checked_out: number; overflow: number };
}

export interface SystemSettings {
  minio_endpoint: string;
  minio_bucket: string;
  minio_object_prefix: string;
  minio_presign_expires_seconds: string;
  log_retention_days: string;
  scheduler_enabled: string;
}

export interface Artifact {
  id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  download_url: string;
  created_at: string;
}
