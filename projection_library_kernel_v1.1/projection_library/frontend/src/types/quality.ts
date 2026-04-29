export interface QualityScore {
  project_id: string
  score_total: number
  score_history: number
  score_completeness: number
  score_consistency: number
  score_method_calibration: number | null
  classification: string
  weights: Record<string, number>
  components_detail: Record<string, unknown>
  computed_at: string
}
