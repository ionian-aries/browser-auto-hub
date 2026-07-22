import { useState } from "react";
import { Alert, Button, Card, Col, Form, Input, InputNumber, Row, Switch, Tabs, Tag, message } from "antd";
import { ApiOutlined, SaveOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { systemApi } from "../api/client";

/** 控件下方说明文字：小字灰显、最多两行（spec 4 §8.1） */
const hintStyle: React.CSSProperties = {
  color: "#999",
  fontSize: 12,
  lineHeight: 1.5,
  display: "-webkit-box",
  WebkitLineClamp: 2,
  WebkitBoxOrient: "vertical",
  overflow: "hidden",
};

function hint(text: string) {
  return <div style={hintStyle}>{text}</div>;
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
      if (secretKey !== null && secretKey !== "") updates.minio_secret_key = secretKey;
      if (bucket !== null) updates.minio_bucket = bucket;
      if (prefix !== null) updates.minio_object_prefix = prefix;
      if (expires !== null) updates.minio_presign_expires_seconds = expires;
      return systemApi.updateSettings(updates);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["system-settings"] });
      message.success("保存成功");
      resetDirty();
    },
    onError: () => {
      message.error("保存失败");
    },
  });

  const testMutation = useMutation({
    mutationFn: systemApi.testStorage,
    onSuccess: () => {
      message.success("连接正常");
    },
    onError: () => {
      message.error("连接失败");
    },
  });

  const expiresValue = expires ?? settings?.minio_presign_expires_seconds ?? 604800;

  return (
    <Card title="MinIO">
      <Form layout="vertical">
        <Form.Item label="Endpoint">
          <Input
            value={endpoint ?? settings?.minio_endpoint ?? ""}
            onChange={(e) => setEndpoint(e.target.value)}
          />
        </Form.Item>
        <Form.Item label="Access Key">
          <Input
            value={accessKey ?? settings?.minio_access_key ?? ""}
            onChange={(e) => setAccessKey(e.target.value)}
          />
        </Form.Item>
        <Form.Item label="Secret Key">
          <Input.Password
            value={secretKey ?? settings?.minio_secret_key ?? ""}
            onChange={(e) => setSecretKey(e.target.value)}
            placeholder="未配置"
          />
        </Form.Item>
        <Form.Item label="Bucket">
          <Input
            value={bucket ?? settings?.minio_bucket ?? ""}
            onChange={(e) => setBucket(e.target.value)}
          />
        </Form.Item>
        <Form.Item label="对象前缀">
          <Input
            value={prefix ?? settings?.minio_object_prefix ?? ""}
            onChange={(e) => setPrefix(e.target.value)}
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
        <Button
          icon={<ApiOutlined />}
          onClick={() => testMutation.mutate()}
          loading={testMutation.isPending}
        >
          测试连接
        </Button>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          onClick={() => saveMutation.mutate()}
          loading={saveMutation.isPending}
        >
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
      if (dbUrl !== null && dbUrl !== "") updates.database_url = dbUrl;
      return systemApi.updateSettings(updates);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["system-settings"] });
      message.success("保存成功");
      setDbUrl(null);
    },
    onError: () => {
      message.error("保存失败");
    },
  });

  const testMutation = useMutation({
    mutationFn: systemApi.testDb,
    onSuccess: () => {
      message.success("连接正常");
    },
    onError: () => {
      message.error("连接失败");
    },
  });

  return (
    <Card title="数据库">
      <Form layout="vertical">
        <Form.Item label="Database URL">
          <Input
            value={dbUrl ?? settings?.database_url ?? ""}
            onChange={(e) => setDbUrl(e.target.value)}
          />
        </Form.Item>
      </Form>
      <div style={{ display: "flex", gap: 12 }}>
        <Button
          icon={<ApiOutlined />}
          onClick={() => testMutation.mutate()}
          loading={testMutation.isPending}
        >
          测试连接
        </Button>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          onClick={() => saveMutation.mutate()}
          loading={saveMutation.isPending}
        >
          保存配置
        </Button>
      </div>
    </Card>
  );
}

function RunSettingsTab() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["system-settings"], queryFn: systemApi.getSettings });
  const [form] = Form.useForm();

  const saveMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) => systemApi.updateSettings(values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["system-settings"] });
      message.success("保存成功");
    },
    onError: () => {
      message.error("保存失败");
    },
  });

  if (!settings) return null;

  const col = { xs: 24, md: 12 };

  return (
    <Card title="全局运行设置">
      <div style={{ color: "#999", marginBottom: 16 }}>
        作为所有流水线的运行默认值；执行或调度触发时可逐项覆盖
      </div>
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          run_headless: settings.run_headless,
          run_close_browser: settings.run_close_browser,
          run_page_load_timeout: settings.run_page_load_timeout,
          run_element_visible_timeout: settings.run_element_visible_timeout,
          run_action_settle_timeout: settings.run_action_settle_timeout,
          run_default_max_retries: settings.run_default_max_retries,
          run_default_retry_delay_seconds: settings.run_default_retry_delay_seconds,
        }}
        onFinish={(values) => saveMutation.mutate(values)}
      >
        <Row gutter={24}>
          <Col {...col}>
            <Form.Item
              name="run_headless"
              label="无头模式"
              valuePropName="checked"
              extra={hint("浏览器不显示窗口（调试时可关闭）")}
            >
              <Switch />
            </Form.Item>
          </Col>
          <Col {...col}>
            <Form.Item
              name="run_close_browser"
              label="结束后关闭浏览器"
              valuePropName="checked"
              extra={hint("关闭则保留浏览器进程供排查")}
            >
              <Switch />
            </Form.Item>
          </Col>
          <Col {...col}>
            <Form.Item name="run_page_load_timeout" label="页面加载超时">
              <InputNumber min={1000} style={{ width: 200 }} addonAfter="毫秒" />
            </Form.Item>
          </Col>
          <Col {...col}>
            <Form.Item name="run_element_visible_timeout" label="元素可见超时">
              <InputNumber min={500} style={{ width: 200 }} addonAfter="毫秒" />
            </Form.Item>
          </Col>
          <Col {...col}>
            <Form.Item name="run_action_settle_timeout" label="操作稳定等待">
              <InputNumber min={0} style={{ width: 200 }} addonAfter="毫秒" />
            </Form.Item>
          </Col>
          <Col {...col}>
            <Form.Item
              name="run_default_max_retries"
              label="默认最大重试次数"
              extra={hint("新建调度表单的默认值")}
            >
              <InputNumber min={0} style={{ width: 200 }} addonAfter="次" />
            </Form.Item>
          </Col>
          <Col {...col}>
            <Form.Item
              name="run_default_retry_delay_seconds"
              label="默认重试间隔"
              extra={hint("新建调度表单的默认值")}
            >
              <InputNumber min={1} style={{ width: 200 }} addonAfter="秒" />
            </Form.Item>
          </Col>
        </Row>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          htmlType="submit"
          loading={saveMutation.isPending}
        >
          保存配置
        </Button>
      </Form>
    </Card>
  );
}

function ConnectionTab() {
  return (
    <Row gutter={16}>
      <Col xs={24} lg={12}>
        <MinioCard />
      </Col>
      <Col xs={24} lg={12}>
        <DatabaseCard />
      </Col>
    </Row>
  );
}

function OpsTab() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["system-settings"], queryFn: systemApi.getSettings });
  const { data: info } = useQuery({
    queryKey: ["system-info"],
    queryFn: systemApi.info,
    refetchInterval: 10000,
  });
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
      message.success("保存成功");
      setRetention(null);
      setSchedulerEnabled(null);
    },
    onError: () => {
      message.error("保存失败");
    },
  });

  const enabled = schedulerEnabled ?? settings?.scheduler_enabled ?? true;
  const running = info?.scheduler_status === "running";

  return (
    <Card>
      <div style={{ marginBottom: 24 }}>
        <span style={{ marginRight: 8 }}>调度器状态：</span>
        <Tag color={running ? "success" : "warning"}>
          {running ? "运行中" : "已暂停"}
        </Tag>
        {info && <span style={{ color: "#666" }}>{info.active_schedules} 个活跃调度</span>}
      </div>
      <Form layout="vertical">
        <Row gutter={24}>
          <Col xs={24} md={12}>
            <Form.Item label="调度器全局开关" extra={hint("关闭后所有定时调度立即暂停（紧急场景）")}>
              <div>
                <Switch checked={enabled} onChange={(v) => setSchedulerEnabled(v)} />
                <span style={{ marginLeft: 8, color: "#666" }}>{enabled ? "运行中" : "已暂停"}</span>
              </div>
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="日志保留天数" extra={hint("每日凌晨自动清理过期执行记录与日志")}>
              <InputNumber
                value={retention ?? settings?.log_retention_days ?? 30}
                onChange={(v) => setRetention(v)}
                min={1}
                style={{ width: 200 }}
                addonAfter="天"
              />
            </Form.Item>
          </Col>
        </Row>
      </Form>
      <Button
        type="primary"
        icon={<SaveOutlined />}
        onClick={() => saveMutation.mutate()}
        loading={saveMutation.isPending}
      >
        保存配置
      </Button>
    </Card>
  );
}

export function Settings() {
  return (
    <div>
      <h2>系统设置</h2>
      <Alert
        type="info"
        showIcon
        message="所有配置保存后即时生效，无需重启"
        style={{ marginBottom: 16 }}
      />
      <Tabs
        items={[
          { key: "run", label: "运行设置", children: <RunSettingsTab /> },
          { key: "connection", label: "连接配置", children: <ConnectionTab /> },
          { key: "ops", label: "运维策略", children: <OpsTab /> },
        ]}
      />
    </div>
  );
}
