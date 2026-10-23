import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Card, Descriptions, Progress, Statistic, Tag, Timeline, Spin, Empty, Collapse, Typography } from 'antd'
import { ClockCircleOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import apiClient from '../api/client'
import { useSse } from '../hooks/useSse'
import { REVIEW_TYPE_LABELS, type ReviewTaskResponse, type ReviewResultResponse } from '../types/review'
import RiskItemCard from '../components/RiskItemCard'

const { Title, Text } = Typography

const statusIconMap: Record<string, React.ReactNode> = {
  COMPLETED: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  PROCESSING: <ClockCircleOutlined style={{ color: '#1890ff' }} />,
  FAILED: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
}

const levelColorMap: Record<string, string> = { HIGH: 'red', MEDIUM: 'orange', LOW: 'green' }

export default function ReviewPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const tid = taskId ? parseInt(taskId) : null
  const [task, setTask] = useState<ReviewTaskResponse | null>(null)
  const [result, setResult] = useState<ReviewResultResponse | null>(null)
  const { events, progress, status } = useSse(tid)

  useEffect(() => {
    if (!tid) return
    apiClient.get(`/reviews/${tid}`).then(r => setTask(r.data.data)).catch(() => {})
  }, [tid])

  useEffect(() => {
    if (status === 'COMPLETED' && tid) {
      apiClient.get(`/reviews/${tid}/result`).then(r => setResult(r.data.data)).catch(() => {})
    }
  }, [status, tid])

  useEffect(() => {
    if (task?.status === 'COMPLETED' && tid) {
      apiClient.get(`/reviews/${tid}/result`).then(r => setResult(r.data.data)).catch(() => {})
    }
  }, [task?.status, tid])

  if (!task) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>

  const pct = progress.total > 0
    ? Math.round((progress.reviewed / progress.total) * 100)
    : task.totalClauses > 0 ? Math.round((task.reviewedClauses / task.totalClauses) * 100) : 0

  const riskEvents = events.filter(e => e.eventType === 'RISK_FOUND' || e.eventType === 'CLAUSE_ANALYZING')

  return (
    <div>
      <Title level={4}>审查详情</Title>

      <Card style={{ marginBottom: 24 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="文档">{task.documentName}</Descriptions.Item>
          <Descriptions.Item label="审查模式">
            <Tag color={task.reviewType === 'FULL' ? 'blue' : 'orange'}>
              {REVIEW_TYPE_LABELS[task.reviewType] || task.reviewType}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            {statusIconMap[task.status]} <Text style={{ marginLeft: 4 }}>{task.status}</Text>
          </Descriptions.Item>
        </Descriptions>
        <Progress percent={pct} status={pct === 100 ? 'success' : 'active'}
          format={() => `${progress.reviewed || task.reviewedClauses}/${progress.total || task.totalClauses} 条款`} />
      </Card>

      {/* Live SSE events */}
      {riskEvents.length > 0 && !result && (
        <Card title="实时分析" size="small" style={{ marginBottom: 24 }}>
          <Timeline items={riskEvents.slice(-20).map((e, i) => ({
            color: e.eventType === 'RISK_FOUND'
              ? (levelColorMap[e.riskLevel] || 'blue')
              : 'gray',
            children: e.eventType === 'RISK_FOUND'
              ? <span><Tag color={levelColorMap[e.riskLevel]}>{e.riskLevel}</Tag> 条款{e.clauseIndex}: {e.riskDescription}</span>
              : <Text type="secondary">正在分析条款 {e.clauseIndex}...</Text>,
          }))} />
        </Card>
      )}

      {/* Review result */}
      {result ? (
        <>
          <Card style={{ marginBottom: 24, textAlign: 'center' }}>
            <Statistic
              title="综合评分"
              value={result.overallScore}
              suffix="/ 100"
              valueStyle={{ color: result.overallScore >= 80 ? '#52c41a' : result.overallScore >= 60 ? '#faad14' : '#ff4d4f', fontSize: 48 }}
            />
            <Text type="secondary">{result.summary}</Text>

            <Card size="small" title="行动建议" style={{ marginTop: 16, textAlign: 'left' }}>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {result.recommendations.map((rec, i) => <li key={i} style={{ marginBottom: 4 }}>{rec}</li>)}
              </ul>
            </Card>
          </Card>

          <Title level={5}>风险明细 ({result.riskItems.length})</Title>
          {result.riskItems.length === 0 ? (
            <Empty description="未发现风险条款" />
          ) : (
            <Collapse defaultActiveKey={result.riskItems.filter(r => r.riskLevel === 'HIGH').map((_, i) => i)}
              items={result.riskItems.map((item, i) => ({
                key: i,
                label: (
                  <span>
                    <Tag color={levelColorMap[item.riskLevel]}>{item.riskLevel}</Tag>
                    条款 {item.clauseIndex} — {item.riskType}
                  </span>
                ),
                children: <RiskItemCard item={item} reviewType={task.reviewType} />,
              }))} />
          )}
        </>
      ) : (
        task.status === 'PROCESSING' && !riskEvents.length && (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin tip="正在启动审查..." />
          </div>
        )
      )}
    </div>
  )
}
