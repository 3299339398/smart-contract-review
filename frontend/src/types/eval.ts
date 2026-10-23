export interface EvalCaseDetail {
  caseId: number
  description: string
  expectedRiskType: string
  expectedRiskLevel: string
  predictedRiskType: string
  predictedRiskLevel: string
  riskTypeMatch: boolean
  riskLevelMatch: boolean
  llmJudgeScore: number | null
  llmJudgeReasoning: string | null
  predictedReasoning: string | null
}

export interface EvalReportResponse {
  reportId: string
  mode: string
  totalCases: number
  riskTypePrecision: number
  riskTypeRecall: number
  riskTypeF1: number
  riskLevelAccuracy: number
  avgLlmJudgeScore: number
  details: EvalCaseDetail[]
  createdAt: string
}

export interface EvalReportBrief {
  reportId: string
  mode: string
  totalCases: number
  riskTypeF1: number
  avgLlmJudgeScore: number
  createdAt: string
}

export interface EvalRunResponse {
  reportId: string
  status: 'running' | 'completed' | 'failed'
}

export interface EvalSseEvent {
  event: string
  caseIndex?: number
  totalCases?: number
  caseId?: number
  description?: string
  riskTypeMatch?: boolean
  riskLevelMatch?: boolean
  predictedRiskType?: string
  predictedRiskLevel?: string
  elapsed?: number
  error?: string
  report?: EvalReportResponse
  mode?: string
}
