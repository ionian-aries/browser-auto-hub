import { Card, Col, Row, Statistic } from "antd";
import { useQuery } from "@tanstack/react-query";
import { executionApi, pipelineApi } from "../api/client";

export function Dashboard() {
  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });
  const { data: executions } = useQuery({ queryKey: ["executions"], queryFn: () => executionApi.list() });

  const running = executions?.filter((e) => e.status === "running").length ?? 0;
  const total = executions?.length ?? 0;

  return (
    <div>
      <h2>仪表盘</h2>
      <Row gutter={16}>
        <Col span={6}>
          <Card><Statistic title="Pipeline 总数" value={pipelines?.length ?? 0} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="正在运行" value={running} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="总执行次数" value={total} /></Card>
        </Col>
      </Row>
    </div>
  );
}
