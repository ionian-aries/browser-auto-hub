import { useState } from "react";
import { Button, Card, Descriptions, InputNumber, Space, Switch, Table, Tabs, Tag, message } from "antd";
import { useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { executionApi, pipelineApi, scheduleApi } from "../api/client";
import { ExecuteModal } from "../components/ExecuteModal";
import { ScheduleCreateModal } from "../components/ScheduleCreateModal";
import type { Schedule } from "../types";

const statusColors: Record<string, string> = {
  pending: "default", running: "processing", success: "success", failed: "error", cancelled: "warning",
};

export function PipelineDetail() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [executeOpen, setExecuteOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [editSchedule, setEditSchedule] = useState<Schedule | null>(null);
  const [editConcurrent, setEditConcurrent] = useState<number | null>(null);
  const [editTimeout, setEditTimeout] = useState<number | null>(null);

  const { data: pipeline } = useQuery({
    queryKey: ["pipeline", name],
    queryFn: () => pipelineApi.get(name!),
    enabled: !!name,
  });
  const { data: schedules } = useQuery({
    queryKey: ["schedules", { pipeline_id: pipeline?.id }],
    queryFn: () => scheduleApi.list({ pipeline_id: pipeline?.id }),
    enabled: !!pipeline,
  });
  const { data: executions } = useQuery({
    queryKey: ["executions", { pipeline: name }],
    queryFn: () => executionApi.list({ pipeline: name }),
    enabled: !!name,
  });

  const patchMutation = useMutation({
    mutationFn: (data: { max_concurrent?: number; timeout_seconds?: number }) =>
      pipelineApi.patch(name!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline", name] });
      message.success("已保存");
    },
  });
  const toggleMutation = useMutation({
    mutationFn: (id: string) => scheduleApi.toggle(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => scheduleApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] }),
  });

  if (!pipeline) return <div>Loading...</div>;

  const tabItems = [
    {
      key: "overview",
      label: "概览",
      children: (
        <div>
          <Card>
            <Descriptions bordered column={2}>
              <Descriptions.Item label="标识">{pipeline.name}</Descriptions.Item>
              <Descriptions.Item label="状态"><Tag>{pipeline.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="描述" span={2}>{pipeline.description}</Descriptions.Item>
              <Descriptions.Item label="触发方式">
                {pipeline.trigger_modes.map((m) => <Tag key={m}>{m}</Tag>)}
              </Descriptions.Item>
              <Descriptions.Item label="最大并发">
                <Space>
                  <InputNumber
                    min={1}
                    value={editConcurrent ?? pipeline.max_concurrent}
                    onChange={(v) => setEditConcurrent(v)}
                    style={{ width: 80 }}
                  />
                  {editConcurrent !== null && editConcurrent !== pipeline.max_concurrent && (
                    <Button size="small" type="primary" onClick={() => { patchMutation.mutate({ max_concurrent: editConcurrent! }); setEditConcurrent(null); }}>保存</Button>
                  )}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="执行超时">
                <Space>
                  <InputNumber
                    min={60}
                    value={editTimeout ?? pipeline.timeout_seconds}
                    onChange={(v) => setEditTimeout(v)}
                    style={{ width: 100 }}
                    addonAfter="秒"
                  />
                  <span style={{ color: "#999" }}>
                    ({Math.round((editTimeout ?? pipeline.timeout_seconds) / 60)} 分钟)
                  </span>
                  {editTimeout !== null && editTimeout !== pipeline.timeout_seconds && (
                    <Button size="small" type="primary" onClick={() => { patchMutation.mutate({ timeout_seconds: editTimeout! }); setEditTimeout(null); }}>保存</Button>
                  )}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {new Date(pipeline.created_at).toLocaleString()}
              </Descriptions.Item>
            </Descriptions>
          </Card>
          {pipeline.config_schema && (
            <Card title="配置模板" style={{ marginTop: 16 }}>
              <pre style={{ fontSize: 12 }}>{JSON.stringify(pipeline.config_schema, null, 2)}</pre>
            </Card>
          )}
        </div>
      ),
    },
    {
      key: "schedules",
      label: "调度管理",
      children: (
        <div>
          <Button type="primary" style={{ marginBottom: 16 }} onClick={() => { setEditSchedule(null); setScheduleOpen(true); }}>
            新建调度
          </Button>
          <Table
            dataSource={schedules}
            rowKey="id"
            columns={[
              { title: "名称", dataIndex: "name" },
              { title: "类型", dataIndex: "trigger_type" },
              { title: "表达式/间隔", render: (_, r: Schedule) => r.cron_expr || (r.interval_seconds ? `${r.interval_seconds}s` : "-") },
              { title: "启用", render: (_, r: Schedule) => <Switch checked={r.enabled} onChange={() => toggleMutation.mutate(r.id)} /> },
              { title: "下次执行", dataIndex: "next_run_at", render: (v: string) => v || "-" },
              {
                title: "操作",
                render: (_, r: Schedule) => (
                  <Space>
                    <Button size="small" onClick={() => { setEditSchedule(r); setScheduleOpen(true); }}>编辑</Button>
                    <Button size="small" danger onClick={() => deleteMutation.mutate(r.id)}>删除</Button>
                  </Space>
                ),
              },
            ]}
          />
        </div>
      ),
    },
    {
      key: "history",
      label: "执行历史",
      children: (
        <Table
          dataSource={executions}
          rowKey="id"
          onRow={(record) => ({ onClick: () => navigate(`/executions/${record.id}`), style: { cursor: "pointer" } })}
          columns={[
            { title: "状态", dataIndex: "status", render: (s: string) => <Tag color={statusColors[s]}>{s}</Tag> },
            { title: "触发方式", dataIndex: "trigger_type" },
            { title: "开始时间", dataIndex: "started_at", render: (v: string) => v ? new Date(v).toLocaleString() : "-" },
            {
              title: "耗时",
              render: (_: unknown, r: { started_at: string | null; finished_at: string | null }) => {
                if (!r.started_at) return "-";
                const end = r.finished_at ? new Date(r.finished_at).getTime() : Date.now();
                const sec = Math.floor((end - new Date(r.started_at).getTime()) / 1000);
                return sec < 60 ? `${sec}s` : `${Math.floor(sec / 60)}m ${sec % 60}s`;
              },
            },
            { title: "重试", dataIndex: "retry_count", render: (v: number) => v > 0 ? v : "-" },
          ]}
          pagination={{ pageSize: 20 }}
        />
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h2>{pipeline.display_name} <Tag color={pipeline.status === "active" ? "success" : "default"}>{pipeline.status}</Tag></h2>
        <Button type="primary" onClick={() => setExecuteOpen(true)}>立即执行</Button>
      </div>

      <Tabs items={tabItems} />

      <ExecuteModal pipeline={pipeline} open={executeOpen} onClose={() => setExecuteOpen(false)} />
      <ScheduleCreateModal
        pipelineId={pipeline.id}
        open={scheduleOpen}
        onClose={() => setScheduleOpen(false)}
        editSchedule={editSchedule}
      />
    </div>
  );
}
