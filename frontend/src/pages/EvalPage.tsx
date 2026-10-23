import { useEffect, useState, useCallback, useRef } from 'react'
import {
  Card, Button, Radio, Switch, Table, Tag, Statistic, Row, Col,
  Progress, Spin, Empty, Typography, Collapse, Space, message,
} from 'antd'
import {
  PlayCircleOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ReloadOutlined, TrophyOutlined, ExperimentOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import apiClient from '../api/client'
import type {
  EvalReportResponse, EvalReportBrief, EvalRunResponse, EvalSseEvent,
} from '../types/eval'

const { Title, Text } = Typography

const RISK_TYPE_LABELS: Record<string, string> = {
  LIABILITY_UNLIMITED: '无限责任',
  MISSING_TERM_DATE: '缺失期限',
  AMBIGUOUS_PAYMENT_TERMS: '付款模糊',
  ONE_SIDED_TERMINATION: '单方解约',
  IP_OWNERSHIP_UNCLEAR: 'IP归属不明',
  CONFIDENTIALITY_WEAK: '保密不足',
  DATA_PRIVACY_VIOLATION: '数据隐私违规',
  DISPUTE_RESOLUTION_VAGUE: '争议解决不明',
  FORCE_MAJEURE_MISSING: '缺失不可抗力',
  GOVERNING_LAW_MISSING: '缺失适用法律',
  AUTO_RENEWAL_TRAP: '自动续约陷阱',
  EXCESSIVE_LIQUIDATED_DAMAGES: '过高违约金',
  NON_COMPETE_OVERBROAD: '竞业限制过宽',
  NONE: '无风险',
}

const LEVEL_COLORS: Record<string, string> = { HIGH: 'red', MEDIUM: 'orange', LOW: 'green' }

export default function EvalPage() {
  const [mode, setMode] = useState<'quick' | 'full'>('quick')
  const [withJudge, setWithJudge] = useState(true)
  const [running, setRunning] = useState(false)
  const [reportId, setReportId] = useState<string | null>(null)
  const [progress, setProgress] = useState({ current: 0, total: 0 })
  const [sseEvents, setSseEvents] = useState<EvalSseEvent[]>([])
  const [report, setReport] = useState<EvalReportResponse | null>(null)
  const [reports, setReports] = useState<EvalReportBrief[]>([])
  const [loadingReports, setLoadingReports] = useState(false)
  const [viewingHistory, setViewingHistory] = useState(false)
  const sseAbortRef = useRef<AbortController | null>(null)

  const fetchReports = useCallback(async () => {
    setLoadingReports(true)
    try {
      const { data } = await apiClient.get('/eval/reports')
      setReports(data.data.content || [])
    } catch { /* ignore */ }
    setLoadingReports(false)
  }, [])

  useEffect(() => { fetchReports() }, [fetchReports])

  const startEval = async () => {
    setRunning(true)
    setReport(null)
    setSseEvents([])
    setProgress({ current: 0, total: 0 })
    try {
      const { data } = await apiClient.post('/eval/run', { mode, withLlmJudge: withJudge })
      const resp: EvalRunResponse = data.data
      setReportId(resp.reportId)
      connectSse(resp.reportId)
    } catch {
      message.error('启动评测失败')
      setRunning(false)
    }
  }

  const connectSse = (rid: string) => {
    sseAbortRef.current?.abort()
    const token = localStorage.getItem('accessToken')
    const controller = new AbortController()
    sseAbortRef.current = controller
    const processEvent = (evt: EvalSseEvent) => {
      setSseEvents(prev => [...prev, evt])
      if (evt.event === 'EVAL_STARTED') {
        setProgress({ current: 0, total: evt.totalCases || 0 })
      } else if (evt.event === 'CASE_COMPLETED' || evt.event === 'CASE_ERROR') {
        setProgress(prev => ({ ...prev, current: evt.caseIndex || 0 }))
      } else if (evt.event === 'EVAL_COMPLETED' && evt.report) {
        setReport(evt.report)
        setRunning(false)
        fetchReports()
      }
    }
    fetch(`/api/v1/eval/reports/${rid}/stream`, {
      signal: controller.signal,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).then(async response => {
      if (!response.ok) throw new Error(`SSE request failed: ${response.status}`)
      const reader = response.body?.getReader()
      if (!reader) throw new Error('SSE stream unavailable')
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          try { processEvent(JSON.parse(line.substring(5).trim())) } catch { /* ignore malformed event */ }
        }
      }
    }).catch(() => {
      if (!controller.signal.aborted) setRunning(false)
    })
  }

  useEffect(() => {
    return () => { sseAbortRef.current?.abort() }
  }, [])

  const loadHistoryReport = async (rid: string) => {
    setViewingHistory(true)
    try {
      const { data } = await apiClient.get(`/eval/reports/${rid}`)
      setReport(data.data)
      setRunning(false)
      setSseEvents([])
    } catch {
      message.error('加载报告失败')
    }
  }

  const formatPct = (v: number) => `${(v * 100).toFixed(1)}%`

  return (
    <div>
      <Title level={4}>
        <ExperimentOutlined style={{ marginRight: 8 }} />
        Agent 评测面板
      </Title>

      {/* 控制面板 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <span style={{ marginRight: 8, color: '#666' }}>模式：</span>
            <Radio.Group value={mode} onChange={e => setMode(e.target.value)} disabled={running}>
              <Radio.Button value="quick">
                <ThunderboltOutlined /> 快速 (仅分类)
              </Radio.Button>
              <Radio.Button value="full">完整 (分类+等级)</Radio.Button>
            </Radio.Group>
          </Col>
          <Col>
            <Switch checked={withJudge} onChange={setWithJudge} disabled={running} />
            <span style={{ marginLeft: 8, color: '#666' }}>LLM-as-Judge</span>
          </Col>
          <Col>
            <Button
              type="primary"
              icon={running ? undefined : <PlayCircleOutlined />}
              onClick={startEval}
              loading={running}
              disabled={running}
            >
              {running ? '评测中...' : '开始评测'}
            </Button>
          </Col>
          <Col>
            <Button icon={<ReloadOutlined />} onClick={fetchReports} loading={loadingReports} size="small">
              刷新历史
            </Button>
          </Col>
        </Row>
      </Card>

      {/* 实时进度 */}
      {running && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Progress
              type="circle"
              percent={progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0}
              size={60}
            />
            <div>
              <Text strong>正在评测... ({progress.current}/{progress.total})</Text>
              <div style={{ marginTop: 4 }}>
                {sseEvents.filter(e => e.event === 'CASE_COMPLETED' || e.event === 'CASE_ERROR').map((e, i) => (
                  <Tag key={i} color={e.event === 'CASE_ERROR' ? 'red' : e.riskTypeMatch ? 'green' : 'orange'} style={{ marginBottom: 4 }}>
                    #{e.caseId} {e.predictedRiskType} {e.event === 'CASE_ERROR' ? '✗' : e.riskTypeMatch ? '✓' : '✗'}
                  </Tag>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* 评测结果 */}
      {report && (
        <>
          {/* 指标卡片 */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={4}>
              <Card size="small">
                <Statistic
                  title="F1 分数"
                  value={report.riskTypeF1}
                  precision={1}
                  suffix="%"
                  formatter={v => (Number(v) * 100).toFixed(1)}
                  valueStyle={{ color: report.riskTypeF1 >= 0.9 ? '#52c41a' : '#faad14', fontSize: 28 }}
                  prefix={<TrophyOutlined />}
                />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card size="small">
                <Statistic
                  title="Precision"
                  value={report.riskTypePrecision}
                  precision={1}
                  suffix="%"
                  formatter={v => (Number(v) * 100).toFixed(1)}
                />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card size="small">
                <Statistic
                  title="Recall"
                  value={report.riskTypeRecall}
                  precision={1}
                  suffix="%"
                  formatter={v => (Number(v) * 100).toFixed(1)}
                />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card size="small">
                <Statistic
                  title="等级准确率"
                  value={report.riskLevelAccuracy}
                  precision={1}
                  suffix="%"
                  formatter={v => (Number(v) * 100).toFixed(1)}
                />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card size="small">
                <Statistic
                  title="LLM-Judge 均分"
                  value={report.avgLlmJudgeScore}
                  precision={2}
                  suffix="/1.00"
                />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card size="small">
                <Statistic
                  title="测试用例"
                  value={report.totalCases}
                  suffix={`个 (${report.mode === 'quick' ? '快速' : '完整'})`}
                />
              </Card>
            </Col>
          </Row>

          {/* 用例明细表格 */}
          <Card title={`评测明细 (报告 #${report.reportId})`} style={{ marginBottom: 16 }}>
            <Table
              dataSource={report.details}
              rowKey="caseId"
              size="small"
              pagination={false}
              columns={[
                { title: '#', dataIndex: 'caseId', width: 48 },
                {
                  title: '描述', dataIndex: 'description', ellipsis: true,
                  render: (t: string) => <Text style={{ fontSize: 13 }}>{t}</Text>,
                },
                {
                  title: '期望', width: 170,
                  render: (_: any, r: any) => (
                    <Space size={4}>
                      <Tag>{RISK_TYPE_LABELS[r.expectedRiskType] || r.expectedRiskType}</Tag>
                      <Tag color={LEVEL_COLORS[r.expectedRiskLevel]}>{r.expectedRiskLevel}</Tag>
                    </Space>
                  ),
                },
                {
                  title: '预测', width: 170,
                  render: (_: any, r: any) => (
                    <Space size={4}>
                      <Tag color={r.riskTypeMatch ? 'green' : 'red'}>
                        {RISK_TYPE_LABELS[r.predictedRiskType] || r.predictedRiskType}
                      </Tag>
                      <Tag color={LEVEL_COLORS[r.predictedRiskLevel]}>{r.predictedRiskLevel}</Tag>
                    </Space>
                  ),
                },
                {
                  title: '类型', width: 60, align: 'center' as const,
                  render: (_: any, r: any) =>
                    r.riskTypeMatch
                      ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                      : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
                },
                {
                  title: '等级', width: 60, align: 'center' as const,
                  render: (_: any, r: any) =>
                    r.riskLevelMatch
                      ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                      : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
                },
                {
                  title: 'Judge', width: 70, align: 'center' as const,
                  render: (_: any, r: any) =>
                    r.llmJudgeScore != null ? (
                      <Tag color={r.llmJudgeScore >= 0.8 ? 'green' : r.llmJudgeScore >= 0.5 ? 'orange' : 'red'}>
                        {r.llmJudgeScore.toFixed(2)}
                      </Tag>
                    ) : <Text type="secondary">-</Text>,
                },
              ]}
              expandable={{
                expandedRowRender: (r) => (
                  <div style={{ padding: '0 24px 12px' }}>
                    {r.predictedReasoning && (
                      <div style={{ marginBottom: 8 }}>
                        <Text type="secondary">AI 推理：</Text>
                        <Text style={{ fontSize: 13 }}>{r.predictedReasoning}</Text>
                      </div>
                    )}
                    {r.llmJudgeReasoning && (
                      <div>
                        <Text type="secondary">Judge 评语：</Text>
                        <Text style={{ fontSize: 13, fontStyle: 'italic' }}>{r.llmJudgeReasoning}</Text>
                      </div>
                    )}
                  </div>
                ),
                rowExpandable: (r) => !!(r.predictedReasoning || r.llmJudgeReasoning),
              }}
            />
          </Card>
        </>
      )}

      {/* 空状态 */}
      {!running && !report && (
        <Card>
          <Empty description="点击「开始评测」运行自动化测试">
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={startEval}>
              开始评测
            </Button>
          </Empty>
        </Card>
      )}

      {/* 历史报告 */}
      <Card title="历史报告" size="small" style={{ marginTop: 16 }}>
        {reports.length === 0 ? (
          <Empty description="暂无历史评测报告" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table
            dataSource={reports}
            rowKey="reportId"
            size="small"
            pagination={false}
            columns={[
              { title: '报告 ID', dataIndex: 'reportId', width: 100 },
              {
                title: '模式', dataIndex: 'mode', width: 80,
                render: (m: string) => <Tag>{m === 'quick' ? '快速' : '完整'}</Tag>,
              },
              { title: '用例数', dataIndex: 'totalCases', width: 70 },
              {
                title: 'F1', dataIndex: 'riskTypeF1', width: 80,
                render: (v: number) => (
                  <Text strong style={{ color: v >= 0.9 ? '#52c41a' : '#faad14' }}>
                    {formatPct(v)}
                  </Text>
                ),
              },
              {
                title: 'Judge均分', dataIndex: 'avgLlmJudgeScore', width: 100,
                render: (v: number) => v?.toFixed(2) || '-',
              },
              {
                title: '时间', dataIndex: 'createdAt', ellipsis: true,
                render: (t: string) => new Date(t).toLocaleString(),
              },
              {
                title: '操作', width: 80,
                render: (_: any, r: EvalReportBrief) => (
                  <Button size="small" onClick={() => loadHistoryReport(r.reportId)}>查看</Button>
                ),
              },
            ]}
          />
        )}
      </Card>
    </div>
  )
}
