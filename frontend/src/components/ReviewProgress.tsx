import { Progress } from 'antd'

interface Props {
  reviewed: number
  total: number
}

export default function ReviewProgress({ reviewed, total }: Props) {
  if (total === 0) return null
  const pct = Math.round((reviewed / total) * 100)
  return <Progress percent={pct} format={() => `${reviewed}/${total} 条款`} status={pct === 100 ? 'success' : 'active'} />
}
