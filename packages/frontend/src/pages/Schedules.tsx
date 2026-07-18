import { useState } from "react";
import { Button, Switch, Table } from "antd";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { scheduleApi } from "../api/client";
import { ScheduleCreateModal } from "../components/ScheduleCreateModal";
import type { Schedule } from "../types";

export function Schedules() {
  const [createOpen, setCreateOpen] = useState(false);
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["schedules"], queryFn: scheduleApi.list });
  const toggleMutation = useMutation({
    mutationFn: (id: number) => scheduleApi.toggle(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] }),
  });

  const columns = [
    { title: "名称", dataIndex: "name", key: "name" },
    { title: "Pipeline", dataIndex: "pipeline_name", key: "pipeline_name" },
    { title: "类型", dataIndex: "trigger_type", key: "trigger_type" },
    { title: "Cron", dataIndex: "cron_expr", key: "cron_expr" },
    {
      title: "启用",
      key: "enabled",
      render: (_: unknown, record: Schedule) => (
        <Switch checked={record.enabled} onChange={() => toggleMutation.mutate(record.id)} />
      ),
    },
  ];

  return (
    <div>
      <h2>调度管理</h2>
      <Button type="primary" onClick={() => setCreateOpen(true)} style={{ marginBottom: 16 }}>
        新建调度
      </Button>
      <ScheduleCreateModal open={createOpen} onClose={() => setCreateOpen(false)} />
      <Table dataSource={data} columns={columns} rowKey="id" loading={isLoading} />
    </div>
  );
}
