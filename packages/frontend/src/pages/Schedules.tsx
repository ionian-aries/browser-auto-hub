import { useState } from "react";
import { Button, Popconfirm, Select, Space, Switch, Table, message } from "antd";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { pipelineApi, scheduleApi } from "../api/client";
import { FilterBar, FilterItem, LIST_PAGE_STYLE, TABLE_PAGINATION, useFillTable } from "../components/ListPage";
import { RunModal } from "../components/RunModal";
import { scheduleTypeLabels } from "../labels";
import type { Schedule } from "../types";

export function Schedules() {
  const queryClient = useQueryClient();
  const [runOpen, setRunOpen] = useState(false);
  const [editSchedule, setEditSchedule] = useState<Schedule | null>(null);
  const fill = useFillTable();

  // 筛选草稿（点「筛选」才应用，spec 4 §2.6）
  const [nameDraft, setNameDraft] = useState<string | undefined>();
  const [pipelineDraft, setPipelineDraft] = useState<string | undefined>();
  const [typesDraft, setTypesDraft] = useState<string[] | undefined>();
  const [enabledDraft, setEnabledDraft] = useState<boolean | undefined>();
  const [applied, setApplied] = useState<{ name?: string; pipeline?: string; types?: string[]; enabled?: boolean }>({});

  const { data: schedules } = useQuery({
    queryKey: ["schedules"],
    queryFn: () => scheduleApi.list(),
  });
  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });

  const enabledMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => scheduleApi.setEnabled(id, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => scheduleApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      message.success("删除成功");
    },
    onError: () => {
      message.error("删除失败");
    },
  });

  const filtered = schedules?.filter((s) => {
    if (applied.name && s.name !== applied.name) return false;
    if (applied.pipeline && s.pipeline_name !== applied.pipeline) return false;
    if (applied.types?.length && !applied.types.includes(s.trigger_type)) return false;
    if (applied.enabled !== undefined && s.enabled !== applied.enabled) return false;
    return true;
  });

  const applyFilter = () =>
    setApplied({ name: nameDraft, pipeline: pipelineDraft, types: typesDraft, enabled: enabledDraft });

  return (
    <div style={LIST_PAGE_STYLE}>
      <h2>调度管理</h2>

      <FilterBar
        filters={
          <>
            <FilterItem label="名称">
              <Select
                placeholder="全部"
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ width: 180 }}
                value={nameDraft}
                onChange={setNameDraft}
                options={[...new Set(schedules?.map((s) => s.name))].map((n) => ({ value: n, label: n }))}
              />
            </FilterItem>
            <FilterItem label="流水线">
              <Select
                placeholder="全部"
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ width: 160 }}
                value={pipelineDraft}
                onChange={setPipelineDraft}
                options={pipelines?.map((p) => ({ value: p.name, label: p.display_name }))}
              />
            </FilterItem>
            <FilterItem label="类型">
              <Select
                placeholder="全部"
                allowClear
                mode="multiple"
                maxTagCount="responsive"
                style={{ width: 160 }}
                value={typesDraft}
                onChange={(v) => setTypesDraft(v.length ? v : undefined)}
                options={Object.entries(scheduleTypeLabels).map(([value, label]) => ({ value, label }))}
              />
            </FilterItem>
            <FilterItem label="启用状态">
              <Select
                placeholder="全部"
                allowClear
                style={{ width: 100 }}
                value={enabledDraft}
                onChange={setEnabledDraft}
                options={[
                  { value: true, label: "启用" },
                  { value: false, label: "停用" },
                ]}
              />
            </FilterItem>
          </>
        }
        actions={
          <>
            <Button type="primary" icon={<SearchOutlined />} onClick={applyFilter}>
              筛选
            </Button>
            <Button icon={<PlusOutlined />} onClick={() => { setEditSchedule(null); setRunOpen(true); }}>
              新建调度
            </Button>
          </>
        }
      />

      <div ref={fill.ref} style={{ flex: 1, minHeight: 0 }}>
        {fill.fillStyle}
        <Table
          className="fill-table"
          dataSource={filtered}
          rowKey="id"
          scroll={{ y: fill.scrollY }}
          pagination={{ ...TABLE_PAGINATION }}
          columns={[
            { title: "名称", dataIndex: "name", width: 180, ellipsis: true },
            {
              title: "流水线",
              width: 160,
              ellipsis: true,
              render: (_, r: Schedule) =>
                r.pipeline_name ? (
                  <Link to={`/pipelines/${r.pipeline_name}`}>{r.pipeline_display_name ?? r.pipeline_name}</Link>
                ) : (
                  "-"
                ),
            },
            { title: "类型", dataIndex: "trigger_type", width: 90, render: (t: string) => scheduleTypeLabels[t] ?? t },
            {
              title: "表达式/间隔/时刻",
              ellipsis: true,
              render: (_, r: Schedule) =>
                r.cron_expr ||
                (r.interval_seconds ? `${r.interval_seconds}s` : null) ||
                (r.run_at ? new Date(r.run_at).toLocaleString("zh-CN", { hour12: false }) : "-"),
            },
            {
              title: "启用",
              width: 70,
              render: (_, r: Schedule) => <Switch size="small" checked={r.enabled} onChange={(checked) => enabledMutation.mutate({ id: r.id, enabled: checked })} />,
            },
            {
              title: "下次执行",
              dataIndex: "next_run_at",
              width: 170,
              render: (v: string) => (v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "-"),
            },
            {
              title: "操作",
              width: 140,
              render: (_, r: Schedule) => (
                <Space>
                  <Button size="small" onClick={() => { setEditSchedule(r); setRunOpen(true); }}>
                    编辑
                  </Button>
                  <Popconfirm title="确认删除该调度？" onConfirm={() => deleteMutation.mutate(r.id)}>
                    <Button size="small" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </div>
      <RunModal
        open={runOpen}
        onClose={() => setRunOpen(false)}
        mode="schedule"
        editSchedule={editSchedule}
      />
    </div>
  );
}
