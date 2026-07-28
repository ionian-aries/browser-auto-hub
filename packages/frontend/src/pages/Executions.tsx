import { useState } from "react";
import { Button, DatePicker, Popconfirm, Select, Table, Tag, message } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import type { Dayjs } from "dayjs";
import { executionApi, pipelineApi } from "../api/client";
import { FilterBar, FilterItem, LIST_PAGE_STYLE, TABLE_PAGINATION, useFillTable } from "../components/ListPage";
import { statusColors, statusLabels, triggerLabels } from "../labels";
import { durationSeconds, formatDuration } from "../utils/format";
import type { Execution } from "../types";

const { RangePicker } = DatePicker;

export function Executions() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // 筛选草稿（点「筛选」才应用并回到第 1 页，spec 4 §2.6）
  const [pipelineDraft, setPipelineDraft] = useState<string | undefined>();
  const [statusDraft, setStatusDraft] = useState<string[] | undefined>();
  const [rangeDraft, setRangeDraft] = useState<[Dayjs, Dayjs] | null>(null);
  const [applied, setApplied] = useState<{
    pipeline?: string;
    status?: string[];
    range: [Dayjs, Dayjs] | null;
  }>({ range: null });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const fill = useFillTable();

  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });
  const { data, isLoading } = useQuery({
    queryKey: [
      "executions",
      {
        pipeline: applied.pipeline,
        status: applied.status?.join(","),
        start: applied.range?.[0]?.toISOString(),
        end: applied.range?.[1]?.toISOString(),
        page,
        page_size: pageSize,
      },
    ],
    queryFn: () =>
      executionApi.list({
        pipeline: applied.pipeline,
        status: applied.status?.join(","),
        start: applied.range?.[0]?.toISOString(),
        end: applied.range?.[1]?.toISOString(),
        page,
        page_size: pageSize,
      }),
    refetchInterval: 5000,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => executionApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["executions"] });
      message.success("删除成功");
    },
    onError: () => {
      message.error("删除失败");
    },
  });

  const applyFilter = () => {
    setApplied({ pipeline: pipelineDraft, status: statusDraft, range: rangeDraft });
    setPage(1);
  };

  return (
    <div style={LIST_PAGE_STYLE}>
      <h2>执行记录</h2>

      <FilterBar
        filters={
          <>
            <FilterItem label="流水线">
              <Select
                placeholder="全部"
                allowClear
                style={{ width: 180 }}
                value={pipelineDraft}
                onChange={setPipelineDraft}
                options={pipelines?.map((p) => ({ value: p.name, label: p.display_name }))}
              />
            </FilterItem>
            <FilterItem label="状态">
              <Select
                placeholder="全部"
                allowClear
                mode="multiple"
                maxTagCount="responsive"
                style={{ width: 220 }}
                value={statusDraft}
                onChange={(v) => setStatusDraft(v.length ? v : undefined)}
                options={Object.entries(statusLabels).map(([value, label]) => ({ value, label }))}
              />
            </FilterItem>
            <FilterItem label="时间范围">
              <RangePicker
                showTime={{ format: "HH:mm" }}
                format="YYYY-MM-DD HH:mm"
                placeholder={["开始时间", "结束时间"]}
                value={rangeDraft}
                onChange={(dates) => {
                  if (dates && dates[0] && dates[1]) {
                    setRangeDraft([dates[0], dates[1]]);
                  } else {
                    setRangeDraft(null);
                  }
                }}
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
          dataSource={data?.items}
          rowKey="id"
          loading={isLoading}
          scroll={{ y: fill.scrollY }}
          onRow={(record) => ({
            onClick: () => navigate(`/executions/${record.id}`),
            style: { cursor: "pointer" },
          })}
          pagination={{
            ...TABLE_PAGINATION,
            current: page,
            pageSize,
            total: data?.total,
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
          columns={[
          {
            title: "流水线",
            width: 180,
            ellipsis: true,
            render: (_: unknown, r: Execution) =>
              r.pipeline_name ? (
                <Link to={`/pipelines/${r.pipeline_name}`}>{r.pipeline_display_name ?? r.pipeline_name}</Link>
              ) : (
                "-"
              ),
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 100,
            render: (s: string) => <Tag color={statusColors[s]}>{statusLabels[s] ?? s}</Tag>,
          },
          {
            title: "触发方式",
            dataIndex: "trigger_type",
            width: 100,
            render: (t: string) => triggerLabels[t] ?? t,
          },
          {
            title: "开始时间",
            dataIndex: "started_at",
            width: 170,
            render: (v: string) => v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "-",
          },
          {
            title: "耗时",
            width: 90,
            render: (_: unknown, r: Execution) => {
              const sec = durationSeconds(r.started_at, r.finished_at);
              return sec === null ? "-" : formatDuration(sec);
            },
          },
          {
            title: "重试",
            dataIndex: "retry_count",
            width: 70,
            render: (v: number) => v > 0 ? v : "-",
          },
          {
            title: "结果",
            ellipsis: true,
            render: (_: unknown, r: Execution) => {
              if (r.result_summary) {
                return <span style={{ color: "#666" }}>{JSON.stringify(r.result_summary).slice(0, 40)}</span>;
              }
              if (r.error_message) {
                return <span style={{ color: "#ff4d4f" }}>{r.error_message.slice(0, 40)}</span>;
              }
              return "-";
            },
          },
          {
            title: "操作",
            width: 80,
            render: (_: unknown, r: Execution) =>
              r.status !== "pending" && r.status !== "running" ? (
                // React portal 合成事件沿组件树冒泡：必须拦截，否则确认删除会触发行 onClick 误入详情
                <span onClick={(e) => e.stopPropagation()}>
                  <Popconfirm
                    title="确认删除该执行记录？"
                    description="仅删除执行记录与关联日志；MinIO 文件与业务数据不受影响"
                    onConfirm={() => deleteMutation.mutate(r.id)}
                  >
                    <Button size="small" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </span>
              ) : null,
          },
        ]}
        />
      </div>
    </div>
  );
}
