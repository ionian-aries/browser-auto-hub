import { useState } from "react";
import { Button, Card, Col, Row, Tag } from "antd";
import { PlayCircleOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { executionApi, pipelineApi } from "../api/client";
import { ExecuteModal } from "../components/ExecuteModal";
import type { Execution, Pipeline } from "../types";

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

const statusColors: Record<string, string> = {
  pending: "default", running: "processing", success: "success", failed: "error", cancelled: "warning",
};

export function Pipelines() {
  const navigate = useNavigate();
  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });
  const { data: executions } = useQuery({
    queryKey: ["executions", { page_size: 100 }],
    queryFn: () => executionApi.list({ page_size: 100 }),
  });
  const [executePipeline, setExecutePipeline] = useState<Pipeline | null>(null);

  const getLastExecution = (pipelineName: string): Execution | undefined =>
    executions?.find((e) => e.pipeline_name === pipelineName);

  const handleExecute = (pipeline: Pipeline) => {
    const schema = pipeline.config_schema as { required?: string[] } | null;
    const hasRequired = schema?.required && schema.required.length > 0;

    if (hasRequired) {
      setExecutePipeline(pipeline);
    } else {
      // Direct trigger without modal
      executionApi
        .create({ pipeline: pipeline.name, trigger_type: "manual" })
        .then((exec) => navigate(`/executions/${exec.id}`));
    }
  };

  return (
    <div>
      <h2>Pipeline</h2>
      <Row gutter={[16, 16]}>
        {pipelines?.map((p) => (
          <Col span={8} key={p.id}>
            <Card
              title={
                <a onClick={() => navigate(`/pipelines/${p.name}`)}>
                  {p.display_name}
                </a>
              }
              extra={<Tag color={p.status === "active" ? "success" : "default"}>{p.status}</Tag>}
              actions={[
                <Button
                  key="run"
                  type="link"
                  icon={<PlayCircleOutlined />}
                  onClick={() => handleExecute(p)}
                >
                  立即执行
                </Button>,
              ]}
            >
              <p style={{ color: "#666", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {p.description || "暂无描述"}
              </p>
              <div>
                {p.trigger_modes.map((m) => (
                  <Tag key={m}>{m}</Tag>
                ))}
              </div>
              <div style={{ marginTop: 8, fontSize: 12, color: "#999" }}>
                {(() => {
                  const last = getLastExecution(p.name);
                  if (!last) return "暂无执行记录";
                  return (
                    <>
                      最近执行: <Tag color={statusColors[last.status]} style={{ fontSize: 11 }}>{last.status}</Tag>
                      {last.created_at && formatRelativeTime(last.created_at)}
                    </>
                  );
                })()}
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <ExecuteModal
        pipeline={executePipeline}
        open={!!executePipeline}
        onClose={() => setExecutePipeline(null)}
      />
    </div>
  );
}
