import { useEffect, useRef, useState } from "react";
import { Button, Card, Col, Empty, Image, Result, Row, Tag, message } from "antd";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { executionApi, fileApi } from "../api/client";
import { statusColors, statusLabels, triggerLabels } from "../labels";
import { durationSeconds, formatDuration } from "../utils/format";
import type { Artifact, LogEntry } from "../types";

const levelLabels: Record<string, string> = { all: "全部", info: "信息", warn: "警告", error: "错误" };
const levelColors: Record<string, string> = { info: "#1890ff", warn: "#faad14", error: "#ff4d4f" };
const levelIcons: Record<string, string> = { info: "●", warn: "▲", error: "✕" };
const stepColors = ["#1890ff", "#52c41a", "#722ed1", "#fa8c16", "#13c2c2", "#eb2f96"];

function getStepColor(step: string, map: Map<string, string>): string {
  if (!map.has(step)) {
    map.set(step, stepColors[map.size % stepColors.length]);
  }
  return map.get(step)!;
}

export function ExecutionDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [screenshots, setScreenshots] = useState<Record<string, string>>({});
  const [sseDropped, setSseDropped] = useState<"retrying" | "failed" | false>(false);
  // 耗时实时走秒：pending/running 期间本地 1s ticker（spec 4 §6.1）
  const [now, setNow] = useState(() => Date.now());
  const logEndRef = useRef<HTMLDivElement>(null);
  const userScrolledRef = useRef(false);
  const stepColorMap = useRef(new Map<string, string>());
  const loadedKeysRef = useRef(new Set<string>());

  const { data: execution, error: executionError } = useQuery({
    queryKey: ["execution", id],
    queryFn: () => executionApi.get(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      // pending 也必须轮询：后端无排队机制，pending→running 为毫秒级；
      // 只轮询 running 会让落在 pending 的页面永久停留「排队中」（死端，spec §6.3）
      const s = query.state.data?.status;
      return s === "pending" || s === "running" ? 3000 : false;
    },
  });
  const { data: artifacts } = useQuery({
    queryKey: ["artifacts", id],
    queryFn: () => executionApi.getArtifacts(id!),
    enabled: !!id && execution?.status !== "running",
  });

  const cancelMutation = useMutation({
    mutationFn: () => executionApi.cancel(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["execution", id] });
      message.success("已取消");
    },
  });

  // SSE or load historical logs
  useEffect(() => {
    if (!id || !execution) return;

    if (execution.status === "running") {
      let source: EventSource | null = null;
      let retryTimer: ReturnType<typeof setTimeout> | null = null;
      let retries = 0;
      let done = false;

      const connect = () => {
        source = new EventSource(`/api/executions/${id}/logs/stream`);
        source.onmessage = (event) => {
          const entry = JSON.parse(event.data);
          if (entry.type === "complete") {
            done = true;
            source?.close();
            setSseDropped(false);
            queryClient.invalidateQueries({ queryKey: ["execution", id] });
            return;
          }
          setLogs((prev) => [...prev, entry]);
        };
        source.onerror = () => {
          // 关闭以阻止原生自动重连（原生重连会重新回放 backlog，导致日志重复）
          source?.close();
          if (done) return;
          retries += 1;
          if (retries <= 5) {
            // 手动重连：后端会回放已落库日志，先清空避免重复
            setLogs([]);
            setSseDropped("retrying");
            retryTimer = setTimeout(connect, 1000 * retries);
          } else {
            // 放弃重连：execution 轮询仍在走，状态翻为非 running 后会改走 getLogs 快照
            setSseDropped("failed");
          }
        };
      };
      connect();
      return () => {
        done = true;
        if (retryTimer) clearTimeout(retryTimer);
        source?.close();
      };
    } else {
      setSseDropped(false);
      executionApi.getLogs(id).then(setLogs);
    }
  }, [id, execution?.status]);

  // Auto-scroll
  useEffect(() => {
    if (!userScrolledRef.current) {
      logEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  // Load screenshot URLs
  useEffect(() => {
    const keys = logs.filter((l) => l.screenshot_key).map((l) => l.screenshot_key!);
    const newKeys = keys.filter((k) => !loadedKeysRef.current.has(k));
    newKeys.forEach((key) => {
      loadedKeysRef.current.add(key);
      fileApi.presign(key).then(({ url }) => {
        setScreenshots((prev) => ({ ...prev, [key]: url }));
      });
    });
  }, [logs]);

  // pending/running 期间每秒刷新耗时显示
  useEffect(() => {
    if (execution?.status !== "pending" && execution?.status !== "running") return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [execution?.status]);

  if (executionError) {
    return (
      <Result
        status="404"
        title="执行记录不存在"
        subTitle="该执行可能已被删除，或链接有误"
        extra={<Link to="/executions"><Button type="primary">返回执行列表</Button></Link>}
      />
    );
  }
  if (!execution) return <div>加载中...</div>;

  const filteredLogs = filter === "all" ? logs : logs.filter((l) => l.level === filter);
  const durationSec = durationSeconds(execution.started_at, execution.finished_at, now);

  return (
    // 等高 100% 布局：占满视口可用高度（扣除 Content 与白卡双层 padding 各 24×2），
    // 左右栏各自内部滚动，页面级滚动不参与（spec 4 §6.2）
    <div style={{ height: "calc(100vh - 96px)", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16, flexShrink: 0 }}>
        <div>
          <h2 style={{ display: "inline" }}>
            <Link to={`/pipelines/${execution.pipeline_name}`}>
              {execution.pipeline_display_name ?? execution.pipeline_name}
            </Link>
            {" "}
            <span style={{ fontSize: 14, color: "#999" }}>#{execution.id.slice(0, 8)}</span>
          </h2>
          <div style={{ marginTop: 8 }}>
            <Tag color={statusColors[execution.status]}>{statusLabels[execution.status] ?? execution.status}</Tag>
            <Tag>{triggerLabels[execution.trigger_type] ?? execution.trigger_type}</Tag>
            {execution.pipeline_version && <Tag>v{execution.pipeline_version}</Tag>}
            {execution.started_at && <span style={{ color: "#666" }}>{new Date(execution.started_at).toLocaleString("zh-CN", { hour12: false })}</span>}
            {durationSec !== null && <span style={{ color: "#666", marginLeft: 8 }}>耗时 {formatDuration(durationSec)}</span>}
          </div>
        </div>
        {(execution.status === "pending" || execution.status === "running") && (
          <Button danger onClick={() => cancelMutation.mutate()}>取消执行</Button>
        )}
      </div>

      {/* Main content: left/right split */}
      <Row gutter={16} style={{ flex: 1, minHeight: 0 }}>
        {/* Left: Log stream */}
        <Col span={17} style={{ height: "100%" }}>
          <Card
            title="执行日志"
            size="small"
            style={{ height: "100%", display: "flex", flexDirection: "column" }}
            styles={{ body: { flex: 1, minHeight: 0, padding: 0, display: "flex", flexDirection: "column" } }}
            extra={
              <span>
                {sseDropped === "retrying" && <Tag color="warning">连接中断，重连中…</Tag>}
                {sseDropped === "failed" && <Tag color="error">日志连接已断开</Tag>}
                {["all", "info", "warn", "error"].map((level) => (
                  <Tag
                    key={level}
                    color={filter === level ? "blue" : "default"}
                    style={{ cursor: "pointer" }}
                    onClick={() => setFilter(level)}
                  >
                    {levelLabels[level]}
                  </Tag>
                ))}
              </span>
            }
          >
            <div
              style={{ flex: 1, minHeight: 0, overflow: "auto", fontFamily: "monospace", fontSize: 12, padding: "8px 0" }}
              onScroll={(e) => {
                const el = e.currentTarget;
                userScrolledRef.current = el.scrollTop + el.clientHeight < el.scrollHeight - 50;
              }}
            >
              {filteredLogs.length === 0 && <Empty description="暂无日志" />}
              {filteredLogs.map((log, i) => (
                <div
                  key={i}
                  style={{
                    padding: "4px 8px",
                    background: log.level === "error" ? "#fff2f0" : undefined,
                    borderLeft: `3px solid ${levelColors[log.level]}`,
                    marginBottom: 2,
                  }}
                >
                  <span style={{ color: "#999" }}>{new Date(log.timestamp).toLocaleTimeString("zh-CN", { hour12: false })}</span>
                  {" "}
                  <Tag color={getStepColor(log.step, stepColorMap.current)} style={{ fontSize: 11 }}>
                    {log.step}
                  </Tag>
                  {" "}
                  <span style={{ color: levelColors[log.level] }}>{levelIcons[log.level]}</span>
                  {" "}
                  <span>{log.message}</span>
                </div>
              ))}
              <div ref={logEndRef} />
            </div>
          </Card>
        </Col>

        {/* Right: Info panel */}
        <Col span={7} style={{ height: "100%" }}>
          <div style={{ height: "100%", overflow: "auto" }}>
          {execution.status === "success" && execution.result_summary && (
            <Card title="执行结果" size="small" style={{ marginBottom: 12 }}>
              <pre style={{ fontSize: 12, margin: 0 }}>
                {JSON.stringify(execution.result_summary, null, 2)}
              </pre>
            </Card>
          )}

          {execution.status === "failed" && execution.error_message && (
            <Card title="错误信息" size="small" style={{ marginBottom: 12, borderColor: "#ff4d4f" }}>
              <pre style={{ fontSize: 12, margin: 0, color: "#ff4d4f", whiteSpace: "pre-wrap" }}>
                {execution.error_message}
              </pre>
            </Card>
          )}

          {execution.config && (
            <Card title="执行配置" size="small" style={{ marginBottom: 12 }}>
              <pre style={{ fontSize: 12, margin: 0 }}>
                {JSON.stringify(
                  Object.fromEntries(
                    Object.entries(execution.config).map(([k, v]) =>
                      /密码|password|secret|token/i.test(k) ? [k, "***"] : [k, v]
                    )
                  ),
                  null,
                  2
                )}
              </pre>
            </Card>
          )}

          {artifacts && artifacts.length > 0 && (
            <Card title="产出文件" size="small" style={{ marginBottom: 12 }}>
              {artifacts.map((a: Artifact) => (
                <div key={a.id} style={{ marginBottom: 4 }}>
                  <a href={a.download_url}>{a.file_name}</a>
                  <span style={{ color: "#999", marginLeft: 8 }}>
                    {(a.size_bytes / 1024).toFixed(1)} KB
                  </span>
                </div>
              ))}
            </Card>
          )}

          {Object.keys(screenshots).length > 0 && (
            <Card title="截图" size="small">
              <Image.PreviewGroup>
                {Object.entries(screenshots).map(([key, url]) => (
                  <Image key={key} src={url} width={100} style={{ marginRight: 8, marginBottom: 8 }} />
                ))}
              </Image.PreviewGroup>
            </Card>
          )}
          </div>
        </Col>
      </Row>
    </div>
  );
}
