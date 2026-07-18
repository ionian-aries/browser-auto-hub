import { Button, Card, Descriptions, Table, Tag } from "antd";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { executionApi, pipelineApi } from "../api/client";

const statusColors: Record<string, string> = {
  pending: "default", running: "processing", success: "success", failed: "error", cancelled: "warning",
};

export function PipelineDetail() {
  const { name } = useParams<{ name: string }>();
  const { data: pipeline } = useQuery({
    queryKey: ["pipeline", name],
    queryFn: () => pipelineApi.get(name!),
    enabled: !!name,
  });
  const { data: executions } = useQuery({
    queryKey: ["executions", { pipeline: name }],
    queryFn: () => executionApi.list({ pipeline: name }),
    enabled: !!name,
  });

  if (!pipeline) return <div>Loading...</div>;

  return (
    <div>
      <h2>{pipeline.display_name}</h2>
      <Card style={{ marginBottom: 16 }}>
        <Descriptions bordered column={2}>
          <Descriptions.Item label="标识">{pipeline.name}</Descriptions.Item>
          <Descriptions.Item label="状态"><Tag>{pipeline.status}</Tag></Descriptions.Item>
          <Descriptions.Item label="描述" span={2}>{pipeline.description}</Descriptions.Item>
          <Descriptions.Item label="触发方式">
            {pipeline.trigger_modes.map((m) => <Tag key={m}>{m}</Tag>)}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {pipeline.config_schema && (
        <Card title="配置模板" style={{ marginBottom: 16 }}>
          <pre>{JSON.stringify(pipeline.config_schema, null, 2)}</pre>
        </Card>
      )}

      <Card title="执行历史">
        <Button
          type="primary"
          style={{ marginBottom: 16 }}
          onClick={() => executionApi.create({ pipeline: pipeline.name, trigger_type: "manual" })}
        >
          手动触发
        </Button>
        <Table
          dataSource={executions}
          rowKey="id"
          columns={[
            { title: "ID", dataIndex: "id" },
            { title: "状态", dataIndex: "status", render: (s: string) => <Tag color={statusColors[s]}>{s}</Tag> },
            { title: "触发方式", dataIndex: "trigger_type" },
            { title: "创建时间", dataIndex: "created_at" },
          ]}
        />
      </Card>
    </div>
  );
}
