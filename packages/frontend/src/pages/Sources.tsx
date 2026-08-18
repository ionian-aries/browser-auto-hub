import { useState } from "react";
import { Button, Select, Table, Tag, Typography } from "antd";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { FilterBar, FilterItem, LIST_PAGE_STYLE, TABLE_PAGINATION, useFillTable } from "../components/ListPage";
import { sourceApi } from "../api/client";
import type { Source } from "../types";

export function Sources() {
  const fill = useFillTable();

  // 筛选草稿（点「筛选」才应用，spec 4 §2.6）
  const [nameDraft, setNameDraft] = useState<string | undefined>();
  const [applied, setApplied] = useState<{ name?: string }>({});

  const { data: sources } = useQuery({
    queryKey: ["sources"],
    queryFn: sourceApi.list,
  });

  const filtered = sources?.filter((s) => {
    if (applied.name && s.source_name !== applied.name) return false;
    return true;
  });

  const applyFilter = () => setApplied({ name: nameDraft });

  return (
    <div style={LIST_PAGE_STYLE}>
      <h2>信源管理</h2>

      <FilterBar
        filters={
          <FilterItem label="信源">
            <Select
              placeholder="全部"
              allowClear
              showSearch
              optionFilterProp="label"
              style={{ width: 180 }}
              value={nameDraft}
              onChange={setNameDraft}
              options={sources?.map((s) => ({ value: s.source_name, label: s.source_name }))}
            />
          </FilterItem>
        }
        actions={
          <>
            <Button type="primary" icon={<SearchOutlined />} onClick={applyFilter}>
              筛选
            </Button>
            <Button icon={<PlusOutlined />}>
              新增网站
            </Button>
          </>
        }
      />

      <Typography.Title level={5} style={{ margin: "16px 0 8px" }}>
        采集源网站
      </Typography.Title>

      <div ref={fill.ref} style={{ flex: 1, minHeight: 0 }}>
        {fill.fillStyle}
        <Table
          key={filtered ? "loaded" : "loading"}
          className="fill-table"
          dataSource={filtered}
          rowKey="source_name"
          scroll={{ y: fill.scrollY }}
          pagination={{ ...TABLE_PAGINATION }}
          expandable={{
            expandRowByClick: true,
            defaultExpandAllRows: true,
            expandedRowRender: (record: Source) => (
              <Table
                dataSource={record.entries}
                rowKey="url"
                pagination={false}
                size="small"
                columns={[
                  { title: "采集入口", dataIndex: "entry_name", width: 200 },
                  {
                    title: "网址",
                    dataIndex: "url",
                    render: (u: string) => (
                      <a href={u} target="_blank" rel="noopener noreferrer">
                        {u}
                      </a>
                    ),
                  },
                  {
                    title: "采集规则",
                    dataIndex: "has_override",
                    width: 100,
                    align: "center" as const,
                    render: (v: boolean) =>
                      v ? (
                        <Tag color="orange">自定义</Tag>
                      ) : (
                        <Tag color="green">标准</Tag>
                      ),
                  },
                ]}
              />
            ),
          }}
          columns={[
            { title: "信源名称", dataIndex: "source_name", width: 140 },
            {
              title: "网站地址",
              dataIndex: "base_url",
              ellipsis: true,
              render: (u: string) => (
                <a href={u} target="_blank" rel="noopener noreferrer">
                  {u}
                </a>
              ),
            },
            { title: "采集入口数量", dataIndex: "entry_count", width: 120, align: "center" as const },
            {
              title: "详情变体",
              dataIndex: "detail_variant_count",
              width: 90,
              align: "center" as const,
            },
            {
              title: "列表字段",
              dataIndex: "list_fields",
              width: 220,
              render: (fs: string[]) => (
                <>
                  {fs.map((f) => (
                    <Tag key={f}>{f}</Tag>
                  ))}
                </>
              ),
            },
            {
              title: "详情字段",
              dataIndex: "detail_fields",
              width: 200,
              render: (fs: string[]) => (
                <>
                  {fs.map((f) => (
                    <Tag key={f}>{f}</Tag>
                  ))}
                </>
              ),
            },
          ]}
        />
      </div>
    </div>
  );
}
