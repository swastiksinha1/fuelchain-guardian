/**
 * Alerts Feed — real-time anomaly and reassurance alerts.
 */
import React from 'react'
import { useStore } from '../store'
import { Bell, AlertTriangle, CheckCircle, Shield } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

export function AlertsFeed() {
  const { anomalies, alerts } = useStore()

  return (
    <div className="h-full overflow-y-auto p-6 bg-slate-950">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <Bell size={22} className="text-orange-400" />
          <h1 className="text-xl font-bold text-white">Alerts & Notifications</h1>
        </div>

        <div className="grid lg:grid-cols-2 gap-6">
          {/* Tanker Anomalies */}
          <div>
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
              <AlertTriangle size={14} className="text-orange-400" />
              Tanker Anomalies ({anomalies.length})
            </h2>
            <div className="space-y-3">
              {anomalies.length === 0 ? (
                <div className="bg-slate-800 rounded-xl p-6 text-center text-slate-500 text-sm border border-slate-700">
                  <CheckCircle size={24} className="mx-auto mb-2 text-green-500/50" />
                  No anomalies detected
                </div>
              ) : (
                anomalies.slice(0, 20).map((a) => (
                  <div
                    key={a.event_id}
                    className={`bg-slate-800 rounded-xl p-4 border ${
                      a.event_type === 'slow_speed'
                        ? 'border-orange-500/30'
                        : 'border-red-500/30'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <AlertTriangle
                            size={14}
                            className={a.event_type === 'slow_speed' ? 'text-orange-400' : 'text-red-400'}
                          />
                          <span className="text-sm font-semibold text-white">
                            {a.vessel_name || a.mmsi}
                          </span>
                        </div>
                        <div className="text-xs text-slate-400 space-y-0.5">
                          <div>
                            Type:{' '}
                            <span className="text-slate-300">
                              {a.event_type === 'slow_speed' ? '🐢 Slow Speed' : '↗ Off Course'}
                            </span>
                          </div>
                          <div>
                            Destination:{' '}
                            <span className="text-slate-300">{a.destination_port}</span>
                          </div>
                          {a.estimated_delay_hours && (
                            <div className="text-orange-400">
                              Estimated delay: ~{a.estimated_delay_hours}h
                            </div>
                          )}
                          <div className="text-slate-500 text-xs mt-1">
                            {formatDistanceToNow(new Date(a.detected_at), { addSuffix: true })}
                          </div>
                        </div>
                      </div>
                      <div className="text-xs font-mono text-slate-500">
                        {a.lat?.toFixed(2)}, {a.lon?.toFixed(2)}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Reassurance Alerts */}
          <div>
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Shield size={14} className="text-green-400" />
              Reassurance Alerts ({alerts.length})
            </h2>
            <div className="space-y-3">
              {alerts.length === 0 ? (
                <div className="bg-slate-800 rounded-xl p-6 text-center text-slate-500 text-sm border border-slate-700">
                  <Shield size={24} className="mx-auto mb-2 text-green-500/50" />
                  No active reassurance alerts
                </div>
              ) : (
                alerts.map((a, i) => (
                  <div
                    key={i}
                    className="bg-slate-800 rounded-xl p-4 border border-green-500/30"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <Shield size={14} className="text-green-400" />
                      <span className="text-sm font-semibold text-white">{a.city}</span>
                      <span className="text-xs bg-red-500/20 text-red-400 px-2 py-0.5 rounded-full">
                        Panic Index: {a.panic_index.toFixed(0)}
                      </span>
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">{a.message}</p>
                    <p className="text-xs text-slate-500 mt-2">
                      {formatDistanceToNow(new Date(a.issued_at), { addSuffix: true })}
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
