import { Col, DatePicker, Form, Input, InputNumber, Modal, Radio, Row, Select, Switch, Tabs, TimePicker, message } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import dayjs, { Dayjs } from "dayjs";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { executionApi, pipelineApi, scheduleApi, systemApi } from "../api/client";
import { isJsonField, SchemaFields } from "./SchemaFields";
import { labelWithHint } from "./LabelHint";
import type { Pipeline, Schedule } from "../types";

type CronPreset = "daily" | "weekday" | "weekly" | "monthly" | "custom";

const WEEKDAY_OPTIONS = [
  { value: 1, label: "周一" },
  { value: 2, label: "周二" },
  { value: 3, label: "周三" },
  { value: 4, label: "周四" },
  { value: 5, label: "周五" },
  { value: 6, label: "周六" },
  { value: 0, label: "周日" },  // cron 标准：0=周日
];

/** 将已有 cron 表达式反解为预设（无法识别则为自定义） */
function parseCron(expr: string | null | undefined): {
  preset: CronPreset;
  time: Dayjs;
  weekday: number;
  monthday: number;
} {
  const fallback = { preset: "custom" as CronPreset, time: dayjs("08:00", "HH:mm"), weekday: 0, monthday: 1 };
  if (!expr) return { ...fallback, preset: "daily" };
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return fallback;
  const [m, h, dom, , dow] = parts;
  if (!/^\d+$/.test(m) || !/^\d+$/.test(h)) return fallback;
  const time = dayjs(`${h.padStart(2, "0")}:${m.padStart(2, "0")}`, "HH:mm");
  if (dom === "*" && dow === "*") return { preset: "daily", time, weekday: 0, monthday: 1 };
  if (dom === "*" && dow === "1-5") return { preset: "weekday", time, weekday: 0, monthday: 1 };
  if (dom === "*" && /^\d$/.test(dow)) return { preset: "weekly", time, weekday: Number(dow), monthday: 1 };
  if (/^\d+$/.test(dom) && dow === "*") return { preset: "monthly", time, weekday: 0, monthday: Number(dom) };
  return fallback;
}

function buildCron(
  preset: CronPreset,
  time: Dayjs | null,
  weekday: number,
  monthday: number,
  custom: string
): string {
  if (preset === "custom") return custom.trim();
  const t = time ?? dayjs("08:00", "HH:mm");
  const mh = `${t.minute()} ${t.hour()}`;
  switch (preset) {
    case "daily":
      return `${mh} * * *`;
    case "weekday":
      return `${mh} * * 1-5`;
    case "weekly":
      return `${mh} * * ${weekday}`;
    case "monthly":
      return `${mh} ${monthday} * *`;
  }
}

type SchemaShape = {
  properties?: Record<string, { type?: string; format?: string; items?: { type?: string }; default?: unknown; description?: string }>;
  required?: string[];
} | null;

/** 提交前：复杂 array/object 字段的 JSON 文本解析回原生类型；空文本的可选字段剔除（spec 4 §4.4）。
 *  array<string> 由 tags Select 原生提交，不在此列。 */
function parseJsonFields(config: Record<string, unknown>, schema: SchemaShape): Record<string, unknown> {
  const out = { ...config };
  for (const [key, prop] of Object.entries(schema?.properties ?? {})) {
    if (!isJsonField(prop)) continue;
    const v = out[key];
    if (v == null || (typeof v === "string" && v.trim() === "")) {
      delete out[key];
    } else if (typeof v === "string") {
      out[key] = JSON.parse(v); // rules 已保证合法 JSON
    }
  }
  return out;
}

/** 编辑回显：复杂 array/object 字段的原生值序列化为 JSON 文本填回 TextArea */
function stringifyJsonFields(config: Record<string, unknown>, schema: SchemaShape): Record<string, unknown> {
  const out = { ...config };
  for (const [key, prop] of Object.entries(schema?.properties ?? {})) {
    if (!isJsonField(prop)) continue;
    const v = out[key];
    if (v != null && typeof v !== "string") {
      out[key] = JSON.stringify(v, null, 2);
    }
  }
  return out;
}

export interface RunModalProps {
  open: boolean;
  onClose: () => void;
  /** 固定流水线（流水线卡片/详情页入口） */
  pipeline?: Pipeline | null;
  /** 初始执行方式 */
  mode?: "now" | "schedule";
  /** 编辑模式：传入已有调度 */
  editSchedule?: Schedule | null;
}

/** 统一执行配置弹窗：立即执行与定时调度共用（spec 4 §4.5） */
export function RunModal({ open, onClose, pipeline: fixedPipeline, mode, editSchedule }: RunModalProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [activeTab, setActiveTab] = useState("params");
  // RunModal 常驻挂载（open 控制显隐），每次打开重置回第一个 Tab（spec 4 §4.5）
  useEffect(() => {
    if (open) setActiveTab("params");
  }, [open]);
  const isEdit = !!editSchedule;

  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });
  const { data: settings } = useQuery({ queryKey: ["system-settings"], queryFn: systemApi.getSettings });

  const pipelineName = Form.useWatch("pipeline_name", form);
  const execMode = Form.useWatch("exec_mode", form);
  const triggerType = Form.useWatch("trigger_type", form);
  const cronPreset = Form.useWatch("cron_preset", form) ?? "daily";
  const cronTime = Form.useWatch("cron_time", form);
  const cronWeekday = Form.useWatch("cron_weekday", form) ?? 0;
  const cronMonthday = Form.useWatch("cron_monthday", form) ?? 1;
  const cronCustom = Form.useWatch("cron_expr_custom", form) ?? "";

  // edit 模式/schema 查找按名称匹配（Select 选项本身只列启用项）
  const pipeline =
    fixedPipeline ??
    pipelines?.find((p) => p.name === pipelineName) ??
    null;
  const schema = pipeline?.config_schema as SchemaShape;

  const runMutation = useMutation({
    mutationFn: (values: Record<string, unknown>): Promise<{ kind: "execution" | "schedule"; id: string }> => {
      const config = parseJsonFields((values.config as Record<string, unknown>) ?? {}, schema);
      if (values.exec_mode === "now") {
        return executionApi
          .create({ pipeline: values.pipeline_name as string, config, trigger_type: "manual" })
          .then((exec) => ({ kind: "execution" as const, id: exec.id }));
      }
      const out: Record<string, unknown> = {
        name: values.name,
        trigger_type: values.trigger_type,
        max_retries: values.max_retries,
        retry_delay_seconds: values.retry_delay_seconds,
        config_override: Object.keys(config).length > 0 ? config : null,
        cron_expr: null,
        interval_seconds: null,
        run_at: null,
      };
      if (values.trigger_type === "cron") {
        out.cron_expr = buildCron(
          values.cron_preset as CronPreset,
          values.cron_time as Dayjs | null,
          (values.cron_weekday as number) ?? 0,
          (values.cron_monthday as number) ?? 1,
          (values.cron_expr_custom as string) ?? ""
        );
      } else if (values.trigger_type === "interval") {
        out.interval_seconds = values.interval_seconds;
      } else if (values.trigger_type === "once") {
        out.run_at = values.run_at ? (values.run_at as Dayjs).toISOString() : null;
      }
      if (isEdit) {
        return scheduleApi
          .update(editSchedule!.id, out as Partial<Schedule>)
          .then(() => ({ kind: "schedule" as const, id: editSchedule!.id }));
      }
      return scheduleApi
        .create({
          ...out,
          pipeline_id: pipeline!.id,
        } as Parameters<typeof scheduleApi.create>[0])
        .then((s) => ({ kind: "schedule" as const, id: s.id }));
    },
    onSuccess: (result) => {
      form.resetFields();
      onClose();
      if (result.kind === "execution") {
        navigate(`/executions/${result.id}`);
      } else {
        queryClient.invalidateQueries({ queryKey: ["schedules"] });
        message.success("保存成功");
      }
    },
    onError: () => {
      message.error("保存失败");
    },
  });

  if (!pipelines || !settings) return null;

  // 运行设置 5 项默认取全局运行设置（spec 4 §4.5 Tab 3）；编辑模式下已保存的
  // config_override 覆盖在后（spread 顺序：全局打底 → 已存覆盖）
  const runSettingDefaults = {
    headless: settings.run_headless,
    close_browser: settings.run_close_browser,
    page_load_timeout: settings.run_page_load_timeout,
    element_visible_timeout: settings.run_element_visible_timeout,
    action_settle_timeout: settings.run_action_settle_timeout,
  };

  let initialValues: Record<string, unknown>;
  if (isEdit && editSchedule) {
    const editCron = parseCron(editSchedule.cron_expr);
    const editSchema = (pipelines.find((p) => p.name === editSchedule.pipeline_name)?.config_schema ?? null) as SchemaShape;
    initialValues = {
      pipeline_name: editSchedule.pipeline_name,
      exec_mode: "schedule",
      config: {
        ...runSettingDefaults,
        // array/object 字段需序列化为 JSON 文本回显（spec 4 §4.4）
        ...stringifyJsonFields(editSchedule.config_override ?? {}, editSchema),
      },
      name: editSchedule.name,
      trigger_type: editSchedule.trigger_type,
      cron_preset: editCron.preset,
      cron_time: editCron.time,
      cron_weekday: editCron.weekday,
      cron_monthday: editCron.monthday,
      cron_expr_custom: editCron.preset === "custom" ? editSchedule.cron_expr : "",
      interval_seconds: editSchedule.interval_seconds,
      run_at: editSchedule.run_at ? dayjs(editSchedule.run_at) : null,
      max_retries: editSchedule.max_retries,
      retry_delay_seconds: editSchedule.retry_delay_seconds,
    };
  } else {
    initialValues = {
      pipeline_name: fixedPipeline?.name,
      exec_mode: mode === "schedule" ? "schedule" : "now",
      config: { ...runSettingDefaults },
      trigger_type: "cron",
      cron_preset: "daily",
      cron_time: dayjs("08:00", "HH:mm"),
      cron_weekday: 1,
      cron_monthday: 1,
      max_retries: settings.run_default_max_retries,
      retry_delay_seconds: settings.run_default_retry_delay_seconds,
    };
  }

  // 提交校验失败：切换到第一个错误字段所在 Tab（隐藏面板的错误不可见）
  const onFinishFailed = ({ errorFields }: { errorFields: { name: (string | number)[] }[] }) => {
    const first = errorFields[0]?.name ?? [];
    const last = String(first[first.length - 1] ?? "");
    if (first[0] === "config") {
      const RUNTIME_KEYS = [
        "headless",
        "close_browser",
        "page_load_timeout",
        "element_visible_timeout",
        "action_settle_timeout",
      ];
      setActiveTab(RUNTIME_KEYS.includes(last) ? "runtime" : "params");
    } else if (first[0] !== "pipeline_name") {
      setActiveTab("exec");
    }
  };

  const col2 = { xs: 24, md: 12 };
  const col3 = { xs: 24, md: 8 };

  return (
    <Modal
      title={isEdit ? "编辑调度" : "执行配置"}
      open={open}
      width={880}
      onCancel={() => {
        form.resetFields();
        onClose();
      }}
      onOk={() => form.submit()}
      okText={execMode === "schedule" ? "保存调度" : "立即执行"}
      cancelText="取消"
      confirmLoading={runMutation.isPending}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={initialValues}
        onFinish={(v) => runMutation.mutate(v)}
        onFinishFailed={onFinishFailed}
        preserve={false}
      >
        {!fixedPipeline && !isEdit && (
          <Form.Item name="pipeline_name" label="流水线" rules={[{ required: true, message: "请选择流水线" }]}>
            <Select
              placeholder="选择流水线"
              options={pipelines
                .filter((p) => p.status === "active")
                .map((p) => ({ value: p.name, label: p.display_name }))}
            />
          </Form.Item>
        )}
        {/* 固定流水线/edit 模式也需要 pipeline_name 参与提交 */}
        {(fixedPipeline || isEdit) && <Form.Item name="pipeline_name" hidden><Input /></Form.Item>}

        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: "params",
              label: "流水线参数",
              forceRender: true,
              children: schema ? (
                <SchemaFields schema={schema} namePrefix={["config"]} twoColumn seedDefaults={!isEdit} />
              ) : (
                <div style={{ color: "#999" }}>当前流水线无可配置参数</div>
              ),
            },
            {
              key: "exec",
              label: "执行方式",
              forceRender: true,
              children: (
                <>
                  <Form.Item name="exec_mode" style={{ marginBottom: 16 }}>
                    <Radio.Group
                      disabled={isEdit}
                      optionType="button"
                      buttonStyle="solid"
                      options={[
                        { value: "now", label: "立即执行" },
                        { value: "schedule", label: "定时调度" },
                      ]}
                    />
                  </Form.Item>

                  {execMode === "schedule" && (
                    <>
                      <Row gutter={24}>
                        <Col {...col2}>
                          <Form.Item name="name" label="调度名称" rules={[{ required: true, message: "请输入调度名称" }]}>
                            <Input placeholder="如：工作日早8点采集" />
                          </Form.Item>
                        </Col>
                        <Col {...col2}>
                          <Form.Item name="trigger_type" label="触发方式" rules={[{ required: true }]}>
                            <Radio.Group>
                              <Radio value="cron">Cron 定时</Radio>
                              <Radio value="interval">固定间隔</Radio>
                              <Radio value="once">单次定时</Radio>
                            </Radio.Group>
                          </Form.Item>
                        </Col>
                      </Row>
                      {triggerType === "cron" && (
                        <>
                          <Form.Item name="cron_preset" label="频率">
                            <Radio.Group
                              options={[
                                { value: "daily", label: "每天" },
                                { value: "weekday", label: "工作日" },
                                { value: "weekly", label: "每周" },
                                { value: "monthly", label: "每月" },
                                { value: "custom", label: "自定义" },
                              ]}
                              optionType="button"
                              buttonStyle="solid"
                            />
                          </Form.Item>
                          <Row gutter={24}>
                            {cronPreset === "weekly" && (
                              <Col {...col3}>
                                <Form.Item name="cron_weekday" label="星期">
                                  <Select options={WEEKDAY_OPTIONS} style={{ width: "100%" }} />
                                </Form.Item>
                              </Col>
                            )}
                            {cronPreset === "monthly" && (
                              <Col {...col3}>
                                <Form.Item name="cron_monthday" label="日期">
                                  <InputNumber min={1} max={31} addonAfter="日" style={{ width: "100%" }} />
                                </Form.Item>
                              </Col>
                            )}
                            {cronPreset !== "custom" ? (
                              <Col {...col3}>
                                <Form.Item
                                  name="cron_time"
                                  label={labelWithHint("时间", `对应表达式：${buildCron(cronPreset, cronTime, cronWeekday, cronMonthday, cronCustom)}`)}
                                >
                                  <TimePicker format="HH:mm" minuteStep={5} style={{ width: "100%" }} />
                                </Form.Item>
                              </Col>
                            ) : (
                              <Col span={24}>
                                <Form.Item
                                  name="cron_expr_custom"
                                  label={labelWithHint("Cron 表达式", "5 段格式：分 时 日 月 星期，如 0 8 * * 1-5")}
                                  rules={[{ required: true, message: "请输入 cron 表达式" }]}
                                >
                                  <Input placeholder="0 8 * * 1-5" />
                                </Form.Item>
                              </Col>
                            )}
                          </Row>
                        </>
                      )}
                      {triggerType === "interval" && (
                        <Form.Item name="interval_seconds" label="间隔（秒）" rules={[{ required: true, message: "请输入间隔秒数" }]}>
                          <InputNumber min={60} style={{ width: 200 }} />
                        </Form.Item>
                      )}
                      {triggerType === "once" && (
                        <Form.Item name="run_at" label="执行时刻" rules={[{ required: true, message: "请选择执行时刻" }]}>
                          <DatePicker
                            showTime={{ format: "HH:mm" }}
                            format="YYYY-MM-DD HH:mm"
                            disabledDate={(d) => d && d.isBefore(dayjs().startOf("day"))}
                          />
                        </Form.Item>
                      )}
                      <Row gutter={24}>
                        <Col {...col2}>
                          <Form.Item name="max_retries" label="最大重试次数">
                            <InputNumber min={0} style={{ width: "100%" }} />
                          </Form.Item>
                        </Col>
                        <Col {...col2}>
                          <Form.Item name="retry_delay_seconds" label="重试间隔（秒）">
                            <InputNumber min={1} style={{ width: "100%" }} />
                          </Form.Item>
                        </Col>
                      </Row>
                    </>
                  )}
                </>
              ),
            },
            {
              key: "runtime",
              label: "运行配置",
              forceRender: true,
              children: (
                <Row gutter={24}>
                  <Col {...col2}>
                    <Form.Item
                      name={["config", "headless"]}
                      label={labelWithHint("无头模式", "浏览器不显示窗口（调试时可关闭）")}
                      valuePropName="checked"
                    >
                      <Switch />
                    </Form.Item>
                  </Col>
                  <Col {...col2}>
                    <Form.Item
                      name={["config", "close_browser"]}
                      label={labelWithHint("结束后关闭浏览器", "关闭则保留浏览器进程供排查")}
                      valuePropName="checked"
                    >
                      <Switch />
                    </Form.Item>
                  </Col>
                  <Col {...col2}>
                    <Form.Item
                      name={["config", "page_load_timeout"]}
                      label={labelWithHint("页面加载超时", "页面跳转后等待加载完成的时长")}
                      rules={[{ required: true, message: "请输入页面加载超时" }]}
                    >
                      <InputNumber min={0} step={1000} addonAfter="毫秒" style={{ width: "100%" }} />
                    </Form.Item>
                  </Col>
                  <Col {...col2}>
                    <Form.Item
                      name={["config", "element_visible_timeout"]}
                      label={labelWithHint("元素可见超时", "等待页面元素出现的时长")}
                      rules={[{ required: true, message: "请输入元素可见超时" }]}
                    >
                      <InputNumber min={0} step={1000} addonAfter="毫秒" style={{ width: "100%" }} />
                    </Form.Item>
                  </Col>
                  <Col {...col2}>
                    <Form.Item
                      name={["config", "action_settle_timeout"]}
                      label={labelWithHint("操作后稳定等待", "每次点击/输入等操作后的固定等待")}
                      rules={[{ required: true, message: "请输入操作后稳定等待" }]}
                    >
                      <InputNumber min={0} step={100} addonAfter="毫秒" style={{ width: "100%" }} />
                    </Form.Item>
                  </Col>
                </Row>
              ),
            },
          ]}
        />
      </Form>
    </Modal>
  );
}
