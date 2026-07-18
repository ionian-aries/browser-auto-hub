import { Table, Tag } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { executionApi } from "../api/client";

const statusColors: Record<string, string> = {
  pending: "default",
  running: "processing",
  success: "success",
  failed: "error",
  cancelled: "warning",
};

export function Executions() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({ queryKey: ["executions"], queryFn: () => executionApi.list() });

  const columns = [
    { title: "ID", dataIndex: "id", key: "id" },
    { title: "Pipeline", dataIndex: "pipeline_name", key: "pipeline_name" },
    { title: "触发方式", dataIndex: "trigger_type", key: "trigger_type" },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      render: (status: string) => <Tag color={statusColors[status]}>{status}</Tag>,
    },
    { title: "创建时间", dataIndex: "created_at", key: "created_at" },
  ];

  return (
    <div>
      <h2>执行记录</h2>
      <Table
        dataSource={data}
        columns={columns}
        rowKey="id"
        loading={isLoading}
        onRow={(record) => ({ onClick: () => navigate(`/executions/${record.id}`) })}
      />
    </div>
  );
}
