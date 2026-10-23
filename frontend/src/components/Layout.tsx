import { useState } from 'react'
import { Outlet, useNavigate, useLocation, Link } from 'react-router-dom'
import { Layout, Menu, Button, theme, Breadcrumb } from 'antd'
import {
  DashboardOutlined,
  UploadOutlined,
  LogoutOutlined,
  UserOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'
import useAuth from '../hooks/useAuth'
import apiClient from '../api/client'

const { Header, Sider, Content } = Layout

export default function AppLayout() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { user, logout } = useAuth()
  const [collapsed, setCollapsed] = useState(false)
  const { token } = theme.useToken()

  const handleLogout = async () => {
    try {
      await apiClient.post('/auth/logout', { refreshToken: localStorage.getItem('refreshToken') })
    } catch { /* ignore */ }
    logout()
    navigate('/login')
  }

  const selectedKey = pathname === '/' || pathname === '' ? '/dashboard' : pathname
  const breadcrumbItems = pathname
    .split('/')
    .filter(Boolean)
    .map((seg, i, arr) => {
      const labelMap: Record<string, string> = {
        upload: '上传文档',
        review: '审查详情',
        consult: 'AI 咨询',
        eval: 'Agent 评测',
      }
      return { title: labelMap[seg] || seg, path: '/' + arr.slice(0, i + 1).join('/') }
    })

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        style={{ background: token.colorBgContainer }}
      >
        <div style={{
          height: 48, margin: 8, display: 'flex', alignItems: 'center',
          justifyContent: 'center', fontWeight: 700, fontSize: collapsed ? 14 : 16,
          whiteSpace: 'nowrap', overflow: 'hidden',
        }}>
          {collapsed ? 'SC' : '智能合同审查'}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={[
            { key: '/dashboard', icon: <DashboardOutlined />, label: <Link to="/">仪表板</Link> },
            { key: '/upload', icon: <UploadOutlined />, label: <Link to="/upload">上传文档</Link> },
            { key: '/eval', icon: <ExperimentOutlined />, label: <Link to="/eval">Agent 评测</Link> },
          ]}
        />
      </Sider>

      <Layout>
        <Header style={{
          background: token.colorBgContainer, padding: '0 24px',
          display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
        }}>
          <span style={{ marginRight: 12 }}>
            <UserOutlined style={{ marginRight: 4 }} />
            {user?.username}
          </span>
          <Button icon={<LogoutOutlined />} onClick={handleLogout} type="text">
            退出
          </Button>
        </Header>

        <Content style={{ margin: 16 }}>
          {pathname !== '/' && pathname !== '' && (
            <Breadcrumb
              items={[{ title: <Link to="/">首页</Link> }, ...breadcrumbItems]}
              style={{ marginBottom: 16 }}
            />
          )}
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
