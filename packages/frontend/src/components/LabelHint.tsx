import { Tooltip } from "antd";
import { QuestionCircleOutlined } from "@ant-design/icons";
import type { ReactNode } from "react";

/**
 * label 后缀说明 icon（spec 4 §8.1 二十二次修订全局规则）：
 * 表单项补充说明一律 icon + Tooltip，不再置于控件下方。
 */
export function LabelHint({ text }: { text: ReactNode }) {
  return (
    <Tooltip title={text}>
      <QuestionCircleOutlined style={{ color: "#999", marginLeft: 4, fontSize: 12 }} />
    </Tooltip>
  );
}

/** 便捷拼装：label 节点 + 说明 tooltip */
export function labelWithHint(label: ReactNode, hint: ReactNode) {
  return (
    <span>
      {label}
      <LabelHint text={hint} />
    </span>
  );
}
