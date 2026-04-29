import { create } from 'zustand'

export type DashboardTab = 'pl' | 'sp' | 'cf' | 'ratios' | 'validation'
export type ProjectionYear = 'Y1' | 'Y2' | 'Y3'

interface DashboardState {
  activeTab: DashboardTab
  selectedYear: ProjectionYear
  isModelDirty: boolean
  isRunning: boolean
  lastRunAt: string | null

  setActiveTab: (tab: DashboardTab) => void
  setSelectedYear: (year: ProjectionYear) => void
  markDirty: () => void
  markClean: (lastRunAt?: string) => void
  setRunning: (running: boolean) => void
}

export const useDashboardStore = create<DashboardState>((set) => ({
  activeTab: 'pl',
  selectedYear: 'Y3',
  isModelDirty: false,
  isRunning: false,
  lastRunAt: null,

  setActiveTab: (activeTab) => set({ activeTab }),
  setSelectedYear: (selectedYear) => set({ selectedYear }),
  markDirty: () => set({ isModelDirty: true }),
  markClean: (lastRunAt) =>
    set({
      isModelDirty: false,
      lastRunAt: lastRunAt ?? new Date().toISOString(),
    }),
  setRunning: (isRunning) => set({ isRunning }),
}))
