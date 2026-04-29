export type OverrideNature = 'organic' | 'one_shot' | (string & {})

export interface Override {
  id: string
  project_id: string
  voice_id: string
  year: string
  delta_amount: number
  nature: OverrideNature
  override_policy_class: string
  is_active: boolean
  user_note: string | null
  created_at: string
  deactivated_at: string | null
}

export interface OverrideList {
  project_id: string
  count: number
  items: Override[]
}

export interface OverrideCreatePayload {
  voice_id: string
  year: string
  delta_amount: number
  nature: OverrideNature
  user_note?: string | null
}
