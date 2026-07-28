import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

/**
 * 列表页统一设计语言（spec 4 §2.6，二十二次修订）共享常量与组件。
 */

/** 页面根容器：固定视口可用高度（扣除 Content 与白卡双层 padding），表格滚动而非页面滚动 */
export const LIST_PAGE_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  height: "calc(100vh - 96px)",
};

/** 统一分页配置（服务端/前端分页行为一致） */
export const TABLE_PAGINATION = {
  showSizeChanger: true,
  showQuickJumper: true,
  pageSizeOptions: [10, 20, 50, 100],
  showTotal: (total: number) => `共 ${total} 条`,
};

/**
 * 表格占满剩余高度：测量容器高度，表头(39)+分页(64)之外为表体滚动区。
 * 内容不足时通过 min-height 撑满，使分页始终贴底而非跟随内容高度。
 */
export function useFillTable() {
  const ref = useRef<HTMLDivElement>(null);
  const [y, setY] = useState(300);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setY(Math.max(el.clientHeight - 103, 120));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return {
    ref,
    scrollY: y,
    /** 注入到表格容器内：内容不足时表体仍撑满高度 */
    fillStyle: <style>{`.fill-table .ant-table-body{min-height:${y}px}`}</style>,
  };
}

/**
 * 筛选栏：左侧筛选项组（名称 + 控件），右侧操作按钮组，两端布局。
 */
export function FilterBar({ filters, actions }: { filters: ReactNode; actions: ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        flexWrap: "wrap",
        gap: 12,
        marginBottom: 16,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 16 }}>{filters}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>{actions}</div>
    </div>
  );
}

/** 单个筛选项：左侧名称（灰字），右侧控件 */
export function FilterItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span style={{ color: "#666", whiteSpace: "nowrap" }}>{label}</span>
      {children}
    </span>
  );
}
