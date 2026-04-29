export type Severity = 'block' | 'error' | 'warning' | 'info'

export interface ValidationIssue {
  rule_id: string
  severity: Severity
  voice_id: string | null
  year: string | null
  message: string
  context: Record<string, unknown>
}

export interface ValidationSummary {
  block: number
  error: number
  warning: number
  info: number
}

export interface HistoricalValidationReport {
  project_id: string
  phase: 'historical'
  summary: ValidationSummary
  issues: ValidationIssue[]
  can_proceed: boolean
  computed_at: string
}

export interface LatestValidationReport {
  project_id: string
  snapshot_id: string
  run_timestamp: string
  status: string
  summary: Partial<ValidationSummary> & Record<string, unknown>
  issues: ValidationIssue[]
}
