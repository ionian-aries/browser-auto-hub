import { Card, Descriptions, Tag } from "antd";
import { useQuery } from "@tanstack/react-query";
import { systemApi } from "../api/client";

export function Settings() {
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: systemApi.health });

  return (
    <div>
      <h2>系统设置</h2>
      <Card title="系统状态">
        <Descriptions bordered>
          <Descriptions.Item label="服务状态">
            <Tag color={health?.status === "ok" ? "success" : "error"}>
              {health?.status ?? "unknown"}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="版本">{health?.version ?? "-"}</Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  );
}
