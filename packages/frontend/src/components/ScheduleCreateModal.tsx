import { Form, Input, InputNumber, Modal, Radio, Select } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { pipelineApi, scheduleApi } from "../api/client";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function ScheduleCreateModal({ open, onClose }: Props) {
  const [form] = Form.useForm();
  const queryClient = useQueryClient();
  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });
  const triggerType = Form.useWatch("trigger_type", form);

  const mutation = useMutation({
    mutationFn: scheduleApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      form.resetFields();
      onClose();
    },
  });

  return (
    <Modal
      title="创建调度"
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={mutation.isPending}
    >
      <Form form={form} layout="vertical" onFinish={(values) => mutation.mutate(values)}>
        <Form.Item name="pipeline_name" label="Pipeline" rules={[{ required: true }]}>
          <Select placeholder="选择 Pipeline">
            {pipelines?.filter((p) => p.trigger_modes.some((m) => ["cron", "interval"].includes(m)))
              .map((p) => <Select.Option key={p.name} value={p.name}>{p.display_name}</Select.Option>)}
          </Select>
        </Form.Item>
        <Form.Item name="name" label="调度名称" rules={[{ required: true }]}>
          <Input placeholder="如：每日 OA 采集" />
        </Form.Item>
        <Form.Item name="trigger_type" label="触发方式" rules={[{ required: true }]}>
          <Radio.Group>
            <Radio value="cron">Cron 表达式</Radio>
            <Radio value="interval">固定间隔</Radio>
          </Radio.Group>
        </Form.Item>
        {triggerType === "cron" && (
          <Form.Item name="cron_expr" label="Cron 表达式" rules={[{ required: true }]}>
            <Input placeholder="0 9 * * * (每天 9 点)" />
          </Form.Item>
        )}
        {triggerType === "interval" && (
          <Form.Item name="interval_seconds" label="间隔（秒）" rules={[{ required: true }]}>
            <InputNumber min={60} placeholder="300" style={{ width: "100%" }} />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}
