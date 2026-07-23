import { useState } from "react";
import { Button, DatePicker, Popconfirm, Select, Table, Tag, message } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import type { Dayjs } from "dayjs";
import { executionApi, pipelineApi } from "../api/client";
import { statusColors, statusLabels, triggerLabels } from "../labels";
import type { Execution } from "../types";

const { RangePicker } = DatePicker;

export function Executions() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [pipelineFilter, setPipelineFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string[] | undefined>();
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [page, setPage] = useState(1);

  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });
  const { data, isLoading } = useQuery({
    queryKey: [
      "executions",
      {
        pipeline: pipelineFilter,
        status: statusFilter?.join(","),
        start: dateRange?.[0]?.toISOString(),
        end: dateRange?.[1]?.toISOString(),
        page,
      },
    ],
    queryFn: () =>
      executionApi.list({
        pipeline: pipelineFilter,
        status: statusFilter?.join(","),
        start: dateRange?.[0]?.toISOString(),
        end: dateRange?.[1]?.toISOString(),
        page,
      }),
    refetchInterval: 5000,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => executionApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["executions"] });
      message.success("删除成功");
    },
    onError: () => {
      message.error("删除失败");
    },
  });

  return (
    <div>
      <h2>执行记录</h2>

      <div style={{ marginBottom: 16, display: "flex", gap: 12 }}>
        <Select
          placeholder="全部流水线"
          allowClear
          style={{ width: 200 }}
          value={pipelineFilter}
          onChange={(v) => { setPipelineFilter(v); setPage(1); }}
        >
          {pipelines?.map((p) => (
            <Select.Option key={p.name} value={p.name}>{p.display_name}</Select.Option>
          ))}
        </Select>
        <Select
          placeholder="全部状态"
          allowClear
          mode="multiple"
          style={{ width: 250 }}
          value={statusFilter}
          onChange={(v) => { setStatusFilter(v.length ? v : undefined); setPage(1); }}
        >
          {Object.entries(statusLabels).map(([value, label]) => (
            <Select.Option key={value} value={value}>{label}</Select.Option>
          ))}
        </Select>
        <RangePicker
          showTime={{ format: "HH:mm" }}
          format="YYYY-MM-DD HH:mm"
          placeholder={["开始时间", "结束时间"]}
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) {
              setDateRange([dates[0], dates[1]]);
            } else {
              setDateRange(null);
            }
            setPage(1);
          }}
        />
      </div>

      <Table
        dataSource={data?.items}
        rowKey="id"
        loading={isLoading}
        onRow={(record) => ({
          onClick: () => navigate(`/executions/${record.id}`),
          style: { cursor: "pointer" },
        })}
        pagination={{ current: page, pageSize: 20, total: data?.total, onChange: setPage }}
        columns={[
          {
            title: "流水线",
            render: (_: unknown, r: Execution) =>
              r.pipeline_name ? (
                <Link to={`/pipelines/${r.pipeline_name}`}>{r.pipeline_display_name ?? r.pipeline_name}</Link>
              ) : (
                "-"
              ),
          },
          {
            title: "状态",
            dataIndex: "status",
            render: (s: string) => <Tag color={statusColors[s]}>{statusLabels[s] ?? s}</Tag>,
          },
          {
            title: "触发方式",
            dataIndex: "trigger_type",
            render: (t: string) => triggerLabels[t] ?? t,
          },
          {
            title: "开始时间",
            dataIndex: "started_at",
            render: (v: string) => v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "-",
          },
          {
            title: "耗时",
            render: (_: unknown, r: Execution) => {
              if (!r.started_at) return "-";
              const end = r.finished_at ? new Date(r.finished_at).getTime() : Date.now();
              const seconds = Math.floor((end - new Date(r.started_at).getTime()) / 1000);
              return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
            },
          },
          {
            title: "重试",
            dataIndex: "retry_count",
            render: (v: number) => v > 0 ? v : "-",
          },
          {
            title: "结果",
            render: (_: unknown, r: Execution) => {
              if (r.result_summary) {
                return <span style={{ color: "#666" }}>{JSON.stringify(r.result_summary).slice(0, 40)}</span>;
              }
              if (r.error_message) {
                return <span style={{ color: "#ff4d4f" }}>{r.error_message.slice(0, 40)}</span>;
              }
              return "-";
            },
          },
          {
            title: "操作",
            render: (_: unknown, r: Execution) =>
              r.status !== "pending" && r.status !== "running" ? (
                // React portal 合成事件沿组件树冒泡：必须拦截，否则确认删除会触发行 onClick 误入详情
                <span onClick={(e) => e.stopPropagation()}>
                  <Popconfirm
                    title="确认删除该执行记录？"
                    description="仅删除执行记录与关联日志；MinIO 文件与业务数据不受影响"
                    onConfirm={() => deleteMutation.mutate(r.id)}
                  >
                    <Button size="small" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </span>
              ) : null,
          },
        ]}
      />
    </div>
  );
}
