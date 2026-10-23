import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Card, Table, Tag, Button, Space, Popconfirm, Spin, Empty, Row, Col, Statistic, message, Select } from 'antd'
import { FileTextOutlined, AuditOutlined, WarningOutlined, DeleteOutlined, SearchOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import apiClient from '../api/client'
import type { DocumentResponse } from '../types/document'
import { REVIEW_TYPE_LABELS, type ReviewType, type ReviewTaskResponse } from '../types/review'

const statusMap: Record<string, { color: string; label: string }> = {
  COMPLETED: { color: 'green', label: '已完成' },
  PROCESSING: { color: 'blue', label: '处理中' },
  FAILED: { color: 'red', label: '失败' },
  PENDING: { color: 'default', label: '待处理' },
  REJECTED: { color: 'red', label: '已拒绝' },
}

export default function DashboardPage() {
  const [documents, setDocuments] = useState<DocumentResponse[]>([])
  const [reviews, setReviews] = useState<ReviewTaskResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [reviewingId, setReviewingId] = useState<number | null>(null)
  const [reviewType, setReviewType] = useState<ReviewType>('FULL')
  const navigate = useNavigate()

  const fetchData = async () => {
    setLoading(true)
    try {
      const [docRes, reviewRes] = await Promise.all([
        apiClient.get('/documents?size=100'),
        apiClient.get('/reviews?size=100'),
      ])
      setDocuments(docRes?.data?.data?.content || [])
      setReviews(reviewRes?.data?.data?.content || [])
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { fetchData() }, [])

  const startReview = async (documentId: number) => {
    setReviewingId(documentId)
    try {
      const { data } = await apiClient.post('/reviews', { documentId, reviewType })
      navigate(`/review/${data.data.taskId}`)
    } catch {
      message.error('启动审查失败')
    } finally {
      setReviewingId(null)
    }
  }

  const deleteDocument = async (documentId: number) => {
    try {
      await apiClient.delete(`/documents/${documentId}`)
      setDocuments(prev => prev.filter(d => d.documentId !== documentId))
      message.success('文档已删除')
    } catch {
      message.error('删除失败')
    }
  }

  const deleteReview = async (taskId: number) => {
    try {
      await apiClient.delete(`/reviews/${taskId}`)
      setReviews(prev => prev.filter(r => r.taskId !== taskId))
      message.success('审查记录已删除')
    } catch {
      message.error('删除失败')
    }
  }

  const highRiskCount = reviews.reduce((sum, r) => sum + (r.riskCountHigh || 0), 0)

  if (loading) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" tip="加载中..." /></div>
  }

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={8}>
          <Card><Statistic title="总文档数" value={documents.length} prefix={<FileTextOutlined />} /></Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card><Statistic title="总审查数" value={reviews.length} prefix={<AuditOutlined />} /></Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card><Statistic title="高风险条款" value={highRiskCount} prefix={<WarningOutlined />} valueStyle={{ color: highRiskCount > 0 ? '#ff4d4f' : undefined }} /></Card>
        </Col>
      </Row>

      <Card title="我的文档" extra={
        <Space>
          <span style={{ fontSize: 12, color: '#666' }}>审查模式：</span>
          <Select size="small" value={reviewType} onChange={setReviewType} style={{ width: 110 }}
            options={Object.entries(REVIEW_TYPE_LABELS).map(([value, label]) => ({ value, label }))} />
          <Link to="/upload"><Button type="primary" size="small">上传文档</Button></Link>
        </Space>
      } style={{ marginBottom: 24 }}>
        {documents.length === 0 ? (
          <Empty description="暂无文档" />
        ) : (
          <Table dataSource={documents} rowKey="documentId" pagination={{ pageSize: 10 }} size="middle">
            <Table.Column title="文件名" dataIndex="originalFilename" ellipsis />
            <Table.Column title="类型" dataIndex="fileType" width={80} />
            <Table.Column title="状态" dataIndex="documentStatus" width={100}
              render={(s: string) => <Tag>{s}</Tag>} />
            <Table.Column title="条款数" dataIndex="clauseCount" width={80}
              render={(v: number) => v || '-'} />
            <Table.Column title="操作" width={240}
              render={(_: any, record: DocumentResponse) => (
                <Space>
                  <Button type="primary" size="small" icon={<SearchOutlined />} loading={reviewingId === record.documentId}
                    onClick={() => startReview(record.documentId)}>
                    审查
                  </Button>
                  <Button size="small" icon={<QuestionCircleOutlined />}
                    onClick={() => navigate(`/consult/${record.documentId}`)}>
                    咨询
                  </Button>
                  <Popconfirm title="确认删除此文档？" onConfirm={() => deleteDocument(record.documentId)}>
                    <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
                  </Popconfirm>
                </Space>
              )} />
          </Table>
        )}
      </Card>

      <Card title="审查记录">
        {reviews.length === 0 ? (
          <Empty description="暂无审查记录" />
        ) : (
          <Table dataSource={reviews} rowKey="taskId" pagination={{ pageSize: 10 }} size="middle">
            <Table.Column title="文档" dataIndex="documentName" ellipsis />
            <Table.Column title="状态" dataIndex="status" width={100}
              render={(s: string) => {
                const cfg = statusMap[s] || { color: 'default', label: s }
                return <Tag color={cfg.color}>{cfg.label}</Tag>
              }} />
            <Table.Column title="高风险" dataIndex="riskCountHigh" width={80}
              render={(v: number) => <span style={{ color: '#ff4d4f', fontWeight: 'bold' }}>{v}</span>} />
            <Table.Column title="中风险" dataIndex="riskCountMedium" width={80}
              render={(v: number) => <span style={{ color: '#faad14' }}>{v}</span>} />
            <Table.Column title="操作" width={160}
              render={(_: any, record: ReviewTaskResponse) => (
                <Space>
                  <Button size="small" onClick={() => navigate(`/review/${record.taskId}`)}>详情</Button>
                  <Popconfirm title="确认删除此审查记录？" onConfirm={() => deleteReview(record.taskId)}>
                    <Button size="small" danger>删除</Button>
                  </Popconfirm>
                </Space>
              )} />
          </Table>
        )}
      </Card>
    </div>
  )
}
