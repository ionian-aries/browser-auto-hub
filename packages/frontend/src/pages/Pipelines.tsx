import { useState } from "react";
import { Button, Select, Space, Switch, Table, Tag, message } from "antd";
import { ClockCircleOutlined, PlayCircleOutlined, SearchOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { executionApi, pipelineApi } from "../api/client";
import { labelWithHint } from "../components/LabelHint";
import { FilterBar, FilterItem, LIST_PAGE_STYLE, TABLE_PAGINATION, useFillTable } from "../components/ListPage";
import { RunModal } from "../components/RunModal";
import { statusColors, statusLabels, triggerModeLabels } from "../labels";
import type { Execution, Pipeline } from "../types";

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

export function Pipelines() {
  const queryClient = useQueryClient();
  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });
  const { data: executions } = useQuery({
    queryKey: ["executions", { page_size: 100 }],
    queryFn: () => executionApi.listItems({ page_size: 100 }),
  });
  const fill = useFillTable();

  // 筛选草稿（点「筛选」才应用，spec 4 §2.6）
  const [nameDraft, setNameDraft] = useState<string | undefined>();
  const [modesDraft, setModesDraft] = useState<string[] | undefined>();
  const [statusDraft, setStatusDraft] = useState<string[] | undefined>();
  const [applied, setApplied] = useState<{ name?: string; modes?: string[]; statuses?: string[] }>({});

  // RunModal 入口
  const [runPipeline, setRunPipeline] = useState<Pipeline | null>(null);
  const [runMode, setRunMode] = useState<"now" | "schedule">("now");

  const statusMutation = useMutation({
    mutationFn: ({ name, status }: { name: string; status: string }) =>
      pipelineApi.patch(name, { status }),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
      message.success(vars.status === "active" ? "已启用" : "已停用");
    },
    onError: () => {
      message.error("保存失败");
    },
  });

  const getLastExecution = (pipelineName: string): Execution | undefined =>
    executions?.find((e) => e.pipeline_name === pipelineName);

  const filtered = pipelines?.filter((p) => {
    if (applied.name && p.name !== applied.name) return false;
    if (applied.modes?.length && !p.trigger_modes.some((m) => applied.modes!.includes(m))) return false;
    if (applied.statuses?.length && !applied.statuses.includes(p.status)) return false;
    return true;
  });

  const openRun = (p: Pipeline, mode: "now" | "schedule") => {
    setRunPipeline(p);
    setRunMode(mode);
  };

  const applyFilter = () => setApplied({ name: nameDraft, modes: modesDraft, statuses: statusDraft });

  return (
    <div style={LIST_PAGE_STYLE}>
      <h2>流水线</h2>

      <FilterBar
        filters={
          <>
            <FilterItem label="名称">
              <Select
                placeholder="全部"
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ width: 200 }}
                value={nameDraft}
                onChange={setNameDraft}
                options={pipelines?.map((p) => ({ value: p.name, label: p.display_name }))}
              />
            </FilterItem>
            <FilterItem label="触发方式">
              <Select
                placeholder="全部"
                allowClear
                mode="multiple"
                maxTagCount="responsive"
                style={{ width: 200 }}
                value={modesDraft}
                onChange={(v) => setModesDraft(v.length ? v : undefined)}
                options={Object.entries(triggerModeLabels).map(([value, label]) => ({ value, label }))}
              />
            </FilterItem>
            <FilterItem label="状态">
              <Select
                placeholder="全部"
                allowClear
                mode="multiple"
                maxTagCount="responsive"
                style={{ width: 160 }}
                value={statusDraft}
                onChange={(v) => setStatusDraft(v.length ? v : undefined)}
                options={[
                  { value: "active", label: "启用" },
                  { value: "disabled", label: "停用" },
                ]}
              />
            </FilterItem>
          </>
        }
        actions={
          <Button type="primary" icon={<SearchOutlined />} onClick={applyFilter}>
            筛选
          </Button>
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
            {
              title: "名称",
              width: 200,
              ellipsis: true,
              render: (_, p: Pipeline) => (
                <Link to={`/pipelines/${p.name}`}>{p.display_name}</Link>
              ),
            },
            {
              title: "版本",
              width: 76,
              render: (_, p: Pipeline) => <span style={{ color: "#666" }}>v{p.version}</span>,
            },
            {
              title: "描述",
              dataIndex: "description",
              width: 240,
              ellipsis: true,
              render: (v: string) => v || <span style={{ color: "#999" }}>暂无描述</span>,
            },
            {
              title: "触发方式",
              width: 140,
              render: (_, p: Pipeline) =>
                p.trigger_modes.map((m) => triggerModeLabels[m] ?? m).join(", "),
            },
            {
              title: labelWithHint("状态", "开关即启停：开 = 启用，关 = 停用"),
              width: 70,
              render: (_, p: Pipeline) => (
                <Switch
                  size="small"
                  checked={p.status === "active"}
                  onChange={(v) =>
                    statusMutation.mutate({ name: p.name, status: v ? "active" : "disabled" })
                  }
                />
              ),
            },
            {
              title: "最近执行",
              width: 170,
              render: (_, p: Pipeline) => {
                const last = getLastExecution(p.name);
                if (!last) return <span style={{ color: "#999" }}>暂无执行记录</span>;
                return (
                  <span style={{ fontSize: 12, color: "#666" }}>
                    <Tag color={statusColors[last.status]} style={{ fontSize: 11 }}>
                      {statusLabels[last.status] ?? last.status}
                    </Tag>
                    {last.created_at && formatRelativeTime(last.created_at)}
                  </span>
                );
              },
            },
            {
              title: "操作",
              width: 180,
              render: (_, p: Pipeline) => {
                const active = p.status === "active";
                return (
                  <Space>
                    <Button
                      type="link"
                      size="small"
                      icon={<PlayCircleOutlined />}
                      disabled={!active}
                      onClick={() => openRun(p, "now")}
                    >
                      立即执行
                    </Button>
                    <Button
                      type="link"
                      size="small"
                      icon={<ClockCircleOutlined />}
                      disabled={!active}
                      onClick={() => openRun(p, "schedule")}
                    >
                      定时设置
                    </Button>
                  </Space>
                );
              },
            },
          ]}
        />
      </div>

      <RunModal
        open={!!runPipeline}
        onClose={() => setRunPipeline(null)}
        pipeline={runPipeline}
        mode={runMode}
      />
    </div>
  );
}
