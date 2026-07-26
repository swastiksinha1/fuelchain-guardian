/**
 * Global Zustand store for FuelChain Guardian dashboard.
 * Receives live updates from the WebSocket hook.
 */
import { create } from 'zustand'

export interface Vessel {
  mmsi: string
  vessel_name: string
  lat: number
  lon: number
  sog: number
  cog: number
  destination: string
  status?: 'on_time' | 'delayed' | 'anomaly'
  estimated_delay_hours?: number
  updated_at: string
}

export interface Pump {
  id: string
  name: string
  city: string
  lat: number
  lon: number
  status: 'GREEN' | 'YELLOW' | 'RED'
  petrol_pct: number
  diesel_pct: number
  hours_to_empty_petrol?: number
  hours_to_empty_diesel?: number
  panic_multiplier: number
  updated_at: string
}

export interface Anomaly {
  event_id: string
  mmsi: string
  event_type: string
  detected_at: string
  lat: number
  lon: number
  estimated_delay_hours?: number
  destination_port: string
  vessel_name: string
}

export interface DisruptionData {
  port_code: string
  disruption_index: number
  delayed_tonnage: number
  computed_at: string
}

export interface PanicData {
  city: string
  panic_index: number
  updated_at: string
}

export interface Alert {
  city: string
  panic_index: number
  message: string
  issued_at: string
}

interface StoreState {
  // Live data
  vessels: Record<string, Vessel>
  pumps: Record<string, Pump>
  anomalies: Anomaly[]
  disruptions: Record<string, DisruptionData>
  panicData: Record<string, PanicData>
  alerts: Alert[]

  // UI state
  selectedMmsi: string | null
  selectedPumpId: string | null

  // Actions
  addVesselUpdate: (v: Vessel) => void
  addPumpUpdate: (p: Pump) => void
  addAnomaly: (a: Anomaly) => void
  updateDisruption: (d: DisruptionData) => void
  updatePanic: (p: PanicData) => void
  addAlert: (a: Alert) => void
  setSelectedVessel: (mmsi: string | null) => void
  setSelectedPump: (id: string | null) => void
}

export const useStore = create<StoreState>((set) => ({
  vessels: {},
  pumps: {},
  anomalies: [],
  disruptions: {},
  panicData: {},
  alerts: [],
  selectedMmsi: null,
  selectedPumpId: null,

  addVesselUpdate: (v) =>
    set((state) => ({
      vessels: { ...state.vessels, [v.mmsi]: { ...state.vessels[v.mmsi], ...v } },
    })),

  addPumpUpdate: (p) =>
    set((state) => ({
      pumps: { ...state.pumps, [p.id]: { ...state.pumps[p.id], ...p } },
    })),

  addAnomaly: (a) =>
    set((state) => ({
      anomalies: [a, ...state.anomalies.slice(0, 99)], // keep last 100
    })),

  updateDisruption: (d) =>
    set((state) => ({
      disruptions: { ...state.disruptions, [d.port_code]: d },
    })),

  updatePanic: (p) =>
    set((state) => ({
      panicData: { ...state.panicData, [p.city]: p },
    })),

  addAlert: (a) =>
    set((state) => ({
      alerts: [a, ...state.alerts.slice(0, 19)],
    })),

  setSelectedVessel: (mmsi) => set({ selectedMmsi: mmsi }),
  setSelectedPump: (id) => set({ selectedPumpId: id }),
}))
