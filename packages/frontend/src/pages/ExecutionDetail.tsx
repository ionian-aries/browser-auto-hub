import { useEffect, useState } from "react";
import { Descriptions, Tag, Timeline } from "antd";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { executionApi } from "../api/client";
import type { LogEntry } from "../types";

export function ExecutionDetail() {
  const { id } = useParams<{ id: string }>();
  const executionId = id!;
  const { data: execution } = useQuery({
    queryKey: ["execution", executionId],
    queryFn: () => executionApi.get(executionId),
  });
  const [logs, setLogs] = useState<LogEntry[]>([]);

  useEffect(() => {
    if (!executionId) return;

    if (execution?.status === "running") {
      const source = new EventSource(`/api/executions/${executionId}/logs/stream`);
      source.onmessage = (event) => {
        const entry = JSON.parse(event.data);
        if (entry.type === "complete") {
          source.close();
          return;
        }
        setLogs((prev) => [...prev, entry]);
      };
      return () => source.close();
    } else if (execution) {
      executionApi.getLogs(executionId).then(setLogs);
    }
  }, [executionId, execution?.status]);

  if (!execution) return <div>Loading...</div>;

  return (
    <div>
      <h2>执行详情 #{execution.id}</h2>
      <Descriptions bordered column={2}>
        <Descriptions.Item label="Pipeline">{execution.pipeline_name}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag>{execution.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="触发方式">{execution.trigger_type}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{execution.created_at}</Descriptions.Item>
      </Descriptions>

      <h3 style={{ marginTop: 24 }}>执行步骤</h3>
      <Timeline
        items={logs.map((log) => ({
          color: log.level === "error" ? "red" : log.level === "warn" ? "orange" : "green",
          children: (
            <div>
              <strong>[{log.step}]</strong> {log.message}
              <br />
              <small>{log.timestamp}</small>
            </div>
          ),
        }))}
      />
    </div>
  );
}
