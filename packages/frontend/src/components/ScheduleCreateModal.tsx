import { Form, Input, InputNumber, Modal, Radio, message } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { scheduleApi } from "../api/client";
import type { Schedule } from "../types";

interface Props {
  pipelineId: string;
  open: boolean;
  onClose: () => void;
  editSchedule?: Schedule | null;
}

export function ScheduleCreateModal({ pipelineId, open, onClose, editSchedule }: Props) {
  const [form] = Form.useForm();
  const queryClient = useQueryClient();
  const triggerType = Form.useWatch("trigger_type", form);

  const createMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      editSchedule
        ? scheduleApi.update(editSchedule.id, values as Partial<Schedule>)
        : scheduleApi.create({ ...values, pipeline_id: pipelineId } as Parameters<typeof scheduleApi.create>[0]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      form.resetFields();
      onClose();
    },
  });

  return (
    <Modal
      title={editSchedule ? "编辑调度" : "新建调度"}
      open={open}
      onCancel={() => { form.resetFields(); onClose(); }}
      onOk={() => form.submit()}
      confirmLoading={createMutation.isPending}
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={editSchedule || { trigger_type: "cron", max_retries: 0, retry_delay_seconds: 60 }}
        onFinish={(values) => {
          if (values.config_override && typeof values.config_override === "string") {
            const raw = values.config_override.trim();
            if (raw === "") {
              values.config_override = null;
            } else {
              try {
                values.config_override = JSON.parse(raw);
              } catch {
                message.error("配置覆盖必须是合法的 JSON");
                return;
              }
            }
          } else if (!values.config_override) {
            values.config_override = null;
          }
          createMutation.mutate(values);
        }}
      >
        <Form.Item name="name" label="调度名称" rules={[{ required: true }]}>
          <Input placeholder="如：工作日早8点采集" />
        </Form.Item>
        <Form.Item name="trigger_type" label="触发方式" rules={[{ required: true }]}>
          <Radio.Group>
            <Radio value="cron">Cron 表达式</Radio>
            <Radio value="interval">固定间隔</Radio>
            <Radio value="once">单次</Radio>
          </Radio.Group>
        </Form.Item>
        {triggerType === "cron" && (
          <Form.Item name="cron_expr" label="Cron 表达式" rules={[{ required: true }]}>
            <Input placeholder="0 8 * * 1-5" />
          </Form.Item>
        )}
        {triggerType === "interval" && (
          <Form.Item name="interval_seconds" label="间隔（秒）" rules={[{ required: true }]}>
            <InputNumber min={60} style={{ width: "100%" }} />
          </Form.Item>
        )}
        <Form.Item name="max_retries" label="最大重试次数">
          <InputNumber min={0} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="retry_delay_seconds" label="重试间隔（秒）">
          <InputNumber min={1} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="config_override" label="配置覆盖（JSON，可选）">
          <Input.TextArea rows={4} placeholder='{"key": "value"}' />
        </Form.Item>
      </Form>
    </Modal>
  );
}
