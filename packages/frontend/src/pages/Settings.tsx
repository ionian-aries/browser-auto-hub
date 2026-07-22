import { useState } from "react";
import { Alert, Button, Card, Descriptions, Form, Input, InputNumber, Switch, Tabs, Tag, message } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { systemApi } from "../api/client";

function StatusTab() {
  const { data: info } = useQuery({
    queryKey: ["system-info"],
    queryFn: systemApi.info,
    refetchInterval: 10000,
  });
  const [dbStatus, setDbStatus] = useState<"ok" | "error" | null>(null);
  const [storageStatus, setStorageStatus] = useState<"ok" | "error" | null>(null);

  const testDbMutation = useMutation({
    mutationFn: systemApi.testDb,
    onSuccess: () => {
      setDbStatus("ok");
      message.success("数据库连接正常");
    },
    onError: () => {
      setDbStatus("error");
      message.error("数据库连接失败");
    },
  });

  const testStorageMutation = useMutation({
    mutationFn: systemApi.testStorage,
    onSuccess: (data) => {
      setStorageStatus("ok");
      message.success(data.message);
    },
    onError: () => {
      setStorageStatus("error");
      message.error("MinIO 连接失败");
    },
  });

  return (
    <Card>
      <Descriptions bordered column={1}>
        <Descriptions.Item label="调度器状态">
          <Tag color={info?.scheduler_status === "running" ? "success" : "warning"}>
            {info?.scheduler_status ?? "-"}
          </Tag>
          {info && <span style={{ marginLeft: 8 }}>{info.active_schedules} 个活跃调度</span>}
        </Descriptions.Item>
        <Descriptions.Item label="数据库连接">
          {dbStatus && <Tag color={dbStatus === "ok" ? "success" : "error"}>{dbStatus}</Tag>}
          <Button
            size="small"
            style={{ marginLeft: 8 }}
            onClick={() => testDbMutation.mutate()}
            loading={testDbMutation.isPending}
          >
            测试
          </Button>
        </Descriptions.Item>
        <Descriptions.Item label="MinIO 连接">
          {storageStatus && <Tag color={storageStatus === "ok" ? "success" : "error"}>{storageStatus}</Tag>}
          <Button
            size="small"
            style={{ marginLeft: 8 }}
            onClick={() => testStorageMutation.mutate()}
            loading={testStorageMutation.isPending}
          >
            测试
          </Button>
        </Descriptions.Item>
      </Descriptions>
    </Card>
  );
}

function MinioCard() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["system-settings"], queryFn: systemApi.getSettings });

  const [endpoint, setEndpoint] = useState<string | null>(null);
  const [accessKey, setAccessKey] = useState<string | null>(null);
  const [secretKey, setSecretKey] = useState<string | null>(null);
  const [bucket, setBucket] = useState<string | null>(null);
  const [prefix, setPrefix] = useState<string | null>(null);
  const [expires, setExpires] = useState<number | null>(null);

  const resetDirty = () => {
    setEndpoint(null);
    setAccessKey(null);
    setSecretKey(null);
    setBucket(null);
    setPrefix(null);
    setExpires(null);
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const updates: Record<string, unknown> = {};
      if (endpoint !== null) updates.minio_endpoint = endpoint;
      if (accessKey !== null) updates.minio_access_key = accessKey;
      if (secretKey !== null && secretKey !== "***" && secretKey !== "")
        updates.minio_secret_key = secretKey;
      if (bucket !== null) updates.minio_bucket = bucket;
      if (prefix !== null) updates.minio_object_prefix = prefix;
      if (expires !== null) updates.minio_presign_expires_seconds = expires;
      return systemApi.updateSettings(updates);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["system-settings"] });
      message.success("MinIO 配置已保存");
      resetDirty();
    },
    onError: () => message.error("保存失败"),
  });

  const testMutation = useMutation({
    mutationFn: systemApi.testStorage,
    onSuccess: (data) => message.success(data.message),
    onError: () => message.error("MinIO 连接失败"),
  });

  const expiresValue = expires ?? settings?.minio_presign_expires_seconds ?? 604800;

  return (
    <Card title="MinIO">
      <Form layout="vertical">
        <Form.Item label="Endpoint">
          <Input
            value={endpoint ?? settings?.minio_endpoint ?? ""}
            onChange={(e) => setEndpoint(e.target.value)}
            style={{ maxWidth: 400 }}
          />
        </Form.Item>
        <Form.Item label="Access Key">
          <Input
            value={accessKey ?? settings?.minio_access_key ?? ""}
            onChange={(e) => setAccessKey(e.target.value)}
            style={{ maxWidth: 400 }}
          />
        </Form.Item>
        <Form.Item label="Secret Key">
          <Input.Password
            value={secretKey ?? settings?.minio_secret_key ?? "***"}
            onChange={(e) => setSecretKey(e.target.value)}
            placeholder="*** 表示未修改"
            style={{ maxWidth: 400 }}
          />
        </Form.Item>
        <Form.Item label="Bucket">
          <Input
            value={bucket ?? settings?.minio_bucket ?? ""}
            onChange={(e) => setBucket(e.target.value)}
            style={{ maxWidth: 400 }}
          />
        </Form.Item>
        <Form.Item label="对象前缀">
          <Input
            value={prefix ?? settings?.minio_object_prefix ?? ""}
            onChange={(e) => setPrefix(e.target.value)}
            style={{ maxWidth: 400 }}
          />
        </Form.Item>
        <Form.Item label="预签名过期时间">
          <InputNumber
            value={expiresValue}
            onChange={(v) => setExpires(v)}
            min={1}
            style={{ width: 200 }}
            addonAfter="秒"
          />
          <span style={{ marginLeft: 8, color: "#999" }}>
            （约 {(expiresValue / 86400).toFixed(1)} 天）
          </span>
        </Form.Item>
      </Form>
      <div style={{ display: "flex", gap: 12 }}>
        <Button onClick={() => testMutation.mutate()} loading={testMutation.isPending}>
          测试连接
        </Button>
        <Button type="primary" onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
          保存配置
        </Button>
      </div>
    </Card>
  );
}

function DatabaseCard() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["system-settings"], queryFn: systemApi.getSettings });
  const [dbUrl, setDbUrl] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: () => {
      const updates: Record<string, unknown> = {};
      if (dbUrl !== null && !dbUrl.includes("***") && dbUrl !== "") updates.database_url = dbUrl;
      return systemApi.updateSettings(updates);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["system-settings"] });
      message.success("数据库配置已保存并热切换");
      setDbUrl(null);
    },
    onError: () => message.error("保存失败，请检查数据库连接串"),
  });

  const testMutation = useMutation({
    mutationFn: systemApi.testDb,
    onSuccess: () => message.success("数据库连接正常"),
    onError: () => message.error("数据库连接失败"),
  });

  return (
    <Card title="数据库" style={{ marginTop: 16 }}>
      <Form layout="vertical">
        <Form.Item label="Database URL">
          <Input
            value={dbUrl ?? settings?.database_url ?? ""}
            onChange={(e) => setDbUrl(e.target.value)}
            style={{ maxWidth: 600 }}
          />
        </Form.Item>
      </Form>
      <Alert
        type="warning"
        showIcon
        message="保存后立即热切换数据库连接，无需重启"
        style={{ marginBottom: 16, maxWidth: 600 }}
      />
      <div style={{ display: "flex", gap: 12 }}>
        <Button onClick={() => testMutation.mutate()} loading={testMutation.isPending}>
          测试连接
        </Button>
        <Button type="primary" onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
          保存配置
        </Button>
      </div>
    </Card>
  );
}

function ConnectionTab() {
  return (
    <div>
      <MinioCard />
      <DatabaseCard />
    </div>
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
      queryClient.invalidateQueries({ queryKey: ["system-info"] });
      message.success("已保存");
      setRetention(null);
      setSchedulerEnabled(null);
    },
    onError: () => message.error("保存失败"),
  });

  const enabled = schedulerEnabled ?? settings?.scheduler_enabled ?? true;

  return (
    <Card>
      <Form layout="vertical">
        <Form.Item label="调度器全局开关">
          <div>
            <Switch checked={enabled} onChange={(v) => setSchedulerEnabled(v)} />
            <span style={{ marginLeft: 8, color: "#666" }}>{enabled ? "运行中" : "已暂停"}</span>
          </div>
          <div style={{ color: "#999", marginTop: 4 }}>
            关闭后所有定时调度立即暂停（紧急场景）
          </div>
        </Form.Item>
        <Form.Item label="日志保留天数">
          <InputNumber
            value={retention ?? settings?.log_retention_days ?? 30}
            onChange={(v) => setRetention(v)}
            min={1}
            style={{ width: 200 }}
            addonAfter="天"
          />
          <div style={{ color: "#999", marginTop: 4 }}>
            每日凌晨自动清理过期执行记录与日志
          </div>
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
          { key: "status", label: "运行状态", children: <StatusTab /> },
          { key: "connection", label: "连接配置", children: <ConnectionTab /> },
          { key: "ops", label: "运维策略", children: <OpsTab /> },
        ]}
      />
    </div>
  );
}
