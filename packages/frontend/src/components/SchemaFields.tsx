import { Col, DatePicker, Form, Input, InputNumber, Row, Select, Switch } from "antd";
import dayjs, { Dayjs } from "dayjs";
import { labelWithHint } from "./LabelHint";
import { RangePeriodField } from "./RangePeriodField";

/** config_schema property 声明（spec 4 §4.4：渲染器完全由类型/format/enum 驱动） */
interface SchemaProperty {
  type?: string;
  format?: string;
  enum?: unknown[];
  items?: {
    type?: string;
    enum?: unknown[];
    properties?: Record<string, { description?: string }>;
    required?: string[];
  };
  default?: unknown;
  description?: string;
  /** 展示顺序（小的在前）；DB(MySQL JSON) 会重排 properties key，声明顺序不可靠 */
  "x-order"?: number;
  /** 日期联动：可选范围不得早于/晚于同组另一字段的值（对方清空则不限） */
  "x-min-field"?: string;
  "x-max-field"?: string;
  /** 周期复合控件：同组 start/end 两字段合并渲染为一个范围控件（存储仍为两扁平字段） */
  "x-range-group"?: string;
  "x-range-part"?: "start" | "end";
  /** 复合控件 label（声明在 start 字段上） */
  "x-range-label"?: string;
  /** 允许相对表达式（today / today-N，engine 执行时解析） */
  "x-allow-relative"?: boolean;
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
 * 展示排序（spec 4 §4.4）：字段声明 x-order 时按其升序（未声明的排后）；
 * 否则回退凭据类优先——username 最前、password 其次。注意 DB(MySQL JSON) 会按
 * key 长度+字典序重排 properties，schema 中的声明顺序无法可靠传到前端，
 * 故排序必须在前端做。
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
  const entries = Object.entries(properties).sort(([a, pa], [b, pb]) => {
    const oa = pa["x-order"];
    const ob = pb["x-order"];
    if (oa != null || ob != null) return (oa ?? 999) - (ob ?? 999);
    return fieldRank(a) - fieldRank(b);
  });
  // 监听同组字段值（日期联动 x-min-field/x-max-field 取对方当前值）
  const groupValues = (Form.useWatch(namePrefix) ?? {}) as Record<string, unknown>;
  if (entries.length === 0) return null;

  // 周期复合控件分组：同 x-range-group 的 start/end 配对，start 处渲染合并控件，end 跳过
  const rangePairs = new Map<string, { startKey?: string; endKey?: string; label?: string }>();
  for (const [key, prop] of entries) {
    const g = prop["x-range-group"];
    if (!g) continue;
    const grp = rangePairs.get(g) ?? {};
    if (prop["x-range-part"] === "end") grp.endKey = key;
    else {
      grp.startKey = key;
      grp.label = prop["x-range-label"] ?? prop.description ?? g;
    }
    rangePairs.set(g, grp);
  }
  const consumedEndKeys = new Set<string>();
  const startKeyToGroup = new Map<string, string>();
  for (const [g, { startKey, endKey }] of rangePairs) {
    if (startKey && endKey) {
      consumedEndKeys.add(endKey);
      startKeyToGroup.set(startKey, g);
    }
  }

  const items = entries.map(([key, prop]) => {
    if (consumedEndKeys.has(key)) return { field: null, fullRow: false };
    const rangeGroup = startKeyToGroup.get(key);
    if (rangeGroup) {
      const grp = rangePairs.get(rangeGroup)!;
      return {
        field: (
          <RangePeriodField
            key={key}
            namePrefix={namePrefix}
            startKey={key}
            endKey={grp.endKey!}
            label={grp.label!}
          />
        ),
        fullRow: true,
      };
    }

    const isRequired = required.includes(key);
    const isBoolean = prop.type === "boolean";
    const isDate = prop.format === "date";
    const isJson = isJsonField(prop);
    const minField = prop["x-min-field"];
    const maxField = prop["x-max-field"];
    const minVal = minField ? groupValues[minField] : undefined;
    const maxVal = maxField ? groupValues[maxField] : undefined;
    const label = prop.description || key;
    const rawInitial = prop.default;
    const initialValue =
      isJson && rawInitial != null && typeof rawInitial !== "string"
        ? JSON.stringify(rawInitial, null, 2)
        : rawInitial;

    const rules = [
      ...(isRequired && !isBoolean ? [{ required: true, message: `请输入${label}` }] : []),
      // 日期联动提交校验（disabledDate 之外的双保险，覆盖手工输入/回显场景）
      ...(isDate && minField
        ? [
            {
              validator: (_: unknown, value: unknown) => {
                if (!value || !minVal) return Promise.resolve();
                return dayjs(String(value)).isBefore(dayjs(String(minVal)), "day")
                  ? Promise.reject(new Error(`不能早于${properties[minField]?.description ?? minField}`))
                  : Promise.resolve();
              },
            },
          ]
        : []),
      ...(isDate && maxField
        ? [
            {
              validator: (_: unknown, value: unknown) => {
                if (!value || !maxVal) return Promise.resolve();
                return dayjs(String(value)).isAfter(dayjs(String(maxVal)), "day")
                  ? Promise.reject(new Error(`不能晚于${properties[maxField]?.description ?? maxField}`))
                  : Promise.resolve();
              },
            },
          ]
        : []),
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
      const itemEnum = prop.items?.enum;
      control = itemEnum ? (
        // items.enum 闭集：多选下拉，防自由录入笔误
        <Select
          mode="multiple"
          options={itemEnum.map((v) => ({ value: v as string, label: String(v) }))}
          placeholder="请选择"
          style={{ width: "100%" }}
        />
      ) : (
        // items.type === "string"：tags 录入，原生字符串数组提交
        <Select mode="tags" open={false} suffixIcon={null} placeholder="回车录入" style={{ width: "100%" }} />
      );
    } else if (prop.format === "date") {
      control = (
        <DatePicker
          style={{ width: "100%" }}
          disabledDate={
            minField || maxField
              ? (d) =>
                  (minVal != null && minVal !== "" && d.isBefore(dayjs(String(minVal)), "day")) ||
                  (maxVal != null && maxVal !== "" && d.isAfter(dayjs(String(maxVal)), "day"))
              : undefined
          }
        />
      );
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
        // 日期字段：表单值始终存 "YYYY-MM-DD" 字符串（提交/回显无需调用方转换）
        {...(isDate
          ? {
              getValueProps: (v: unknown) => ({ value: v ? dayjs(String(v)) : null }),
              normalize: (v: Dayjs | null) => (v ? v.format("YYYY-MM-DD") : undefined),
            }
          : {})}
        // 日期联动：对方值变化时重验本字段
        {...(minField || maxField
          ? { dependencies: [minField, maxField].filter(Boolean).map((f) => [...namePrefix, f as string]) }
          : {})}
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
      {items
        .filter((item) => item.field != null)
        .map((item, i) => (
          // JSON 字段内容长，占满整行（spec 4 §4.4）
          <Col xs={24} md={item.fullRow ? 24 : 12} key={i}>
            {item.field}
          </Col>
        ))}
    </Row>
  );
}
