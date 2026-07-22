import axios from "axios";
import type {
  Artifact,
  Execution,
  ExecutionStats,
  LogEntry,
  Pipeline,
  Schedule,
  SystemInfo,
  SystemSettings,
} from "../types";

const api = axios.create({ baseURL: "/api" });

export const pipelineApi = {
  list: () => api.get<Pipeline[]>("/pipelines").then((r) => r.data),
  get: (name: string) => api.get<Pipeline>(`/pipelines/${name}`).then((r) => r.data),
  patch: (name: string, data: { max_concurrent?: number; timeout_seconds?: number; status?: string }) =>
    api.patch<Pipeline>(`/pipelines/${name}`, data).then((r) => r.data),
};

export const scheduleApi = {
  list: (params?: { pipeline_id?: string }) =>
    api.get<Schedule[]>("/schedules", { params }).then((r) => r.data),
  get: (id: string) => api.get<Schedule>(`/schedules/${id}`).then((r) => r.data),
  create: (data: {
    pipeline_id: string;
    name: string;
    trigger_type: string;
    cron_expr?: string | null;
    interval_seconds?: number | null;
    run_at?: string | null;
    config_override?: Record<string, unknown> | null;
    max_retries?: number;
    retry_delay_seconds?: number;
  }) => api.post<Schedule>("/schedules", data).then((r) => r.data),
  update: (id: string, data: Partial<Schedule>) =>
    api.put<Schedule>(`/schedules/${id}`, data).then((r) => r.data),
  delete: (id: string) => api.delete(`/schedules/${id}`),
  toggle: (id: string) => api.patch<Schedule>(`/schedules/${id}/toggle`).then((r) => r.data),
};

export const executionApi = {
  list: (params?: { pipeline?: string; status?: string; start?: string; end?: string; page?: number; page_size?: number }) =>
    api.get<Execution[]>("/executions", { params }).then((r) => r.data),
  get: (id: string) => api.get<Execution>(`/executions/${id}`).then((r) => r.data),
  create: (data: { pipeline: string; config?: Record<string, unknown>; trigger_type?: string }) =>
    api.post<Execution>("/executions", data).then((r) => r.data),
  cancel: (id: string) => api.post<Execution>(`/executions/${id}/cancel`).then((r) => r.data),
  delete: (id: string) => api.delete(`/executions/${id}`),
  getLogs: (id: string) => api.get<LogEntry[]>(`/executions/${id}/logs`).then((r) => r.data),
  getArtifacts: (id: string) => api.get<Artifact[]>(`/executions/${id}/artifacts`).then((r) => r.data),
  stats: () => api.get<ExecutionStats>("/executions/stats").then((r) => r.data),
};

export const systemApi = {
  info: () => api.get<SystemInfo>("/system/info").then((r) => r.data),
  getSettings: () => api.get<SystemSettings>("/system/settings").then((r) => r.data),
  updateSettings: (data: Partial<SystemSettings>) =>
    api.put("/system/settings", data).then((r) => r.data),
  testStorage: () => api.post<{ status: string; message: string }>("/system/storage/test").then((r) => r.data),
  testDb: () => api.post<{ status: string }>("/system/db/test").then((r) => r.data),
};

export const fileApi = {
  presign: (key: string) => api.get<{ url: string }>("/files/presign", { params: { key } }).then((r) => r.data),
};
