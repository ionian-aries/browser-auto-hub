import { Col, Form, Input, InputNumber, Row } from "antd";

interface SchemaProperty {
  type?: string;
  default?: unknown;
  description?: string;
}

interface Props {
  schema: {
    properties?: Record<string, SchemaProperty>;
    required?: string[];
  } | null;
  /** 字段名前缀（嵌套路径），如 ["config_override"] 使值收集到 values.config_override 下 */
  namePrefix?: (string | number)[];
  /** 默认值覆盖（三级覆盖链：全局运行设置优先于 schema default） */
  defaults?: Record<string, unknown>;
  /** 双栏网格排布（spec 4 §8.1） */
  twoColumn?: boolean;
}

/** 按 pipeline config_schema 动态渲染运行参数字段（执行配置页共用） */
export function SchemaFields({ schema, namePrefix = [], defaults, twoColumn }: Props) {
  const properties = schema?.properties || {};
  const required = schema?.required || [];
  const entries = Object.entries(properties);
  if (entries.length === 0) return null;

  const items = entries.map(([key, prop]) => {
    const isRequired = required.includes(key);
    const isPassword = prop.description?.includes("密码");
    const label = prop.description || key;
    const initialValue = defaults && key in defaults ? defaults[key] : prop.default;

    return (
      <Form.Item
        key={key}
        name={[...namePrefix, key]}
        label={label}
        initialValue={initialValue}
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
  });

  if (!twoColumn) return <>{items}</>;

  return (
    <Row gutter={24}>
      {items.map((item, i) => (
        <Col xs={24} md={12} key={i}>
          {item}
        </Col>
      ))}
    </Row>
  );
}
