export interface Pipeline {
  id: number;
  name: string;
  display_name: string;
  description: string;
  trigger_modes: string[];
  config_schema: Record<string, unknown> | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Schedule {
  id: number;
  pipeline_id: number;
  pipeline_name: string | null;
  name: string;
  trigger_type: "cron" | "interval" | "once";
  cron_expr: string | null;
  interval_seconds: number | null;
  config_override: Record<string, unknown> | null;
  enabled: boolean;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Execution {
  id: number;
  pipeline_id: number;
  pipeline_name: string | null;
  schedule_id: number | null;
  trigger_type: "scheduled" | "api" | "manual";
  status: "pending" | "running" | "success" | "failed" | "cancelled";
  config: Record<string, unknown> | null;
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
