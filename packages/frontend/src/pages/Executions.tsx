import { useState } from "react";
import { DatePicker, Select, Table, Tag } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import { executionApi, pipelineApi } from "../api/client";
import type { Execution } from "../types";

const { RangePicker } = DatePicker;

const statusColors: Record<string, string> = {
  pending: "default", running: "processing", success: "success", failed: "error", cancelled: "warning",
};

export function Executions() {
  const navigate = useNavigate();
  const [pipelineFilter, setPipelineFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string[] | undefined>();
  const [page, setPage] = useState(1);

  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });
  const { data: executions, isLoading } = useQuery({
    queryKey: ["executions", { pipeline: pipelineFilter, status: statusFilter?.join(","), page }],
    queryFn: () => executionApi.list({ pipeline: pipelineFilter, status: statusFilter?.join(","), page }),
    refetchInterval: 5000,
  });

  return (
    <div>
      <h2>执行记录</h2>

      <div style={{ marginBottom: 16, display: "flex", gap: 12 }}>
        <Select
          placeholder="全部 Pipeline"
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
          {["pending", "running", "success", "failed", "cancelled"].map((s) => (
            <Select.Option key={s} value={s}>{s}</Select.Option>
          ))}
        </Select>
        <RangePicker
          onChange={(dates) => {
            // Pass date range to API when backend supports it
            void dates;
            setPage(1);
          }}
        />
      </div>

      <Table
        dataSource={executions}
        rowKey="id"
        loading={isLoading}
        onRow={(record) => ({
          onClick: () => navigate(`/executions/${record.id}`),
          style: { cursor: "pointer" },
        })}
        pagination={{ current: page, pageSize: 20, onChange: setPage }}
        columns={[
          {
            title: "Pipeline",
            dataIndex: "pipeline_name",
            render: (name: string) => name ? <Link to={`/pipelines/${name}`}>{name}</Link> : "-",
          },
          {
            title: "状态",
            dataIndex: "status",
            render: (s: string) => <Tag color={statusColors[s]}>{s}</Tag>,
          },
          { title: "触发方式", dataIndex: "trigger_type" },
          {
            title: "开始时间",
            dataIndex: "started_at",
            render: (v: string) => v ? new Date(v).toLocaleString() : "-",
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
            dataIndex: "result_summary",
            render: (v: Record<string, unknown> | null) =>
              v ? <span style={{ color: "#666" }}>{JSON.stringify(v).slice(0, 40)}</span> : "-",
          },
        ]}
      />
    </div>
  );
}
