import { Layout, Menu } from "antd";
import {
  DashboardOutlined,
  NodeIndexOutlined,
  UnorderedListOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

const { Sider, Content } = Layout;

const menuItems = [
  { key: "/", icon: <DashboardOutlined />, label: "看板" },
  { key: "/pipelines", icon: <NodeIndexOutlined />, label: "Pipeline" },
  { key: "/executions", icon: <UnorderedListOutlined />, label: "执行记录" },
  { key: "/settings", icon: <SettingOutlined />, label: "系统设置" },
];

export function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  const selectedKey = menuItems
    .filter((item) => location.pathname.startsWith(item.key) && item.key !== "/")
    .sort((a, b) => b.key.length - a.key.length)[0]?.key || "/";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider>
        <div style={{ color: "#fff", padding: "16px", fontSize: "16px", fontWeight: "bold" }}>
          Browser Auto Hub
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
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
