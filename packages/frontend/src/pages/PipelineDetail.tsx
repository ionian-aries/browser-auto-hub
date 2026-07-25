import { useState } from "react";
import { Button, Card, Descriptions, InputNumber, Popconfirm, Result, Space, Switch, Table, Tabs, Tag, message } from "antd";
import { useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { executionApi, pipelineApi, scheduleApi } from "../api/client";
import { RunModal } from "../components/RunModal";
import { pipelineStatusLabels, scheduleTypeLabels, statusColors, statusLabels, triggerLabels, triggerModeLabels } from "../labels";
import { durationSeconds, formatDuration } from "../utils/format";
import type { Pipeline, Schedule } from "../types";

export function PipelineDetail() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [editConcurrent, setEditConcurrent] = useState<number | null>(null);
  const [editTimeout, setEditTimeout] = useState<number | null>(null);
  const [runOpen, setRunOpen] = useState(false);
  const [runMode, setRunMode] = useState<"now" | "schedule">("now");
  const [editSchedule, setEditSchedule] = useState<Schedule | null>(null);

  const { data: pipeline, error: pipelineError } = useQuery({
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
    queryFn: () => executionApi.listItems({ pipeline: name }),
    enabled: !!name,
  });

  const patchMutation = useMutation({
    mutationFn: (data: { max_concurrent?: number; timeout_seconds?: number }) =>
      pipelineApi.patch(name!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline", name] });
      message.success("保存成功");
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

  if (pipelineError) {
    return (
      <Result
        status="404"
        title="流水线不存在"
        subTitle="该流水线可能已被移除，或链接有误"
        extra={<Button type="primary" onClick={() => navigate("/pipelines")}>返回流水线列表</Button>}
      />
    );
  }
  if (!pipeline) return <div>加载中...</div>;

  const tabItems = [
    {
      key: "overview",
      label: "概览",
      children: (
        <div>
          <Card>
            <Descriptions bordered column={2}>
              <Descriptions.Item label="标识">{pipeline.name}</Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={pipeline.status === "active" ? "success" : "default"}>{pipelineStatusLabels[pipeline.status] ?? pipeline.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="描述" span={2}>{pipeline.description}</Descriptions.Item>
              <Descriptions.Item label="触发方式">
                {pipeline.trigger_modes.map((m) => <Tag key={m}>{triggerModeLabels[m] ?? m}</Tag>)}
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
                {new Date(pipeline.created_at).toLocaleString("zh-CN", { hour12: false })}
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
          <Button type="primary" style={{ marginBottom: 16 }} onClick={() => { setEditSchedule(null); setRunMode("schedule"); setRunOpen(true); }}>
            新建调度
          </Button>
          <Table
            dataSource={schedules}
            rowKey="id"
            columns={[
              { title: "名称", dataIndex: "name" },
              { title: "类型", dataIndex: "trigger_type", render: (t: string) => scheduleTypeLabels[t] ?? t },
              {
                title: "表达式/间隔/时刻",
                render: (_, r: Schedule) =>
                  r.cron_expr ||
                  (r.interval_seconds ? `${r.interval_seconds}s` : null) ||
                  (r.run_at ? new Date(r.run_at).toLocaleString("zh-CN", { hour12: false }) : "-"),
              },
              { title: "启用", render: (_, r: Schedule) => <Switch checked={r.enabled} onChange={() => toggleMutation.mutate(r.id)} /> },
              { title: "下次执行", dataIndex: "next_run_at", render: (v: string) => v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "-" },
              {
                title: "操作",
                render: (_, r: Schedule) => (
                  <Space>
                    <Button size="small" onClick={() => { setEditSchedule(r); setRunOpen(true); }}>编辑</Button>
                    <Popconfirm title="确认删除该调度？" onConfirm={() => deleteMutation.mutate(r.id)}>
                      <Button size="small" danger>删除</Button>
                    </Popconfirm>
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
            { title: "状态", dataIndex: "status", render: (s: string) => <Tag color={statusColors[s]}>{statusLabels[s] ?? s}</Tag> },
            { title: "触发方式", dataIndex: "trigger_type", render: (t: string) => triggerLabels[t] ?? t },
            { title: "开始时间", dataIndex: "started_at", render: (v: string) => v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "-" },
            {
              title: "耗时",
              render: (_: unknown, r: { started_at: string | null; finished_at: string | null }) => {
                const sec = durationSeconds(r.started_at, r.finished_at);
                return sec === null ? "-" : formatDuration(sec);
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
        <h2>{pipeline.display_name} <span style={{ fontSize: 13, color: "#999", fontWeight: "normal" }}>v{pipeline.version}</span> <Tag color={pipeline.status === "active" ? "success" : "default"}>{pipelineStatusLabels[pipeline.status] ?? pipeline.status}</Tag></h2>
        <Button type="primary" disabled={pipeline.status !== "active"} onClick={() => { setEditSchedule(null); setRunMode("now"); setRunOpen(true); }}>立即执行</Button>
      </div>

      <Tabs items={tabItems} />

      <RunModal
        open={runOpen}
        onClose={() => setRunOpen(false)}
        pipeline={pipeline as Pipeline}
        mode={runMode}
        editSchedule={editSchedule}
      />
    </div>
  );
}
