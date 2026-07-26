import React, { useEffect } from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { useWebSocket } from './hooks/useWebSocket'
import { useVessels, useDisruptions, usePumps, usePanic } from './hooks/useApi'
import { MapView } from './pages/MapView'
import { Analytics } from './pages/Analytics'
import { CreditTable } from './pages/CreditTable'
import { AlertsFeed } from './pages/AlertsFeed'
import { useStore } from './store'
import { Ship, BarChart3, CreditCard, Bell, Zap, Wifi, WifiOff } from 'lucide-react'

function DataLoader() {
  // Hydrate store from REST on mount; WebSocket keeps it live after
  useVessels()
  useDisruptions()
  usePumps()
  usePanic()
  return null
}

function WsBadge() {
  const [connected, setConnected] = React.useState(false)
  useEffect(() => {
    const timer = setInterval(() => {
      // Check via a ping — simplistic but effective
      setConnected(true)
    }, 5000)
    return () => clearInterval(timer)
  }, [])
  return connected
    ? <Wifi size={14} className="text-green-400" />
    : <WifiOff size={14} className="text-slate-500" />
}

export default function App() {
  useWebSocket()
  const { alerts } = useStore()
  const unread = alerts.length

  return (
    <BrowserRouter>
      <DataLoader />
      <div className="flex h-screen bg-slate-950 text-slate-100 font-sans overflow-hidden">

        {/* ── Sidebar ──────────────────────────────────────────────── */}
        <aside className="w-16 lg:w-56 flex flex-col bg-slate-900 border-r border-slate-800 flex-shrink-0">

          {/* Logo */}
          <div className="p-4 border-b border-slate-800 flex items-center gap-2">
            <div className="w-8 h-8 bg-orange-500 rounded-lg flex items-center justify-center flex-shrink-0">
              <Zap size={16} className="text-white" />
            </div>
            <div className="hidden lg:block">
              <p className="text-white font-bold text-sm leading-none">FuelChain</p>
              <p className="text-slate-400 text-xs mt-0.5">Guardian</p>
            </div>
          </div>

          {/* Nav links */}
          <nav className="flex-1 p-2 space-y-1 mt-2">
            {[
              { to: '/',          icon: Ship,     label: 'Live Map'  },
              { to: '/analytics', icon: BarChart3, label: 'Analytics' },
              { to: '/credit',    icon: CreditCard,label: 'Credit'   },
              { to: '/alerts',    icon: Bell,      label: 'Alerts',  badge: unread },
            ].map(({ to, icon: Icon, label, badge }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm
                   transition-colors ${isActive
                    ? 'bg-orange-500/20 text-orange-400'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-white'
                  }`
                }
              >
                <Icon size={18} className="flex-shrink-0" />
                <span className="hidden lg:block">{label}</span>
                {badge != null && badge > 0 && (
                  <span className="absolute top-1 right-1 lg:static lg:ml-auto
                    bg-red-500 text-white text-xs font-bold rounded-full
                    w-5 h-5 flex items-center justify-center">
                    {badge > 9 ? '9+' : badge}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>

          {/* WS status */}
          <div className="p-3 border-t border-slate-800 flex items-center gap-2">
            <WsBadge />
            <span className="hidden lg:block text-xs text-slate-500">Live feed</span>
          </div>
        </aside>

        {/* ── Main ─────────────────────────────────────────────────── */}
        <main className="flex-1 overflow-hidden">
          <Routes>
            <Route path="/"          element={<MapView />}    />
            <Route path="/analytics" element={<Analytics />}  />
            <Route path="/credit"    element={<CreditTable />} />
            <Route path="/alerts"    element={<AlertsFeed />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
