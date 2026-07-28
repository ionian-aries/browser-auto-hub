import { Col, Form, Input, InputNumber, Row, Select, Switch } from "antd";
import { labelWithHint } from "./LabelHint";

/** config_schema property 声明（spec 4 §4.4：渲染器完全由类型/format/enum 驱动） */
interface SchemaProperty {
  type?: string;
  format?: string;
  enum?: unknown[];
  items?: {
    type?: string;
    properties?: Record<string, { description?: string }>;
    required?: string[];
  };
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
  /** 双栏网格排布（spec 4 §8.1） */
  twoColumn?: boolean;
  /**
   * 是否用 schema default seed 字段初始值。
   * 编辑场景传 false：Form 层 initialValues 已带保存的配置，
   * Form.Item 级 initialValue 会覆盖并丢弃它们。
   */
  seedDefaults?: boolean;
}

/** array<object>/object 等需 JSON 文本承载的复杂类型（提交前由调用方解析） */
export function isJsonField(prop: SchemaProperty): boolean {
  if (prop.type === "object") return true;
  return prop.type === "array" && prop.items?.type !== "string";
}

/**
 * 展示排序（spec 4 §4.4）：凭据类字段优先——username 最前、password 其次，其余保持
 * schema 声明顺序。注意 DB(MySQL JSON) 会按 key 长度+字典序重排 properties，
 * schema 中的声明顺序无法可靠传到前端，故排序必须在前端做。
 */
function fieldRank(key: string): number {
  const k = key.toLowerCase();
  if (k.includes("username")) return 0;
  if (k.includes("password")) return 1;
  return 2;
}

/** 按 pipeline config_schema 动态渲染运行参数字段（执行配置页共用） */
export function SchemaFields({ schema, namePrefix = [], twoColumn, seedDefaults = true }: Props) {
  const properties = schema?.properties || {};
  const required = schema?.required || [];
  const entries = Object.entries(properties).sort(
    ([a], [b]) => fieldRank(a) - fieldRank(b)
  );
  if (entries.length === 0) return null;

  const items = entries.map(([key, prop]) => {
    const isRequired = required.includes(key);
    const isBoolean = prop.type === "boolean";
    const isJson = isJsonField(prop);
    const label = prop.description || key;
    const rawInitial = prop.default;
    const initialValue =
      isJson && rawInitial != null && typeof rawInitial !== "string"
        ? JSON.stringify(rawInitial, null, 2)
        : rawInitial;

    const rules = [
      ...(isRequired && !isBoolean ? [{ required: true, message: `请输入${label}` }] : []),
      ...(isJson
        ? [
            {
              validator: (_: unknown, value: unknown) => {
                if (value == null || String(value).trim() === "") return Promise.resolve();
                try {
                  JSON.parse(String(value));
                  return Promise.resolve();
                } catch {
                  return Promise.reject(new Error("JSON 格式不合法"));
                }
              },
            },
          ]
        : []),
    ];

    // 控件选择：仅看类型/format/enum/items，不看字段名（spec 4 §4.4）
    let control: React.ReactNode;
    if (prop.enum) {
      control = (
        <Select
          options={prop.enum.map((v) => ({ value: v as string, label: String(v) }))}
          style={{ width: "100%" }}
        />
      );
    } else if (prop.type === "integer" || prop.type === "number") {
      control = <InputNumber style={{ width: "100%" }} />;
    } else if (isBoolean) {
      control = <Switch />;
    } else if (isJson) {
      control = (
        <Input.TextArea
          autoSize={{ minRows: 4, maxRows: 14 }}
          style={{ fontFamily: "monospace", fontSize: 12 }}
          placeholder={prop.type === "array" ? '[{"key": "value"}]' : '{"key": "value"}'}
        />
      );
    } else if (prop.type === "array") {
      // items.type === "string"：tags 录入，原生字符串数组提交
      control = <Select mode="tags" open={false} suffixIcon={null} placeholder="回车录入" style={{ width: "100%" }} />;
    } else if (prop.format === "password") {
      control = <Input.Password />;
    } else if (prop.format === "textarea") {
      control = <Input.TextArea autoSize={{ minRows: 3, maxRows: 8 }} />;
    } else {
      control = <Input />;
    }

    // JSON 编辑器说明：从 items.properties 生成逐字段文档，置于 label 后缀 tooltip（spec 4 §4.4/§8.1）
    const itemProps = prop.items?.properties;
    const itemRequired = prop.items?.required ?? [];
    const jsonHint = isJson ? (
      <div>
        <div>JSON 格式{prop.type === "array" ? "数组" : "对象"}，default 为结构示例</div>
        {itemProps &&
          Object.entries(itemProps).map(([k, p]) => (
            <div key={k}>
              {k}：{p.description ?? ""}
              {itemRequired.includes(k) ? "（必填）" : ""}
            </div>
          ))}
      </div>
    ) : undefined;

    const field = (
      <Form.Item
        key={key}
        name={[...namePrefix, key]}
        label={jsonHint ? labelWithHint(label, jsonHint) : label}
        {...(seedDefaults ? { initialValue } : {})}
        {...(isBoolean ? { valuePropName: "checked" } : {})}
        rules={rules}
      >
        {control}
      </Form.Item>
    );

    return { field, fullRow: isJson };
  });

  if (!twoColumn) return <>{items.map((i) => i.field)}</>;

  return (
    <Row gutter={24}>
      {items.map((item, i) => (
        // JSON 字段内容长，占满整行（spec 4 §4.4）
        <Col xs={24} md={item.fullRow ? 24 : 12} key={i}>
          {item.field}
        </Col>
      ))}
    </Row>
  );
}
