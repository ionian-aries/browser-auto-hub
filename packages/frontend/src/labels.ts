// 全局枚举中文映射层：后端枚举保持英文存储，前端展示一律经此映射
export const statusLabels: Record<string, string> = {
  pending: "排队中",
  running: "运行中",
  success: "成功",
  failed: "失败",
  cancelled: "已取消",
};

export const statusColors: Record<string, string> = {
  pending: "default",
  running: "processing",
  success: "success",
  failed: "error",
  cancelled: "warning",
};

// execution.trigger_type
export const triggerLabels: Record<string, string> = {
  manual: "手动触发",
  scheduled: "定时触发",
  api: "API 触发",
};

// pipeline.trigger_modes
export const triggerModeLabels: Record<string, string> = {
  cron: "定时",
  api: "API",
  manual: "手动",
};

// pipeline.status
export const pipelineStatusLabels: Record<string, string> = {
  active: "启用",
  disabled: "停用",
};

// schedule.trigger_type
export const scheduleTypeLabels: Record<string, string> = {
  cron: "Cron 定时",
  interval: "固定间隔",
  once: "单次定时",
};
