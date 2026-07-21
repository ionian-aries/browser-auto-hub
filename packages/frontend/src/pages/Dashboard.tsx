import { Card, Col, Empty, Row, Statistic, Tag, Timeline } from "antd";
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  NodeIndexOutlined,
  PlayCircleOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { executionApi, pipelineApi } from "../api/client";
import type { Execution } from "../types";

const statusColors: Record<string, string> = {
  pending: "default",
  running: "processing",
  success: "success",
  failed: "error",
  cancelled: "warning",
};

function formatDuration(startedAt: string | null): string {
  if (!startedAt) return "-";
  const seconds = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000);
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function Dashboard() {
  const navigate = useNavigate();
  const { data: stats } = useQuery({
    queryKey: ["execution-stats"],
    queryFn: executionApi.stats,
    refetchInterval: 5000,
  });
  const { data: pipelines } = useQuery({
    queryKey: ["pipelines"],
    queryFn: pipelineApi.list,
  });
  const { data: executions } = useQuery({
    queryKey: ["executions", { page_size: 10 }],
    queryFn: () => executionApi.list({ page_size: 10 }),
    refetchInterval: 5000,
  });

  const runningTasks = executions?.filter((e) => e.status === "running") ?? [];
  const recentDone = executions?.filter((e) => e.status !== "running").slice(0, 10) ?? [];

  return (
    <div>
      <h2>看板</h2>

      {/* Stats cards */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="Pipeline 总数"
              value={pipelines?.length ?? 0}
              prefix={<NodeIndexOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="今日执行"
              value={stats?.today_count ?? 0}
              prefix={<PlayCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="今日成功率"
              value={stats ? Math.round(stats.success_rate * 100) : 0}
              suffix="%"
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="运行中"
              value={stats?.running_count ?? 0}
              prefix={<ClockCircleOutlined />}
              valueStyle={stats?.running_count ? { color: "#1890ff" } : undefined}
            />
          </Card>
        </Col>
      </Row>

      {/* Running tasks */}
      <Card title="运行中任务" style={{ marginBottom: 24 }}>
        {runningTasks.length === 0 ? (
          <Empty description="当前没有正在执行的任务" />
        ) : (
          <Row gutter={16}>
            {runningTasks.map((exec) => (
              <Col span={8} key={exec.id}>
                <Card
                  hoverable
                  size="small"
                  onClick={() => navigate(`/executions/${exec.id}`)}
                >
                  <div style={{ fontWeight: "bold" }}>{exec.pipeline_name}</div>
                  <Tag color="processing">{exec.trigger_type}</Tag>
                  <div style={{ marginTop: 8, color: "#666" }}>
                    运行时长: {formatDuration(exec.started_at)}
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      {/* Recent timeline */}
      <Card
        title="最近执行"
        extra={<a onClick={() => navigate("/executions")}>查看全部</a>}
      >
        <Timeline
          items={recentDone.map((exec: Execution) => ({
            color: exec.status === "success" ? "green" : exec.status === "failed" ? "red" : "gray",
            children: (
              <div
                style={{ cursor: "pointer" }}
                onClick={() => navigate(`/executions/${exec.id}`)}
              >
                <strong>{exec.pipeline_name}</strong>{" "}
                <Tag color={statusColors[exec.status]}>{exec.status}</Tag>
                {exec.finished_at && exec.started_at && (
                  <span style={{ color: "#999", marginLeft: 8 }}>
                    耗时 {Math.floor((new Date(exec.finished_at).getTime() - new Date(exec.started_at).getTime()) / 1000)}s
                  </span>
                )}
                {exec.finished_at && (
                  <span style={{ color: "#999", marginLeft: 8 }}>
                    {new Date(exec.finished_at).toLocaleString()}
                  </span>
                )}
              </div>
            ),
          }))}
        />
      </Card>
    </div>
  );
}
