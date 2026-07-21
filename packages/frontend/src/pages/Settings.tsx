import { useState } from "react";
import { Button, Card, Descriptions, Form, Input, InputNumber, Switch, Tabs, Tag, message } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { systemApi } from "../api/client";

function RuntimeTab() {
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: systemApi.health });
  const { data: info } = useQuery({ queryKey: ["system-info"], queryFn: systemApi.info, refetchInterval: 10000 });

  const formatUptime = (seconds: number) => {
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${d}d ${h}h ${m}m`;
  };

  return (
    <Card>
      <Descriptions bordered column={2}>
        <Descriptions.Item label="服务状态">
          <Tag color={health?.status === "ok" ? "success" : "error"}>{health?.status ?? "unknown"}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="版本">{health?.version ?? "-"}</Descriptions.Item>
        <Descriptions.Item label="运行时长">{info ? formatUptime(info.uptime_seconds) : "-"}</Descriptions.Item>
        <Descriptions.Item label="调度器状态">
          <Tag color={info?.scheduler_status === "running" ? "success" : "warning"}>
            {info?.scheduler_status ?? "-"}
          </Tag>
          {info && <span style={{ marginLeft: 8 }}>{info.active_schedules} 个活跃调度</span>}
        </Descriptions.Item>
        <Descriptions.Item label="数据库连接池">
          {info ? `${info.db_pool.checked_out} / ${info.db_pool.pool_size} (overflow: ${info.db_pool.overflow})` : "-"}
        </Descriptions.Item>
      </Descriptions>
    </Card>
  );
}

function StorageTab() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["system-settings"], queryFn: systemApi.getSettings });
  const [prefix, setPrefix] = useState<string | null>(null);
  const [expires, setExpires] = useState<number | null>(null);

  const saveMutation = useMutation({
    mutationFn: () => {
      const updates: Record<string, unknown> = {};
      if (prefix !== null) updates.minio_object_prefix = prefix;
      if (expires !== null) updates.minio_presign_expires_seconds = expires;
      return systemApi.updateSettings(updates);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["system-settings"] });
      message.success("已保存");
      setPrefix(null);
      setExpires(null);
    },
  });

  const testMutation = useMutation({
    mutationFn: systemApi.testStorage,
    onSuccess: (data) => message.success(data.message),
    onError: () => message.error("MinIO 连接失败"),
  });

  return (
    <Card>
      <Descriptions bordered column={1}>
        <Descriptions.Item label="Endpoint（只读）">{settings?.minio_endpoint ?? "-"}</Descriptions.Item>
        <Descriptions.Item label="Bucket（只读）">{settings?.minio_bucket ?? "-"}</Descriptions.Item>
        <Descriptions.Item label="对象前缀">
          <Input
            value={prefix ?? settings?.minio_object_prefix ?? ""}
            onChange={(e) => setPrefix(e.target.value)}
            style={{ width: 300 }}
          />
        </Descriptions.Item>
        <Descriptions.Item label="预签名过期时间">
          <InputNumber
            value={expires ?? Number(settings?.minio_presign_expires_seconds ?? 604800)}
            onChange={(v) => setExpires(v)}
            style={{ width: 200 }}
            addonAfter="秒"
          />
          <span style={{ marginLeft: 8, color: "#999" }}>
            ({Math.round((expires ?? Number(settings?.minio_presign_expires_seconds ?? 604800)) / 86400)} 天)
          </span>
        </Descriptions.Item>
      </Descriptions>
      <div style={{ marginTop: 16, display: "flex", gap: 12 }}>
        <Button type="primary" onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
          保存配置
        </Button>
        <Button onClick={() => testMutation.mutate()} loading={testMutation.isPending}>
          测试连接
        </Button>
      </div>
    </Card>
  );
}

function OpsTab() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["system-settings"], queryFn: systemApi.getSettings });
  const [retention, setRetention] = useState<number | null>(null);
  const [schedulerEnabled, setSchedulerEnabled] = useState<boolean | null>(null);

  const saveMutation = useMutation({
    mutationFn: () => {
      const updates: Record<string, unknown> = {};
      if (retention !== null) updates.log_retention_days = retention;
      if (schedulerEnabled !== null) updates.scheduler_enabled = schedulerEnabled;
      return systemApi.updateSettings(updates);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["system-settings"] });
      message.success("已保存");
      setRetention(null);
      setSchedulerEnabled(null);
    },
  });

  return (
    <Card>
      <Form layout="vertical">
        <Form.Item label="日志保留天数">
          <InputNumber
            value={retention ?? Number(settings?.log_retention_days ?? 30)}
            onChange={(v) => setRetention(v)}
            min={1}
            style={{ width: 200 }}
            addonAfter="天"
          />
        </Form.Item>
        <Form.Item label="调度器全局开关">
          <Switch
            checked={schedulerEnabled ?? (settings?.scheduler_enabled !== "false")}
            onChange={(v) => setSchedulerEnabled(v)}
          />
          <span style={{ marginLeft: 8, color: "#666" }}>
            {(schedulerEnabled ?? (settings?.scheduler_enabled !== "false")) ? "运行中" : "已暂停（所有调度停止）"}
          </span>
        </Form.Item>
      </Form>
      <Button type="primary" onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
        保存配置
      </Button>
    </Card>
  );
}

export function Settings() {
  return (
    <div>
      <h2>系统设置</h2>
      <Tabs
        items={[
          { key: "runtime", label: "运行时信息", children: <RuntimeTab /> },
          { key: "storage", label: "存储配置", children: <StorageTab /> },
          { key: "ops", label: "运维策略", children: <OpsTab /> },
        ]}
      />
    </div>
  );
}
