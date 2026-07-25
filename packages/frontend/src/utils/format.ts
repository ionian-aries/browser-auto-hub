/** 执行耗时统一格式化（spec 4 §10）：
 * <60s → "45秒"；<1h → "1分23秒"；≥1h → "2小时3分"
 */
export function formatDuration(seconds: number): string {
  const sec = Math.max(0, Math.floor(seconds));
  if (sec < 60) return `${sec}秒`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m}分${sec % 60}秒`;
  return `${Math.floor(m / 60)}小时${m % 60}分`;
}

/** 由起止时间计算耗时秒数；end 为 null（运行中）时用 now。 */
export function durationSeconds(
  startedAt: string | null,
  finishedAt: string | null,
  now: number = Date.now()
): number | null {
  if (!startedAt) return null;
  const end = finishedAt ? new Date(finishedAt).getTime() : now;
  return Math.floor((end - new Date(startedAt).getTime()) / 1000);
}
