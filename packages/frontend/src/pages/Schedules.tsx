import { useState } from "react";
import { Button, Popconfirm, Space, Switch, Table, message } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { scheduleApi } from "../api/client";
import { RunModal } from "../components/RunModal";
import { scheduleTypeLabels } from "../labels";
import type { Schedule } from "../types";

export function Schedules() {
  const queryClient = useQueryClient();
  const [runOpen, setRunOpen] = useState(false);
  const [editSchedule, setEditSchedule] = useState<Schedule | null>(null);

  const { data: schedules } = useQuery({
    queryKey: ["schedules"],
    queryFn: () => scheduleApi.list(),
  });

  const toggleMutation = useMutation({
    mutationFn: (id: string) => scheduleApi.toggle(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => scheduleApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      message.success("删除成功");
    },
    onError: () => {
      message.error("删除失败");
    },
  });

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h2>调度管理</h2>
        <Button type="primary" onClick={() => { setEditSchedule(null); setRunOpen(true); }}>
          新建调度
        </Button>
      </div>
      <Table
        dataSource={schedules}
        rowKey="id"
        columns={[
          { title: "名称", dataIndex: "name" },
          {
            title: "流水线",
            render: (_, r: Schedule) =>
              r.pipeline_name ? (
                <Link to={`/pipelines/${r.pipeline_name}`}>{r.pipeline_display_name ?? r.pipeline_name}</Link>
              ) : (
                "-"
              ),
          },
          { title: "类型", dataIndex: "trigger_type", render: (t: string) => scheduleTypeLabels[t] ?? t },
          {
            title: "表达式/间隔/时刻",
            render: (_, r: Schedule) =>
              r.cron_expr ||
              (r.interval_seconds ? `${r.interval_seconds}s` : null) ||
              (r.run_at ? new Date(r.run_at).toLocaleString("zh-CN", { hour12: false }) : "-"),
          },
          {
            title: "启用",
            render: (_, r: Schedule) => <Switch checked={r.enabled} onChange={() => toggleMutation.mutate(r.id)} />,
          },
          {
            title: "下次执行",
            dataIndex: "next_run_at",
            render: (v: string) => (v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "-"),
          },
          {
            title: "操作",
            render: (_, r: Schedule) => (
              <Space>
                <Button size="small" onClick={() => { setEditSchedule(r); setRunOpen(true); }}>
                  编辑
                </Button>
                <Popconfirm title="确认删除该调度？" onConfirm={() => deleteMutation.mutate(r.id)}>
                  <Button size="small" danger>
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <RunModal
        open={runOpen}
        onClose={() => setRunOpen(false)}
        mode="schedule"
        editSchedule={editSchedule}
      />
    </div>
  );
}
