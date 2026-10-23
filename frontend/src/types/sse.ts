export interface SseEvent {
  eventType: string
  taskId: number
  timestamp: string
}

export interface RiskFoundSseEvent extends SseEvent {
  clauseIndex: number
  riskType: string
  riskLevel: string
  riskDescription: string
  suggestedAmendment: string
  legalBasis: string
}
