import axios from "axios";
import type { Execution, LogEntry, Pipeline, Schedule } from "../types";

const api = axios.create({ baseURL: "/api" });

export const pipelineApi = {
  list: () => api.get<Pipeline[]>("/pipelines").then((r) => r.data),
  get: (name: string) => api.get<Pipeline>(`/pipelines/${name}`).then((r) => r.data),
};

export const scheduleApi = {
  list: () => api.get<Schedule[]>("/schedules").then((r) => r.data),
  create: (data: {
    pipeline_name: string;
    name: string;
    trigger_type: string;
    cron_expr?: string;
    interval_seconds?: number;
    config_override?: Record<string, unknown>;
  }) => api.post<Schedule>("/schedules", data).then((r) => r.data),
  update: (id: number, data: Partial<Schedule>) =>
    api.put<Schedule>(`/schedules/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/schedules/${id}`),
  toggle: (id: number) => api.patch<Schedule>(`/schedules/${id}/toggle`).then((r) => r.data),
};

export const executionApi = {
  list: (params?: { pipeline?: string; status?: string; page?: number }) =>
    api.get<Execution[]>("/executions", { params }).then((r) => r.data),
  get: (id: number) => api.get<Execution>(`/executions/${id}`).then((r) => r.data),
  create: (data: { pipeline: string; config?: Record<string, unknown>; trigger_type?: string }) =>
    api.post<Execution>("/executions", data).then((r) => r.data),
  getLogs: (id: number) => api.get<LogEntry[]>(`/executions/${id}/logs`).then((r) => r.data),
};

export const systemApi = {
  health: () => api.get<{ status: string; version: string }>("/system/health").then((r) => r.data),
};
