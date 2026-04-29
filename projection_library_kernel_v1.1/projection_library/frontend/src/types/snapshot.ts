export interface SnapshotValue {
  voice_id: string
  year: string
  value: number | null
  base_value: number | null
  override_delta: number
}

export interface ValidationSummaryCounts {
  block: number
  error: number
  warning: number
  info: number
}

export interface SnapshotSummary {
  id: string
  project_id: string
  run_timestamp: string
  status: string
  duration_ms: number
  error_message: string | null
  validation_summary: Partial<ValidationSummaryCounts> & Record<string, unknown>
  approximation_log: unknown[]
  created_at: string
}

export interface SnapshotDetail extends SnapshotSummary {
  validation_issues: unknown[]
  pl_data: Record<string, unknown>
  sp_data: Record<string, unknown>
  cf_data: Record<string, unknown>
  projected_kpis: Record<string, unknown>
  values: SnapshotValue[]
}
