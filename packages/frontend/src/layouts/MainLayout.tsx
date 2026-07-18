import { Layout, Menu } from "antd";
import {
  DashboardOutlined,
  NodeIndexOutlined,
  ClockCircleOutlined,
  UnorderedListOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

const { Sider, Content } = Layout;

const menuItems = [
  { key: "/", icon: <DashboardOutlined />, label: "仪表盘" },
  { key: "/pipelines", icon: <NodeIndexOutlined />, label: "Pipeline" },
  { key: "/schedules", icon: <ClockCircleOutlined />, label: "调度管理" },
  { key: "/executions", icon: <UnorderedListOutlined />, label: "执行记录" },
  { key: "/settings", icon: <SettingOutlined />, label: "系统设置" },
];

export function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider>
        <div style={{ color: "#fff", padding: "16px", fontSize: "16px", fontWeight: "bold" }}>
          Browser Auto Hub
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Content style={{ margin: "24px", padding: "24px", background: "#fff" }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
