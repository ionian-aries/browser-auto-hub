import { DatePicker, Form, Input, InputNumber, Radio, Select } from "antd";
import dayjs, { Dayjs } from "dayjs";
import { useState } from "react";

/**
 * 周期复合控件（schema 标记 x-range-group 驱动）：UI 合并为一个范围选择，
 * 存储仍写两个扁平字段（start/end key）。
 *
 * 两种模式：
 * - 固定日期：RangePicker + 快捷预设，值为具体 YYYY-MM-DD；
 * - 相对周期：预设 Select，值为 today / today-N 表达式（engine 每次执行时解析，
 *   定时任务窗口随执行日滚动）。
 */
const REL_RE = /^today(?:-(\d+))?$/;

const REL_PRESETS = [
  { label: "今天", value: "today~today" },
  { label: "昨天", value: "today-1~today-1" },
  { label: "近7天", value: "today-6~today" },
  { label: "近14天", value: "today-13~today" },
  { label: "近30天", value: "today-29~today" },
  { label: "近90天", value: "today-89~today" },
];

const FIXED_PRESETS: { label: string; value: [Dayjs, Dayjs] }[] = [
  { label: "今天", value: [dayjs(), dayjs()] },
  { label: "昨天", value: [dayjs().subtract(1, "day"), dayjs().subtract(1, "day")] },
  { label: "近7天", value: [dayjs().subtract(6, "day"), dayjs()] },
  { label: "近30天", value: [dayjs().subtract(29, "day"), dayjs()] },
];

/** today / today-N → Dayjs（模式互转时把表达式落到具体日期，让 RangePicker 有值可显） */
function exprToDayjs(v: string): Dayjs | null {
  const m = REL_RE.exec(v.trim());
  if (!m) return null;
  return dayjs().subtract(Number(m[1] ?? 0), "day");
}

/** 相对模式 Select 的"自定义（近N天）"哨兵值 */
const CUSTOM = "__custom__";
/** 近N天形态：start=today-(N-1), end=today（N=含执行日在内的天数，N≥1） */
const NDAYS_RE = /^today-(\d+)~today$/;

/** N → 规范表达式（N=1 落为 today~today，与预设口径一致） */
function nToPair(n: number): [string, string] {
  return [n - 1 === 0 ? "today" : `today-${n - 1}`, "today"];
}

interface Props {
  /** 嵌套路径前缀，与 SchemaFields namePrefix 一致 */
  namePrefix: (string | number)[];
  startKey: string;
  endKey: string;
  label: string;
}

export function RangePeriodField({ namePrefix, startKey, endKey, label }: Props) {
  const form = Form.useFormInstance();
  const startPath = [...namePrefix, startKey];
  const endPath = [...namePrefix, endKey];
  const start = Form.useWatch(startPath, form) as string | undefined;
  const end = Form.useWatch(endPath, form) as string | undefined;

  const isRelative = REL_RE.test(String(start ?? "")) || REL_RE.test(String(end ?? ""));
  const mode = isRelative ? "relative" : "fixed";

  const setBoth = (s?: string, e?: string) => {
    form.setFieldValue(startPath, s);
    form.setFieldValue(endPath, e);
    // setFieldValue 不触发校验，手动重验使错误即时出现/消失
    form.validateFields([startPath]).catch(() => {});
  };

  const rangeValue: [Dayjs | null, Dayjs | null] | null = (() => {
    if (!start && !end) return null;
    const toD = (v?: string) => {
      if (!v) return null;
      if (REL_RE.test(v)) return exprToDayjs(v);
      const d = dayjs(v);
      return d.isValid() ? d : null;
    };
    return [toD(start), toD(end)];
  })();

  // 相对模式 Select 状态：预设 / 自定义近N天 / 奇异表达式（API 直传，只读回显）
  const relPair = `${start}~${end}`;
  const relMatched = REL_PRESETS.some((p) => p.value === relPair);
  const nDaysMatch = NDAYS_RE.exec(relPair);
  const [customChosen, setCustomChosen] = useState(false);
  // 自定义激活：用户显式选"自定义…"，或当前值是非预设的 today-X~today 形态
  const customActive = customChosen || (!!nDaysMatch && !relMatched);
  const customN = nDaysMatch ? Number(nDaysMatch[1]) + 1 : 7;
  // 奇异表达式（如 today-60~today-31，无法归入近N天模型）：只读选项回显，保住原值
  const exoticPair = !relMatched && !customActive && start && end ? relPair : null;
  const relOptions = [
    ...REL_PRESETS,
    { label: "自定义（近N天）…", value: CUSTOM },
    ...(exoticPair ? [{ label: `自定义（${start} ~ ${end}）`, value: relPair }] : []),
  ];
  const selectValue = customActive ? CUSTOM : relPair;

  return (
    <>
      {/* 值承载 + 校验挂在隐藏 start 字段上；错误经 shouldUpdate 透传到可见 label 行。
          注意：带 dependencies 的无 name Form.Item 要求 render-props 子节点，
          普通多子节点会被整体吞掉（label 渲染、控件为空）——故外层用 shouldUpdate 模式 */}
      <Form.Item name={startPath} hidden rules={[{
        validator: (_: unknown, v: unknown) =>
          v && form.getFieldValue(endPath)
            ? Promise.resolve()
            : Promise.reject(new Error(`请选择${label}`)),
      }]}>
        <Input />
      </Form.Item>
      <Form.Item name={endPath} hidden>
        <Input />
      </Form.Item>
      <Form.Item noStyle shouldUpdate>
        {() => {
          const errs = form.getFieldError(startPath);
          return (
            <Form.Item
              label={label}
              required
              validateStatus={errs.length ? "error" : undefined}
              help={errs[0]}
            >
              <Radio.Group
                value={mode}
                onChange={(e) => {
                  // 模式互转重置自定义选中态，避免预设值却显示为自定义输入的歧义
                  setCustomChosen(false);
                  if (e.target.value === "relative") {
                    setBoth("today-6", "today");
                  } else {
                    // 表达式 → 具体日期；空则保持空
                    const s = start ? (exprToDayjs(start) ?? dayjs(start)) : undefined;
                    const en = end ? (exprToDayjs(end) ?? dayjs(end)) : undefined;
                    setBoth(s?.isValid() ? s.format("YYYY-MM-DD") : undefined, en?.isValid() ? en.format("YYYY-MM-DD") : undefined);
                  }
                }}
                optionType="button"
                buttonStyle="solid"
                size="small"
                style={{ marginBottom: 8 }}
                options={[
                  { label: "固定日期", value: "fixed" },
                  { label: "相对周期（随执行日滚动）", value: "relative" },
                ]}
              />
              {mode === "fixed" ? (
                <DatePicker.RangePicker
                  style={{ width: "100%" }}
                  presets={FIXED_PRESETS}
                  value={rangeValue}
                  onChange={(v) =>
                    setBoth(
                      v?.[0] ? v[0].format("YYYY-MM-DD") : undefined,
                      v?.[1] ? v[1].format("YYYY-MM-DD") : undefined,
                    )
                  }
                />
              ) : (
                <>
                  <Select
                    style={{ width: "100%" }}
                    options={relOptions}
                    value={selectValue}
                    onChange={(v) => {
                      if (v === CUSTOM) {
                        setCustomChosen(true);
                        // 初始 N：当前已是近N天形态则沿用，否则默认近7天
                        setBoth(...nToPair(customN));
                        return;
                      }
                      setCustomChosen(false);
                      const [s, e] = String(v).split("~");
                      setBoth(s, e);
                    }}
                  />
                  {customActive && (
                    <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8 }}>
                      <span>近</span>
                      <InputNumber
                        min={1}
                        precision={0}
                        style={{ width: 90 }}
                        value={customN}
                        onChange={(v) => {
                          if (typeof v === "number" && v >= 1) setBoth(...nToPair(v));
                        }}
                      />
                      <span style={{ color: "rgba(0,0,0,0.45)" }}>天（含执行日当天，随执行日滚动）</span>
                    </div>
                  )}
                </>
              )}
            </Form.Item>
          );
        }}
      </Form.Item>
    </>
  );
}
