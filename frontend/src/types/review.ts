export type ReviewType = 'FULL' | 'RISK_ONLY'

export const REVIEW_TYPE_LABELS: Record<ReviewType, string> = {
  FULL: '全面审查',
  RISK_ONLY: '仅查风险',
}

export interface ReviewCreateRequest {
  documentId: number
  reviewType: ReviewType
}

export interface ReviewTaskResponse {
  taskId: number
  documentId: number
  documentName: string
  reviewType: ReviewType
  status: string
  totalClauses: number
  reviewedClauses: number
  riskCountHigh: number
  riskCountMedium: number
  riskCountLow: number
  startedAt: string
  completedAt: string
  createdAt: string
}

export interface RiskItemDto {
  clauseIndex: number
  clauseText: string
  riskType: string
  riskLevel: string
  riskDescription: string
  suggestedAmendment: string
  legalBasis: string
}

export interface ReviewResultResponse {
  taskId: number
  overallScore: number
  summary: string
  recommendations: string[]
  riskItems: RiskItemDto[]
}
