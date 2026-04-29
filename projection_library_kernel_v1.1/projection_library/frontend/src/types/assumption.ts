export type AssumptionYear = 'Y1' | 'Y2' | 'Y3'

export type AssumptionSource = 'default_kpi' | 'user_input' | 'fallback'

export type AssumptionValidationStatus =
  | 'ok'
  | 'warning_range'
  | 'warning_continuity'

export type AssumptionCurveType = 'flat' | 'linear_drift' | 'custom'

export interface AssumptionRow {
  voice_id: string
  method_id: string
  assumption_name: string
  values: Partial<Record<AssumptionYear, number>>
  source: AssumptionSource
  default_kpi_id: string | null
  calibration_score: number | null
  validation_status: AssumptionValidationStatus
  validation_range: [number, number] | null
  curve_type: AssumptionCurveType
  user_modified_at: string | null
}

export interface AssumptionList {
  project_id: string
  count: number
  items: AssumptionRow[]
}

export interface PopulateReport {
  populated: number
  kpi_default_used: number
  fallback_used: number
  user_input_preserved: number
  pairs_deleted: number
  methods_skipped: string[]
}

export interface AssumptionPatchPayload {
  voice_id: string
  assumption_name: string
  year: AssumptionYear
  value: number
}

export interface AssumptionCurvePayload {
  voice_id: string
  assumption_name: string
  curve_type: AssumptionCurveType
  y1?: number
  y3?: number
}
