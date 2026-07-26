/**
 * Analytics — Disruption Index, Panic Index, and pump status charts.
 */
import React from 'react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, Legend,
} from 'recharts'
import { useStore } from '../store'
import { useQuery } from 'react-query'
import { fetchAllDisruptions, fetchAllPanicIndices } from '../services/api'
import { AlertTriangle, TrendingUp, Droplets, Activity } from 'lucide-react'

function MetricCard({
  title, value, subtitle, color, icon: Icon,
}: {
  title: string
  value: string | number
  subtitle?: string
  color: string
  icon: React.ElementType
}) {
  return (
    <div className="bg-slate-800 rounded-xl p-4 border border-slate-700">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-slate-400 text-xs uppercase tracking-wider">{title}</p>
          <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
          {subtitle && <p className="text-slate-500 text-xs mt-1">{subtitle}</p>}
        </div>
        <div className={`p-2 rounded-lg bg-slate-700`}>
          <Icon size={18} className={color} />
        </div>
      </div>
    </div>
  )
}

export function Analytics() {
  const { vessels, pumps, disruptions, panicData } = useStore()

  const pumpList = Object.values(pumps)
  const redPumps = pumpList.filter(p => p.status === 'RED').length
  const yellowPumps = pumpList.filter(p => p.status === 'YELLOW').length
  const greenPumps = pumpList.filter(p => p.status === 'GREEN').length

  const { data: disruptionList } = useQuery('disruptions', fetchAllDisruptions, {
    refetchInterval: 30000,
  })

  const { data: panicList } = useQuery('panic', fetchAllPanicIndices, {
    refetchInterval: 30000,
  })

  const disruptionData = disruptionList || Object.values(disruptions).map(d => ({
    port_code: d.port_code,
    disruption_index: d.disruption_index,
  }))

  const panicChartData = panicList || Object.values(panicData).map(p => ({
    city: p.city,
    panic_index: p.panic_index,
  }))

  const pumpStatusData = [
    { name: 'Green (>50%)', value: greenPumps, fill: '#22c55e' },
    { name: 'Yellow (20–50%)', value: yellowPumps, fill: '#eab308' },
    { name: 'Red (<20%)', value: redPumps, fill: '#ef4444' },
  ]

  const avgDisruption = disruptionData.length
    ? (disruptionData.reduce((s, d) => s + (d.disruption_index || 0), 0) / disruptionData.length).toFixed(1)
    : '0'

  const maxPanic = panicChartData.length
    ? Math.max(...panicChartData.map(p => p.panic_index || 0)).toFixed(0)
    : '0'

  return (
    <div className="h-full overflow-y-auto p-6 bg-slate-950">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-xl font-bold text-white mb-6">Supply Chain Analytics</h1>

        {/* Metric cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <MetricCard
            title="Avg Disruption Index"
            value={avgDisruption}
            subtitle="Across all ports"
            color="text-orange-400"
            icon={AlertTriangle}
          />
          <MetricCard
            title="Max Panic Index"
            value={maxPanic}
            subtitle="Any city right now"
            color="text-red-400"
            icon={Activity}
          />
          <MetricCard
            title="Critical Pumps"
            value={redPumps}
            subtitle="Status RED (<20% stock)"
            color="text-red-400"
            icon={Droplets}
          />
          <MetricCard
            title="Tracked Tankers"
            value={Object.keys(vessels).length}
            subtitle="In AIS coverage"
            color="text-blue-400"
            icon={TrendingUp}
          />
        </div>

        <div className="grid lg:grid-cols-2 gap-6">
          {/* Disruption Index by Port */}
          <div className="bg-slate-800 rounded-xl p-5 border border-slate-700">
            <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider">
              Disruption Index by Port
            </h2>
            {disruptionData.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={disruptionData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="port_code" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} domain={[0, 100]} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                    labelStyle={{ color: '#f1f5f9' }}
                  />
                  <Bar dataKey="disruption_index" name="Disruption Index" radius={[4, 4, 0, 0]}>
                    {disruptionData.map((entry, i) => (
                      <Cell
                        key={i}
                        fill={
                          entry.disruption_index > 70 ? '#ef4444'
                          : entry.disruption_index > 40 ? '#f97316'
                          : '#22c55e'
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-48 flex items-center justify-center text-slate-500 text-sm">
                Waiting for disruption data…
              </div>
            )}
          </div>

          {/* Panic Index by City */}
          <div className="bg-slate-800 rounded-xl p-5 border border-slate-700">
            <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider">
              Panic Index by City
            </h2>
            {panicChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={panicChartData.slice(0, 10)}
                  layout="vertical"
                  margin={{ top: 5, right: 10, left: 30, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis type="number" domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                  <YAxis type="category" dataKey="city" tick={{ fill: '#94a3b8', fontSize: 11 }} width={60} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                  />
                  <Bar dataKey="panic_index" name="Panic Index" radius={[0, 4, 4, 0]}>
                    {panicChartData.slice(0, 10).map((entry, i) => (
                      <Cell
                        key={i}
                        fill={
                          entry.panic_index > 70 ? '#ef4444'
                          : entry.panic_index > 40 ? '#f97316'
                          : '#3b82f6'
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-48 flex items-center justify-center text-slate-500 text-sm">
                Waiting for social media data…
              </div>
            )}
          </div>

          {/* Pump Status Distribution */}
          <div className="bg-slate-800 rounded-xl p-5 border border-slate-700">
            <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider">
              Pump Inventory Status
            </h2>
            {pumpList.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={pumpStatusData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                  />
                  <Bar dataKey="value" name="Pump Count" radius={[4, 4, 0, 0]}>
                    {pumpStatusData.map((entry, i) => (
                      <Cell key={i} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-48 flex items-center justify-center text-slate-500 text-sm">
                Waiting for pump data…
              </div>
            )}
          </div>

          {/* Recent Anomalies */}
          <div className="bg-slate-800 rounded-xl p-5 border border-slate-700">
            <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider">
              Recent Anomalies
            </h2>
            {useStore.getState().anomalies.length > 0 ? (
              <div className="space-y-2 max-h-56 overflow-y-auto">
                {useStore.getState().anomalies.slice(0, 8).map((a) => (
                  <div
                    key={a.event_id}
                    className="flex items-start gap-3 p-2 rounded-lg bg-slate-700/50"
                  >
                    <AlertTriangle size={14} className="text-orange-400 mt-0.5 flex-shrink-0" />
                    <div className="text-xs">
                      <span className="text-white font-medium">{a.vessel_name || a.mmsi}</span>
                      <span className="text-slate-400 ml-2">{a.event_type.replace('_', ' ')}</span>
                      {a.estimated_delay_hours && (
                        <span className="text-orange-400 ml-2">+{a.estimated_delay_hours}h delay</span>
                      )}
                      <div className="text-slate-500 mt-0.5">→ {a.destination_port}</div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="h-48 flex items-center justify-center text-slate-500 text-sm">
                No anomalies detected
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
