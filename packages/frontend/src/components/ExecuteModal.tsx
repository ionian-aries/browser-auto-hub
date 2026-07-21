import { Form, Input, InputNumber, Modal } from "antd";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { executionApi } from "../api/client";
import type { Pipeline } from "../types";

interface Props {
  pipeline: Pipeline | null;
  open: boolean;
  onClose: () => void;
}

export function ExecuteModal({ pipeline, open, onClose }: Props) {
  const [form] = Form.useForm();
  const navigate = useNavigate();

  const mutation = useMutation({
    mutationFn: (config: Record<string, unknown>) =>
      executionApi.create({ pipeline: pipeline!.name, config, trigger_type: "manual" }),
    onSuccess: (exec) => {
      form.resetFields();
      onClose();
      navigate(`/executions/${exec.id}`);
    },
  });

  if (!pipeline?.config_schema) return null;

  const schema = pipeline.config_schema as {
    properties?: Record<string, { type?: string; default?: unknown; description?: string }>;
    required?: string[];
  };
  const properties = schema.properties || {};
  const required = schema.required || [];

  return (
    <Modal
      title={`执行 ${pipeline.display_name}`}
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={mutation.isPending}
    >
      <Form form={form} layout="vertical" onFinish={(values) => mutation.mutate(values)}>
        {Object.entries(properties).map(([key, prop]) => {
          const isRequired = required.includes(key);
          const isPassword = prop.description?.includes("密码");
          const label = prop.description || key;

          return (
            <Form.Item
              key={key}
              name={key}
              label={label}
              initialValue={prop.default}
              rules={isRequired ? [{ required: true, message: `请输入${label}` }] : []}
            >
              {prop.type === "integer" ? (
                <InputNumber style={{ width: "100%" }} />
              ) : isPassword ? (
                <Input.Password />
              ) : (
                <Input />
              )}
            </Form.Item>
          );
        })}
      </Form>
    </Modal>
  );
}
