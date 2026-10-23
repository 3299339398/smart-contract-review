import { Card, Typography, Tag } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'
import type { RiskItemDto, ReviewType } from '../types/review'

const { Text } = Typography

interface Props {
  item: RiskItemDto
  reviewType?: ReviewType
}

export default function RiskItemCard({ item, reviewType }: Props) {
  return (
    <div>
      {item.clauseText && (
        <Card size="small" style={{ marginBottom: 8, background: '#fafafa' }}>
          <Text type="secondary">条款内容：</Text>
          <Text>{item.clauseText.substring(0, 500)}</Text>
        </Card>
      )}

      <p><Text strong>风险描述：</Text>{item.riskDescription}</p>

      {reviewType === 'RISK_ONLY' ? (
        item.suggestedAmendment && (
          <Card size="small" style={{ background: '#fff7e6', border: '1px solid #ffd591' }}>
            <p style={{ marginBottom: 4 }}>
              <ThunderboltOutlined style={{ color: '#fa8c16', marginRight: 4 }} />
              <Text strong>快速修改建议：</Text>
              <Tag color="orange" style={{ marginLeft: 8 }}>仅查风险</Tag>
            </p>
            <p style={{ marginTop: 4, fontStyle: 'italic', color: '#333' }}>{item.suggestedAmendment}</p>
            {!item.legalBasis && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                此模式下未执行法规检索与合规比对，建议在"全面审查"模式下重新审查以获取法律依据。
              </Text>
            )}
          </Card>
        )
      ) : (
        <>
          {item.legalBasis && (
            <Card size="small" style={{ marginBottom: 8, background: '#fffbe6', border: '1px solid #ffe58f' }}>
              <Text strong>法律依据：</Text>{item.legalBasis}
            </Card>
          )}

          {item.suggestedAmendment && (
            <Card size="small" style={{ background: '#f6ffed', border: '1px solid #b7eb8f' }}>
              <Text strong>修改建议：</Text>
              <p style={{ marginTop: 4, fontStyle: 'italic', color: '#333' }}>{item.suggestedAmendment}</p>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
