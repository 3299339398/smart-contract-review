import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Upload, Button, Checkbox, Alert, message, Space, Radio } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import apiClient from '../api/client'
import { REVIEW_TYPE_LABELS, type ReviewType } from '../types/review'

const { Dragger } = Upload

export default function DocumentUploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [msg, setMsg] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null)
  const [startReview, setStartReview] = useState(false)
  const [reviewType, setReviewType] = useState<ReviewType>('FULL')
  const navigate = useNavigate()

  const props: UploadProps = {
    accept: '.pdf,.docx,.doc',
    maxCount: 1,
    beforeUpload: (f) => {
      if (f.size > 20 * 1024 * 1024) {
        message.error('文件大小不能超过 20MB')
        return Upload.LIST_IGNORE
      }
      setFile(f)
      setMsg(null)
      return false // manual upload
    },
    onRemove: () => {
      setFile(null)
      setMsg(null)
    },
  }

  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    setMsg(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const { data: uploadData } = await apiClient.post('/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })

      const docName = uploadData.data.originalFilename
      setMsg({ type: 'success', text: `上传成功: ${docName}` })

      if (startReview) {
        setMsg({ type: 'info', text: '审查已启动，正在跳转...' })
        const { data: reviewData } = await apiClient.post('/reviews', {
          documentId: uploadData.data.documentId,
          reviewType,
        })
        setTimeout(() => navigate(`/review/${reviewData.data.taskId}`), 1000)
      }
    } catch (err: any) {
      setMsg({ type: 'error', text: err.response?.data?.message || '上传失败' })
    } finally {
      setUploading(false)
    }
  }

  return (
    <Card title="上传合同文档" style={{ maxWidth: 640, margin: '0 auto' }}>
      <Dragger {...props} style={{ marginBottom: 16 }}>
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
        <p className="ant-upload-hint">支持 PDF、DOCX 格式，最大 20MB</p>
      </Dragger>

      <div style={{ marginBottom: 16 }}>
        <Checkbox checked={startReview} onChange={e => setStartReview(e.target.checked)}>
          上传后立即启动 AI 审查
        </Checkbox>
        {startReview && (
          <div style={{ marginTop: 8, marginLeft: 24 }}>
            <span style={{ marginRight: 8, color: '#666' }}>审查模式：</span>
            <Radio.Group value={reviewType} onChange={e => setReviewType(e.target.value)}>
              {Object.entries(REVIEW_TYPE_LABELS).map(([key, label]) => (
                <Radio.Button key={key} value={key}>{label}</Radio.Button>
              ))}
            </Radio.Group>
          </div>
        )}
      </div>

      <div>
        <Space>
          <Button type="primary" onClick={handleUpload} disabled={!file} loading={uploading}>
            {uploading ? '上传中...' : '上传文档'}
          </Button>
          {!file && <span style={{ color: '#999' }}>请先选择文件</span>}
        </Space>
      </div>

      {msg && <Alert message={msg.text} type={msg.type} showIcon style={{ marginTop: 16 }} />}
    </Card>
  )
}
