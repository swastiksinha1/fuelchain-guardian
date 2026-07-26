/**
 * useApi — typed React Query hooks for all FuelChain API endpoints.
 * These hydrate the Zustand store on mount and then WebSocket keeps it live.
 */
import { useQuery } from 'react-query'
import {
  fetchVessels,
  fetchAllDisruptions,
  fetchPumpsSummary,
  fetchAllPanicIndices,
  fetchCreditHistory,
} from '../services/api'
import { useStore } from '../store'

export function useVessels() {
  const { addVesselUpdate } = useStore()
  return useQuery('vessels', fetchVessels, {
    refetchInterval: 30_000,
    onSuccess: (data: any) => {
      data.vessels?.forEach((v: any) => addVesselUpdate(v))
    },
  })
}

export function useDisruptions() {
  const { updateDisruption } = useStore()
  return useQuery('disruptions', fetchAllDisruptions, {
    refetchInterval: 30_000,
    onSuccess: (ports: any[]) => {
      ports?.forEach((d: any) => updateDisruption(d))
    },
  })
}

export function usePumps(city?: string) {
  const { addPumpUpdate } = useStore()
  return useQuery(['pumps', city], () => fetchPumpsSummary(city), {
    refetchInterval: 60_000,
    onSuccess: (data: any) => {
      data.pumps?.forEach((p: any) => addPumpUpdate(p))
    },
  })
}

export function usePanic() {
  const { updatePanic } = useStore()
  return useQuery('panic', fetchAllPanicIndices, {
    refetchInterval: 30_000,
    onSuccess: (cities: any[]) => {
      cities?.forEach((p: any) => updatePanic(p))
    },
  })
}

export function useCreditHistory(page = 1) {
  return useQuery(['credit', page], () => fetchCreditHistory(page), {
    keepPreviousData: true,
  })
}
