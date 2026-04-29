export type VoiceStatement = 'PL' | 'SP' | 'CF' | string

export interface Voice {
  voice_id: string
  statement: VoiceStatement
  section: string
  nature: string
  sign: string
  default_method: string | null
  calc_phase_proxy: string | null
  calc_phase_final: string | null
  denominator_flow_voice: string | null
  recurrence: string
  note: string | null
  override_policy_class: string | null
}

export interface VoiceList {
  count: number
  items: Voice[]
}
