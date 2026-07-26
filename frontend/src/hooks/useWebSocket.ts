/**
 * useWebSocket — connects to the WS gateway and dispatches events
 * to the Zustand store.
 */
import { useEffect, useRef } from 'react'
import { useStore } from '../store'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8002'
const RECONNECT_DELAY = 3000

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()
  const {
    addVesselUpdate,
    addPumpUpdate,
    addAnomaly,
    updateDisruption,
    updatePanic,
    addAlert,
  } = useStore()

  function connect() {
    const ws = new WebSocket(`${WS_URL}/ws`)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[WS] Connected to FuelChain Gateway')
      // Keep-alive ping every 30s
      const ping = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 30000)
      ws.addEventListener('close', () => clearInterval(ping))
    }

    ws.onmessage = (event) => {
      try {
        const envelope = JSON.parse(event.data)
        if (envelope.data === 'pong') return

        switch (envelope.type) {
          case 'vessel_update':
            addVesselUpdate(envelope.data)
            break
          case 'pump_update':
            addPumpUpdate(envelope.data)
            break
          case 'anomaly_alert':
            addAnomaly(envelope.data)
            break
          case 'disruption_update':
            updateDisruption(envelope.data)
            break
          case 'panic_update':
            updatePanic(envelope.data)
            break
          case 'reassurance_alert':
            addAlert(envelope.data)
            break
        }
      } catch (e) {
        console.warn('[WS] Failed to parse message', e)
      }
    }

    ws.onerror = (e) => console.error('[WS] Error', e)

    ws.onclose = () => {
      console.log('[WS] Disconnected, reconnecting...')
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY)
    }
  }

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [])

  return { connected: wsRef.current?.readyState === WebSocket.OPEN }
}
