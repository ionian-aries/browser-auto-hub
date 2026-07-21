import { useEffect, useRef, useState } from "react";
import { Button, Card, Col, Empty, Image, Row, Tag, message } from "antd";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { executionApi, fileApi } from "../api/client";
import type { Artifact, LogEntry } from "../types";

const statusColors: Record<string, string> = {
  pending: "default", running: "processing", success: "success", failed: "error", cancelled: "warning",
};
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
  const logEndRef = useRef<HTMLDivElement>(null);
  const userScrolledRef = useRef(false);
  const stepColorMap = useRef(new Map<string, string>());

  const { data: execution } = useQuery({
    queryKey: ["execution", id],
    queryFn: () => executionApi.get(id!),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 3000 : false,
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
      const source = new EventSource(`/api/executions/${id}/logs/stream`);
      source.onmessage = (event) => {
        const entry = JSON.parse(event.data);
        if (entry.type === "complete") {
          source.close();
          queryClient.invalidateQueries({ queryKey: ["execution", id] });
          return;
        }
        setLogs((prev) => [...prev, entry]);
      };
      return () => source.close();
    } else {
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
    const newKeys = keys.filter((k) => !screenshots[k]);
    newKeys.forEach((key) => {
      fileApi.presign(key).then(({ url }) => {
        setScreenshots((prev) => ({ ...prev, [key]: url }));
      });
    });
  }, [logs]);

  if (!execution) return <div>Loading...</div>;

  const filteredLogs = filter === "all" ? logs : logs.filter((l) => l.level === filter);
  const duration = execution.started_at
    ? Math.floor(
        ((execution.finished_at ? new Date(execution.finished_at).getTime() : Date.now()) -
          new Date(execution.started_at).getTime()) /
          1000
      )
    : 0;

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <h2 style={{ display: "inline" }}>
            <Link to={`/pipelines/${execution.pipeline_name}`}>{execution.pipeline_name}</Link>
            {" "}
            <span style={{ fontSize: 14, color: "#999" }}>#{execution.id.slice(0, 8)}</span>
          </h2>
          <div style={{ marginTop: 8 }}>
            <Tag color={statusColors[execution.status]}>{execution.status}</Tag>
            <Tag>{execution.trigger_type}</Tag>
            {execution.started_at && <span style={{ color: "#666" }}>{new Date(execution.started_at).toLocaleString()}</span>}
            {duration > 0 && <span style={{ color: "#666", marginLeft: 8 }}>耗时 {duration}s</span>}
          </div>
        </div>
        {(execution.status === "pending" || execution.status === "running") && (
          <Button danger onClick={() => cancelMutation.mutate()}>取消执行</Button>
        )}
      </div>

      {/* Main content: left/right split */}
      <Row gutter={16}>
        {/* Left: Log stream */}
        <Col span={17}>
          <Card
            title="执行日志"
            size="small"
            extra={
              <span>
                {["all", "info", "warn", "error"].map((level) => (
                  <Tag
                    key={level}
                    color={filter === level ? "blue" : "default"}
                    style={{ cursor: "pointer" }}
                    onClick={() => setFilter(level)}
                  >
                    {level === "all" ? "全部" : level}
                  </Tag>
                ))}
              </span>
            }
          >
            <div
              style={{ height: 500, overflow: "auto", fontFamily: "monospace", fontSize: 12 }}
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
                  <span style={{ color: "#999" }}>{new Date(log.timestamp).toLocaleTimeString()}</span>
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
        <Col span={7}>
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
        </Col>
      </Row>
    </div>
  );
}
