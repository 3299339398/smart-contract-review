import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { Card, Input, Button, Space, Spin, Tag, Typography, Empty, List } from 'antd'
import { SendOutlined, UserOutlined, RobotOutlined, HistoryOutlined, PlusOutlined } from '@ant-design/icons'
import apiClient from '../api/client'

const { Text } = Typography

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: { clauseIndex: number; text: string }[]
}

interface HistoryItem {
  consultId: number
  question: string
  answer: string
  sourceClauses?: { clauseIndex: number; text: string }[]
  citationWarnings?: string[]
  createdAt: string
}

export default function ConsultationPage() {
  const { documentId } = useParams<{ documentId: string }>()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const mountedRef = useRef(true)
  const listRef = useRef<HTMLDivElement>(null)

  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const params: Record<string, number> = { page: 1, size: 50 }
      if (documentId) params.documentId = parseInt(documentId)
      const { data } = await apiClient.get('/consultations', { params })
      setHistory(data.data.content || [])
    } catch { /* ignore */ }
    setHistoryLoading(false)
  }, [documentId])

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  const handleSend = async () => {
    if (!input.trim()) return
    const question = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: question }])
    setLoading(true)
    setSelectedId(null)

    try {
      const { data } = await apiClient.post('/consultations', {
        documentId: documentId ? parseInt(documentId) : null,
        question,
      })
      if (!mountedRef.current) return
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.data.answer,
        sources: data.data.sourceClauses,
      }])
      fetchHistory()
    } catch {
      if (!mountedRef.current) return
      setMessages(prev => [...prev, { role: 'assistant', content: '抱歉，AI 服务暂时不可用，请稍后重试。' }])
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }

  const handleSelectHistory = (item: HistoryItem) => {
    setSelectedId(item.consultId)
    setMessages([
      { role: 'user', content: item.question },
      { role: 'assistant', content: item.answer, sources: item.sourceClauses },
    ])
  }

  const handleNewChat = () => {
    setMessages([])
    setSelectedId(null)
  }

  return (
    <div style={{ display: 'flex', gap: 16, maxWidth: 1200, margin: '0 auto' }}>
      {/* 对话历史侧边栏 */}
      <Card
        title={<><HistoryOutlined /> 对话历史</>}
        size="small"
        style={{ width: sidebarOpen ? 320 : 56, flexShrink: 0, transition: 'width 0.25s' }}
        bodyStyle={{ padding: sidebarOpen ? 12 : 8 }}
        extra={
          <Space size={4}>
            {sidebarOpen && (
              <Button type="text" size="small" icon={<PlusOutlined />} onClick={handleNewChat}
                style={{ fontSize: 12 }}>新建</Button>
            )}
            <Button type="link" size="small" onClick={() => setSidebarOpen(!sidebarOpen)}
              style={{ fontSize: 12, padding: 0 }}>
              {sidebarOpen ? '收起' : '展开'}
            </Button>
          </Space>
        }
      >
        {sidebarOpen ? (
          historyLoading ? (
            <div style={{ textAlign: 'center', padding: 20 }}><Spin /></div>
          ) : history.length === 0 ? (
            <Empty description="暂无对话记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <List
              dataSource={history}
              renderItem={(item) => (
                <List.Item
                  onClick={() => handleSelectHistory(item)}
                  style={{
                    cursor: 'pointer',
                    padding: '8px 10px',
                    borderRadius: 6,
                    background: selectedId === item.consultId ? '#e6f4ff' : 'transparent',
                    marginBottom: 2,
                    border: 'none',
                  }}
                >
                  <div style={{ width: '100%', overflow: 'hidden' }}>
                    <Text ellipsis style={{ fontSize: 13, fontWeight: selectedId === item.consultId ? 600 : 400 }}>
                      {item.question}
                    </Text>
                    <div style={{ fontSize: 11, color: '#999', marginTop: 3 }}>
                      {new Date(item.createdAt).toLocaleString('zh-CN')}
                    </div>
                  </div>
                </List.Item>
              )}
              style={{ maxHeight: '60vh', overflow: 'auto' }}
            />
          )
        ) : (
          <Button type="text" icon={<HistoryOutlined />} onClick={() => setSidebarOpen(true)}
            style={{ width: '100%', fontSize: 12 }} />
        )}
      </Card>

      {/* 对话区 */}
      <Card title="AI 合同咨询" style={{ flex: 1 }}
        extra={<Text type="secondary">针对已上传的合同文档进行智能问答</Text>}>
        <div ref={listRef}
          style={{ minHeight: 400, maxHeight: '60vh', overflow: 'auto', marginBottom: 16, padding: 8 }}>
          {messages.length === 0 && (
            <Empty description='输入您对合同的问题，例如："第4条的违约责任是否存在法律风险？"' style={{ marginTop: 80 }} />
          )}
          {messages.map((msg, i) => (
            <div key={i} style={{ marginBottom: 16, display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
              <div style={{
                maxWidth: '80%', padding: '10px 16px', borderRadius: 12,
                background: msg.role === 'user' ? '#1677ff' : '#f5f5f5',
                color: msg.role === 'user' ? '#fff' : '#333',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  {msg.role === 'user'
                    ? <><span style={{ fontSize: 12, opacity: 0.8 }}>你</span><UserOutlined style={{ fontSize: 12 }} /></>
                    : <><RobotOutlined style={{ fontSize: 12 }} /><span style={{ fontSize: 12, opacity: 0.7 }}>AI</span></>
                  }
                </div>
                <p style={{ margin: 0, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{msg.content}</p>
                {msg.sources && msg.sources.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>引用: </Text>
                    {msg.sources.map((s, j) => <Tag key={j} style={{ fontSize: 11 }}>条款{s.clauseIndex}</Tag>)}
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: 16 }}>
              <div style={{ background: '#f5f5f5', borderRadius: 12, padding: '10px 16px' }}>
                <Spin size="small" /> <Text type="secondary">AI 正在分析...</Text>
              </div>
            </div>
          )}
        </div>

        <Space.Compact style={{ width: '100%' }}>
          <Input value={input} onChange={e => setInput(e.target.value)}
            onPressEnter={handleSend}
            placeholder="输入问题..."
            size="large" />
          <Button type="primary" icon={<SendOutlined />} onClick={handleSend}
            loading={loading} disabled={!input.trim()} size="large">
            发送
          </Button>
        </Space.Compact>
      </Card>
    </div>
  )
}
