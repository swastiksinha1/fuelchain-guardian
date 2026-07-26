/**
 * LoginPage — simple JWT login form for the web dashboard.
 * Shown when no valid token is stored.
 */
import React, { useState } from 'react'
import { login } from '../services/api'
import { Zap, Lock } from 'lucide-react'

interface Props { onLogin: () => void }

export function LoginPage({ onLogin }: Props) {
  const [email, setEmail] = useState('admin@fuelchain.dev')
  const [password, setPassword] = useState('Admin@1234')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await login(email, password)
      onLogin()
    } catch {
      setError('Invalid credentials. Try admin@fuelchain.dev / Admin@1234')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16
            bg-orange-500 rounded-2xl mb-4 shadow-lg shadow-orange-500/30">
            <Zap size={30} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white">FuelChain Guardian</h1>
          <p className="text-slate-400 text-sm mt-1">Authorities Dashboard</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1.5">Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5
                text-white placeholder-slate-500 focus:outline-none focus:border-orange-500
                transition-colors"
              placeholder="admin@fuelchain.dev"
              required
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1.5">Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5
                text-white placeholder-slate-500 focus:outline-none focus:border-orange-500
                transition-colors"
              placeholder="••••••••"
              required
            />
          </div>

          {error && (
            <p className="text-red-400 text-sm bg-red-500/10 border border-red-500/20
              rounded-lg px-3 py-2">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-orange-500 hover:bg-orange-600 disabled:opacity-50
              text-white font-semibold py-2.5 rounded-lg transition-colors
              flex items-center justify-center gap-2"
          >
            <Lock size={16} />
            {loading ? 'Signing in…' : 'Sign In'}
          </button>
        </form>

        <p className="text-center text-slate-500 text-xs mt-6">
          Demo: admin@fuelchain.dev / Admin@1234
        </p>
      </div>
    </div>
  )
}
