import { Button, Table, Tag } from "antd";
import { useQuery } from "@tanstack/react-query";
import { executionApi, pipelineApi } from "../api/client";
import type { Pipeline } from "../types";

export function Pipelines() {
  const { data, isLoading } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });

  const columns = [
    { title: "名称", dataIndex: "display_name", key: "display_name" },
    { title: "标识", dataIndex: "name", key: "name" },
    {
      title: "触发方式",
      dataIndex: "trigger_modes",
      key: "trigger_modes",
      render: (modes: string[]) => modes.map((m) => <Tag key={m}>{m}</Tag>),
    },
    {
      title: "操作",
      key: "action",
      render: (_: unknown, record: Pipeline) => (
        <Button
          size="small"
          type="primary"
          onClick={() => executionApi.create({ pipeline: record.name, trigger_type: "manual" })}
        >
          手动触发
        </Button>
      ),
    },
  ];

  return (
    <div>
      <h2>Pipeline 列表</h2>
      <Table dataSource={data} columns={columns} rowKey="id" loading={isLoading} />
    </div>
  );
}
