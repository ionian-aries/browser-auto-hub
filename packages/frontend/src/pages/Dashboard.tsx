import type { ReactNode } from "react";
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
import { statusColors, statusLabels, triggerLabels } from "../labels";
import { durationSeconds, formatDuration } from "../utils/format";
import type { Execution } from "../types";

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
    queryFn: () => executionApi.listItems({ page_size: 10 }),
    refetchInterval: 5000,
  });

  const runningTasks = executions?.filter((e) => e.status === "running") ?? [];
  const recentDone = executions?.filter((e) => e.status !== "running").slice(0, 10) ?? [];
  const activePipelines = pipelines?.filter((p) => p.status === "active").length ?? 0;
  const totalPipelines = pipelines?.length ?? 0;

  const statCards: Array<{
    title: string;
    value: number | string;
    suffix?: string;
    icon: ReactNode;
    color: string;
    bg: string;
  }> = [
    {
      title: "流水线（启用 / 总数）",
      value: `${activePipelines} / ${totalPipelines}`,
      icon: <NodeIndexOutlined />,
      color: "#1677ff",
      bg: "#e6f4ff",
    },
    {
      title: "今日执行",
      value: stats?.today_count ?? 0,
      icon: <PlayCircleOutlined />,
      color: "#722ed1",
      bg: "#f9f0ff",
    },
    {
      title: "今日成功率",
      value: stats ? Math.round(stats.success_rate * 100) : 0,
      suffix: "%",
      icon: <CheckCircleOutlined />,
      color: "#52c41a",
      bg: "#f6ffed",
    },
    {
      title: "运行中",
      value: stats?.running_count ?? 0,
      icon: <ClockCircleOutlined />,
      color: "#fa8c16",
      bg: "#fff7e6",
    },
  ];

  return (
    <div>
      <h2>看板</h2>

      {/* Stats cards */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        {statCards.map((card) => (
          <Col span={6} key={card.title}>
            <Card>
              <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                <div
                  style={{
                    width: 48,
                    height: 48,
                    borderRadius: 12,
                    background: card.bg,
                    color: card.color,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 24,
                    flexShrink: 0,
                  }}
                >
                  {card.icon}
                </div>
                <Statistic
                  title={card.title}
                  value={card.value}
                  suffix={card.suffix}
                  valueStyle={{ fontWeight: 600 }}
                />
              </div>
            </Card>
          </Col>
        ))}
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
                  <div style={{ fontWeight: "bold" }}>{exec.pipeline_display_name ?? exec.pipeline_name}</div>
                  <Tag color="processing">{triggerLabels[exec.trigger_type] ?? exec.trigger_type}</Tag>
                  <div style={{ marginTop: 8, color: "#666" }}>
                    运行时长: {formatDuration(durationSeconds(exec.started_at, null) ?? 0)}
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
                <strong>{exec.pipeline_display_name ?? exec.pipeline_name}</strong>{" "}
                <Tag color={statusColors[exec.status]}>{statusLabels[exec.status] ?? exec.status}</Tag>
                {exec.finished_at && exec.started_at && (
                  <span style={{ color: "#999", marginLeft: 8 }}>
                    耗时 {formatDuration(durationSeconds(exec.started_at, exec.finished_at)!)}
                  </span>
                )}
                {exec.finished_at && (
                  <span style={{ color: "#999", marginLeft: 8 }}>
                    {new Date(exec.finished_at).toLocaleString("zh-CN", { hour12: false })}
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
