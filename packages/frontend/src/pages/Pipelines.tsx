import { useState } from "react";
import { Button, Card, Col, Input, Row, Select, Switch, Tag, message } from "antd";
import { ClockCircleOutlined, PlayCircleOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { executionApi, pipelineApi } from "../api/client";
import { RunModal } from "../components/RunModal";
import { pipelineStatusLabels, statusColors, statusLabels, triggerModeLabels } from "../labels";
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
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });
  const { data: executions } = useQuery({
    queryKey: ["executions", { page_size: 100 }],
    queryFn: () => executionApi.listItems({ page_size: 100 }),
  });

  // 筛选（spec 4 §4.6）
  const [keyword, setKeyword] = useState("");
  const [modeFilter, setModeFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();

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
    if (keyword && !p.display_name.includes(keyword) && !p.name.includes(keyword)) return false;
    if (modeFilter && !p.trigger_modes.includes(modeFilter)) return false;
    if (statusFilter && p.status !== statusFilter) return false;
    return true;
  });

  const openRun = (p: Pipeline, mode: "now" | "schedule") => {
    setRunPipeline(p);
    setRunMode(mode);
  };

  return (
    <div>
      <h2>流水线</h2>

      <div style={{ marginBottom: 16, display: "flex", gap: 12 }}>
        <Input.Search
          placeholder="搜索名称"
          allowClear
          style={{ width: 220 }}
          onSearch={(v) => setKeyword(v.trim())}
          onChange={(e) => { if (!e.target.value) setKeyword(""); }}
        />
        <Select
          placeholder="触发方式"
          allowClear
          style={{ width: 160 }}
          value={modeFilter}
          onChange={setModeFilter}
          options={Object.entries(triggerModeLabels).map(([value, label]) => ({ value, label }))}
        />
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 120 }}
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: "active", label: "启用" },
            { value: "disabled", label: "停用" },
          ]}
        />
      </div>

      <Row gutter={[16, 16]}>
        {filtered?.map((p) => {
          const active = p.status === "active";
          return (
            <Col span={8} key={p.id}>
              <Card
                title={
                  <a onClick={() => navigate(`/pipelines/${p.name}`)}>
                    {p.display_name}
                  </a>
                }
                extra={
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                    <Tag color={active ? "success" : "default"}>{pipelineStatusLabels[p.status] ?? p.status}</Tag>
                    <Switch
                      size="small"
                      checked={active}
                      onChange={(v) =>
                        statusMutation.mutate({ name: p.name, status: v ? "active" : "disabled" })
                      }
                    />
                  </span>
                }
                actions={[
                  <Button
                    key="run"
                    type="link"
                    icon={<PlayCircleOutlined />}
                    disabled={!active}
                    onClick={() => openRun(p, "now")}
                  >
                    立即执行
                  </Button>,
                  <Button
                    key="schedule"
                    type="link"
                    icon={<ClockCircleOutlined />}
                    disabled={!active}
                    onClick={() => openRun(p, "schedule")}
                  >
                    定时设置
                  </Button>,
                ]}
              >
                <p style={{ color: "#666", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {p.description || "暂无描述"}
                </p>
                <div>
                  {p.trigger_modes.map((m) => (
                    <Tag key={m}>{triggerModeLabels[m] ?? m}</Tag>
                  ))}
                </div>
                <div style={{ marginTop: 8, fontSize: 12, color: "#999" }}>
                  {(() => {
                    const last = getLastExecution(p.name);
                    if (!last) return "暂无执行记录";
                    return (
                      <>
                        最近执行: <Tag color={statusColors[last.status]} style={{ fontSize: 11 }}>{statusLabels[last.status] ?? last.status}</Tag>
                        {last.created_at && formatRelativeTime(last.created_at)}
                      </>
                    );
                  })()}
                </div>
              </Card>
            </Col>
          );
        })}
      </Row>

      <RunModal
        open={!!runPipeline}
        onClose={() => setRunPipeline(null)}
        pipeline={runPipeline}
        mode={runMode}
      />
    </div>
  );
}
