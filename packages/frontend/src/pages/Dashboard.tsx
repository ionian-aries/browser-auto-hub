import type { ReactNode, UIEvent } from "react";
import { Card, Col, Row, Spin, Statistic, Tag } from "antd";
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  NodeIndexOutlined,
  PlayCircleOutlined,
} from "@ant-design/icons";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { executionApi, pipelineApi } from "../api/client";
import { DonutChart } from "../components/DonutChart";
import { LIST_PAGE_STYLE } from "../components/ListPage";
import { statusColors, statusLabels, triggerLabels } from "../labels";
import { durationSeconds, formatDuration } from "../utils/format";

const PAGE_SIZE = 20;

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
  // 最近执行：无限滚动（无分页器，滚底自动加载下一页，spec 4 §3.1 二十六次修订）
  const {
    data: execPages,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["executions", "dashboard-recent"],
    queryFn: ({ pageParam }) =>
      executionApi.list({ page: pageParam, page_size: PAGE_SIZE }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, allPages) =>
      allPages.length * PAGE_SIZE < lastPage.total ? allPages.length + 1 : undefined,
  });
  const recentExecs = execPages?.pages.flatMap((p) => p.items) ?? [];

  const onListScroll = (e: UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80 && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  };

  const activePipelines = pipelines?.filter((p) => p.status === "active").length ?? 0;
  const totalPipelines = pipelines?.length ?? 0;

  const todayTotal = stats?.today_count ?? 0;
  const donutData = [
    { label: "成功", value: stats?.today_success ?? 0, color: "#52c41a" },
    { label: "失败", value: stats?.today_failed ?? 0, color: "#ff4d4f" },
  ];
  const finishedTotal = donutData[0].value + donutData[1].value;

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
      value: todayTotal,
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
    <div style={LIST_PAGE_STYLE}>
      <h2>看板</h2>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16, flexShrink: 0 }}>
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

      {/* 底部左右分栏，占满剩余高度 */}
      <Row gutter={16} style={{ flex: 1, minHeight: 0 }} wrap={false}>
        <Col flex="2" style={{ minWidth: 0, display: "flex" }}>
          <Card title="今日执行分布" style={{ width: "100%" }} styles={{ body: { display: "flex", flexDirection: "column", alignItems: "center", gap: 16 } }}>
            <DonutChart data={donutData} centerValue={todayTotal} centerTitle="今日执行（次）" />
            <div style={{ width: "100%" }}>
              {donutData.map((d) => (
                <div
                  key={d.label}
                  style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, fontSize: 13 }}
                >
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: d.color, flexShrink: 0 }} />
                  <span style={{ color: "#666" }}>{d.label}</span>
                  <span style={{ marginLeft: "auto", fontWeight: 600 }}>
                    {d.value}
                    <span style={{ color: "#999", fontWeight: 400, marginLeft: 6 }}>
                      {finishedTotal > 0 ? `${Math.round((d.value / finishedTotal) * 100)}%` : "-"}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </Col>
        <Col flex="3" style={{ minWidth: 0, display: "flex" }}>
          <Card
            title="最近执行"
            extra={<a onClick={() => navigate("/executions")}>查看全部</a>}
            style={{ width: "100%", display: "flex", flexDirection: "column" }}
            styles={{ body: { flex: 1, minHeight: 0, overflow: "hidden", padding: 0, display: "flex", flexDirection: "column" } }}
          >
            {/* 固定表头（滚动容器外，吸顶；spec 4 §3.1 二十八/二十九次修订） */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "8px 16px",
                borderBottom: "1px solid #f0f0f0",
                fontSize: 12,
                fontWeight: 500,
                color: "#595959",
                flexShrink: 0,
              }}
            >
              <span style={{ flex: 1, minWidth: 0 }}>流水线</span>
              <span style={{ width: 160 }}>时间</span>
              <span style={{ width: 76 }}>状态</span>
              <span style={{ width: 72 }}>触发方式</span>
              <span style={{ width: 76 }}>耗时</span>
            </div>
            <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }} onScroll={onListScroll}>
              {recentExecs.map((exec) => {
                const sec = durationSeconds(exec.started_at, exec.finished_at);
                const time = exec.finished_at ?? exec.started_at;
                return (
                  <div
                    key={exec.id}
                    onClick={() => navigate(`/executions/${exec.id}`)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      padding: "10px 16px",
                      borderBottom: "1px solid #f0f0f0",
                      cursor: "pointer",
                      fontSize: 13,
                    }}
                  >
                    <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 500 }}>
                      {exec.pipeline_display_name ?? exec.pipeline_name ?? "-"}
                    </span>
                    <span style={{ color: "#999", width: 160 }}>
                      {time ? new Date(time).toLocaleString("zh-CN", { hour12: false }) : "-"}
                    </span>
                    <span style={{ width: 76 }}>
                      <Tag color={statusColors[exec.status]} style={{ marginRight: 0 }}>
                        {statusLabels[exec.status] ?? exec.status}
                      </Tag>
                    </span>
                    <span style={{ color: "#666", width: 72 }}>{triggerLabels[exec.trigger_type] ?? exec.trigger_type}</span>
                    <span style={{ color: "#666", width: 76 }}>{sec === null ? "-" : formatDuration(sec)}</span>
                  </div>
                );
              })}
              {isFetchingNextPage && (
                <div style={{ textAlign: "center", padding: 12 }}>
                  <Spin size="small" />
                </div>
              )}
              {!hasNextPage && recentExecs.length > 0 && (
                <div style={{ textAlign: "center", padding: 12, color: "#bbb", fontSize: 12 }}>
                  已加载全部
                </div>
              )}
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
