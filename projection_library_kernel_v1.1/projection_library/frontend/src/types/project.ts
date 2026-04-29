export interface Project {
  id: string
  name: string
  company_name: string | null
  sector_pack: string
  perimeter: string | null
  currency: string
  country: string | null
  accounting_standard: string
  horizon_years: number
  tier_level: string | null
  etr_default: number | null
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface ProjectList {
  count: number
  items: Project[]
}
