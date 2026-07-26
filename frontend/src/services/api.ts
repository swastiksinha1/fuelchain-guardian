/**
 * API service — typed wrappers around the FuelChain REST API.
 */
import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const api = axios.create({ baseURL: BASE })

// ── Auth ──────────────────────────────────────────────────────────────────

export async function login(email: string, password: string) {
  const form = new FormData()
  form.append('username', email)
  form.append('password', password)
  const { data } = await api.post('/api/v1/auth/token', form)
  api.defaults.headers.common['Authorization'] = `Bearer ${data.access_token}`
  return data
}

// ── Vessels ───────────────────────────────────────────────────────────────

export async function fetchVessels() {
  const { data } = await api.get('/api/v1/vessels')
  return data
}

export async function fetchVesselDetail(mmsi: string) {
  const { data } = await api.get(`/api/v1/vessels/${mmsi}`)
  return data
}

// ── Disruption ────────────────────────────────────────────────────────────

export async function fetchAllDisruptions() {
  const { data } = await api.get('/api/v1/disruption')
  return data.ports as { port_code: string; disruption_index: number }[]
}

export async function fetchDisruption(portCode: string) {
  const { data } = await api.get(`/api/v1/disruption/${portCode}`)
  return data
}

// ── Pumps ─────────────────────────────────────────────────────────────────

export async function fetchPumpsNearby(lat: number, lon: number, radius = 50000) {
  const { data } = await api.get('/api/v1/pumps/nearby', {
    params: { lat, lon, radius },
  })
  return data
}

export async function fetchPumpsSummary(city?: string, status?: string) {
  const { data } = await api.get('/api/v1/pumps', { params: { city, status } })
  return data
}

// ── Panic ─────────────────────────────────────────────────────────────────

export async function fetchAllPanicIndices() {
  const { data } = await api.get('/api/v1/panic')
  return data.cities as { city: string; panic_index: number }[]
}

export async function fetchPanicCity(city: string) {
  const { data } = await api.get(`/api/v1/panic/${city}`)
  return data
}

// ── Credit ────────────────────────────────────────────────────────────────

export async function fetchCreditHistory(page = 1) {
  const { data } = await api.get('/api/v1/credit/history', { params: { page } })
  return data
}

export async function fetchCreditStatus(loanId: string) {
  const { data } = await api.get(`/api/v1/credit/status/${loanId}`)
  return data
}
