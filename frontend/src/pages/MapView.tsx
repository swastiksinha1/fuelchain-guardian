/**
 * Live Map — shows tanker positions and pump status markers.
 * Uses react-map-gl with MapLibre GL (no API key required for base map).
 */
import React, { useCallback, useEffect, useState } from 'react'
import Map, { Marker, Popup, NavigationControl, Source, Layer } from 'react-map-gl/maplibre'
import { useStore, type Vessel, type Pump } from '../store'
import { fetchVessels, fetchPumpsSummary } from '../services/api'
import { useQuery } from 'react-query'
import { Ship, MapPin, AlertTriangle, Clock } from 'lucide-react'
import 'maplibre-gl/dist/maplibre-gl.css'

// Free OSM-based dark style (no API key)
const MAP_STYLE = 'https://tiles.openfreemap.org/styles/dark'

function vesselColor(vessel: Vessel): string {
  if (vessel.status === 'anomaly') return '#ef4444'
  if (vessel.status === 'delayed') return '#f97316'
  return '#22c55e'
}

function pumpColor(pump: Pump): string {
  if (pump.status === 'RED') return '#ef4444'
  if (pump.status === 'YELLOW') return '#eab308'
  return '#22c55e'
}

function PumpMarkerIcon({ status }: { status: string }) {
  const color = status === 'RED' ? 'bg-red-500' : status === 'YELLOW' ? 'bg-yellow-500' : 'bg-green-500'
  return (
    <div className={`w-3 h-3 rounded-full ${color} border-2 border-white shadow-lg cursor-pointer`} />
  )
}

export function MapView() {
  const { vessels, pumps, anomalies, addVesselUpdate, addPumpUpdate } = useStore()
  const [selectedVessel, setSelectedVessel] = useState<Vessel | null>(null)
  const [selectedPump, setSelectedPump] = useState<Pump | null>(null)
  const [showPumps, setShowPumps] = useState(true)
  const [showVessels, setShowVessels] = useState(true)

  // Initial data fetch
  useQuery('vessels', fetchVessels, {
    refetchInterval: 30000,
    onSuccess: (data) => {
      data.vessels?.forEach((v: Vessel) => addVesselUpdate(v))
    },
  })

  useQuery('pumps', () => fetchPumpsSummary(), {
    refetchInterval: 60000,
    onSuccess: (data) => {
      data.pumps?.forEach((p: Pump) => addPumpUpdate(p))
    },
  })

  const vesselList = Object.values(vessels)
  const pumpList = Object.values(pumps)

  const redPumps = pumpList.filter(p => p.status === 'RED').length
  const delayedVessels = vesselList.filter(v => v.status === 'delayed' || v.status === 'anomaly').length

  return (
    <div className="relative w-full h-full">
      {/* Map */}
      <Map
        initialViewState={{
          longitude: 70.0,
          latitude: 20.0,
          zoom: 4.5,
        }}
        style={{ width: '100%', height: '100%' }}
        mapStyle={MAP_STYLE}
        onClick={() => { setSelectedVessel(null); setSelectedPump(null) }}
      >
        <NavigationControl position="top-right" />

        {/* Vessel markers */}
        {showVessels && vesselList.map((vessel) => (
          <Marker
            key={vessel.mmsi}
            longitude={vessel.lon}
            latitude={vessel.lat}
            onClick={(e) => { e.originalEvent.stopPropagation(); setSelectedVessel(vessel); setSelectedPump(null) }}
          >
            <div
              className="cursor-pointer transition-transform hover:scale-125"
              title={vessel.vessel_name}
            >
              <Ship
                size={20}
                style={{
                  color: vesselColor(vessel),
                  transform: `rotate(${vessel.cog || 0}deg)`,
                  filter: 'drop-shadow(0 0 4px rgba(0,0,0,0.8))',
                }}
              />
            </div>
          </Marker>
        ))}

        {/* Pump markers */}
        {showPumps && pumpList.map((pump) => (
          <Marker
            key={pump.id}
            longitude={pump.lon}
            latitude={pump.lat}
            onClick={(e) => { e.originalEvent.stopPropagation(); setSelectedPump(pump); setSelectedVessel(null) }}
          >
            <PumpMarkerIcon status={pump.status} />
          </Marker>
        ))}

        {/* Vessel popup */}
        {selectedVessel && (
          <Popup
            longitude={selectedVessel.lon}
            latitude={selectedVessel.lat}
            onClose={() => setSelectedVessel(null)}
            closeButton
            className="font-sans"
          >
            <div className="p-2 min-w-48">
              <div className="flex items-center gap-2 mb-2">
                <Ship size={16} className="text-blue-400" />
                <h3 className="font-bold text-sm">{selectedVessel.vessel_name || selectedVessel.mmsi}</h3>
              </div>
              <div className="space-y-1 text-xs text-gray-600">
                <div>MMSI: {selectedVessel.mmsi}</div>
                <div>Speed: {selectedVessel.sog} kn</div>
                <div>Destination: {selectedVessel.destination}</div>
                {selectedVessel.estimated_delay_hours && (
                  <div className="text-orange-600 font-medium flex items-center gap-1">
                    <Clock size={12} />
                    Delay: ~{selectedVessel.estimated_delay_hours}h
                  </div>
                )}
                <div className={`font-medium ${
                  selectedVessel.status === 'anomaly' ? 'text-red-600'
                  : selectedVessel.status === 'delayed' ? 'text-orange-500'
                  : 'text-green-600'
                }`}>
                  {selectedVessel.status?.toUpperCase() || 'TRACKING'}
                </div>
              </div>
            </div>
          </Popup>
        )}

        {/* Pump popup */}
        {selectedPump && (
          <Popup
            longitude={selectedPump.lon}
            latitude={selectedPump.lat}
            onClose={() => setSelectedPump(null)}
            closeButton
          >
            <div className="p-2 min-w-52">
              <div className="flex items-center gap-2 mb-2">
                <MapPin size={16} className="text-orange-400" />
                <h3 className="font-bold text-sm">{selectedPump.name}</h3>
              </div>
              <div className="space-y-1 text-xs text-gray-600">
                <div>{selectedPump.city}, {(selectedPump as any).state}</div>
                <div className="grid grid-cols-2 gap-2 mt-2">
                  <div>
                    <div className="text-gray-400">Petrol</div>
                    <div className="font-bold text-sm">{selectedPump.petrol_pct?.toFixed(0)}%</div>
                    {selectedPump.hours_to_empty_petrol && (
                      <div className="text-xs text-orange-500">{selectedPump.hours_to_empty_petrol}h left</div>
                    )}
                  </div>
                  <div>
                    <div className="text-gray-400">Diesel</div>
                    <div className="font-bold text-sm">{selectedPump.diesel_pct?.toFixed(0)}%</div>
                    {selectedPump.hours_to_empty_diesel && (
                      <div className="text-xs text-orange-500">{selectedPump.hours_to_empty_diesel}h left</div>
                    )}
                  </div>
                </div>
                {selectedPump.panic_multiplier > 1.2 && (
                  <div className="text-red-500 text-xs font-medium flex items-center gap-1 mt-1">
                    <AlertTriangle size={10} /> Panic demand ×{selectedPump.panic_multiplier.toFixed(1)}
                  </div>
                )}
              </div>
            </div>
          </Popup>
        )}
      </Map>

      {/* Layer toggles */}
      <div className="absolute top-4 left-4 flex flex-col gap-2">
        <button
          onClick={() => setShowVessels(v => !v)}
          className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            showVessels ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-300'
          }`}
        >
          🚢 Tankers ({vesselList.length})
        </button>
        <button
          onClick={() => setShowPumps(v => !v)}
          className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            showPumps ? 'bg-orange-600 text-white' : 'bg-slate-700 text-slate-300'
          }`}
        >
          ⛽ Pumps ({pumpList.length})
        </button>
      </div>

      {/* Alert badges */}
      <div className="absolute bottom-6 left-4 flex gap-3">
        {delayedVessels > 0 && (
          <div className="bg-orange-500/90 text-white text-xs px-3 py-1.5 rounded-full font-medium shadow-lg">
            ⚠ {delayedVessels} tanker{delayedVessels > 1 ? 's' : ''} delayed
          </div>
        )}
        {redPumps > 0 && (
          <div className="bg-red-500/90 text-white text-xs px-3 py-1.5 rounded-full font-medium shadow-lg">
            🔴 {redPumps} pump{redPumps > 1 ? 's' : ''} critical
          </div>
        )}
        {anomalies.length > 0 && (
          <div className="bg-red-700/90 text-white text-xs px-3 py-1.5 rounded-full font-medium shadow-lg">
            🚨 {anomalies.length} anomal{anomalies.length > 1 ? 'ies' : 'y'} detected
          </div>
        )}
      </div>
    </div>
  )
}
