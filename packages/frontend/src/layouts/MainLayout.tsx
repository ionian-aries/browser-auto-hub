import { Layout, Menu } from "antd";
import {
  DashboardOutlined,
  NodeIndexOutlined,
  FieldTimeOutlined,
  UnorderedListOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

const { Sider, Content } = Layout;

const menuItems = [
  { key: "/", icon: <DashboardOutlined />, label: "看板" },
  { key: "/pipelines", icon: <NodeIndexOutlined />, label: "流水线" },
  { key: "/schedules", icon: <FieldTimeOutlined />, label: "调度管理" },
  { key: "/executions", icon: <UnorderedListOutlined />, label: "执行记录" },
  { key: "/settings", icon: <SettingOutlined />, label: "系统设置" },
];

export function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  // 仅导航页路由参与选中；瞬态页（/run 等无匹配项）不选中任何菜单（spec 4 §2.5）
  const matchedKey = menuItems
    .filter((item) => location.pathname.startsWith(item.key) && item.key !== "/")
    .sort((a, b) => b.key.length - a.key.length)[0]?.key;
  const selectedKey = matchedKey ?? (location.pathname === "/" ? "/" : undefined);

  return (
    <Layout style={{ height: "100vh" }}>
      <Sider theme="dark" style={{ overflow: "auto" }}>
        <div
          style={{
            color: "#fff",
            padding: "20px 16px",
            fontSize: "16px",
            fontWeight: 600,
            letterSpacing: 0.5,
          }}
        >
          Browser Auto Hub
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={selectedKey ? [selectedKey] : []}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout style={{ background: "#f5f5f5", height: "100vh" }}>
        <Content style={{ padding: 24, overflow: "auto" }}>
          <div
            style={{
              padding: 24,
              background: "#fff",
              borderRadius: 8,
              minHeight: "100%",
            }}
          >
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
