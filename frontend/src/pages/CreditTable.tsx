/**
 * Credit Table — paginated dealer loan applications.
 */
import React, { useState } from 'react'
import { useQuery } from 'react-query'
import { fetchCreditHistory } from '../services/api'
import { CreditCard, CheckCircle, Clock, AlertCircle, XCircle } from 'lucide-react'

const STATUS_CONFIG: Record<string, { color: string; icon: React.ElementType; label: string }> = {
  pending: { color: 'text-slate-400', icon: Clock, label: 'Pending' },
  approved: { color: 'text-blue-400', icon: CheckCircle, label: 'Approved' },
  disbursed: { color: 'text-green-400', icon: CheckCircle, label: 'Disbursed' },
  repaid: { color: 'text-slate-500', icon: CheckCircle, label: 'Repaid' },
  overdue: { color: 'text-red-400', icon: XCircle, label: 'Overdue' },
}

export function CreditTable() {
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<string>('all')

  const { data, isLoading, isError } = useQuery(
    ['credit', page],
    () => fetchCreditHistory(page),
    { keepPreviousData: true }
  )

  const applications = data?.applications || []
  const filtered = statusFilter === 'all'
    ? applications
    : applications.filter((a: any) => a.status === statusFilter)

  return (
    <div className="h-full overflow-y-auto p-6 bg-slate-950">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <CreditCard size={22} className="text-orange-400" />
            <h1 className="text-xl font-bold text-white">Dealer Credit Applications</h1>
          </div>
          {/* Status filter */}
          <div className="flex gap-2">
            {['all', 'disbursed', 'overdue', 'repaid'].map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  statusFilter === s
                    ? 'bg-orange-500 text-white'
                    : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
                }`}
              >
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center h-64 text-slate-500">
            Loading applications…
          </div>
        ) : isError ? (
          <div className="flex items-center justify-center h-64 text-red-400">
            <AlertCircle size={20} className="mr-2" /> Failed to load. Is the API running?
          </div>
        ) : (
          <>
            <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700 bg-slate-900/50">
                    <th className="text-left p-4 text-slate-400 font-medium text-xs uppercase tracking-wider">Loan ID</th>
                    <th className="text-left p-4 text-slate-400 font-medium text-xs uppercase tracking-wider">Amount</th>
                    <th className="text-left p-4 text-slate-400 font-medium text-xs uppercase tracking-wider">Status</th>
                    <th className="text-left p-4 text-slate-400 font-medium text-xs uppercase tracking-wider">Applied</th>
                    <th className="text-left p-4 text-slate-400 font-medium text-xs uppercase tracking-wider">Due Date</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="text-center p-8 text-slate-500">
                        No applications found
                      </td>
                    </tr>
                  ) : (
                    filtered.map((app: any) => {
                      const cfg = STATUS_CONFIG[app.status] || STATUS_CONFIG.pending
                      const Icon = cfg.icon
                      return (
                        <tr
                          key={app.loan_id}
                          className="border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors"
                        >
                          <td className="p-4 font-mono text-xs text-slate-300">
                            {app.loan_id.slice(0, 8)}…
                          </td>
                          <td className="p-4 font-semibold text-white">
                            ₹{parseFloat(app.amount).toLocaleString('en-IN')}
                          </td>
                          <td className="p-4">
                            <span className={`flex items-center gap-1.5 ${cfg.color}`}>
                              <Icon size={14} />
                              {cfg.label}
                            </span>
                          </td>
                          <td className="p-4 text-slate-400 text-xs">
                            {app.applied_at ? new Date(app.applied_at).toLocaleDateString('en-IN') : '—'}
                          </td>
                          <td className="p-4 text-xs">
                            {app.due_date ? (
                              <span className={new Date(app.due_date) < new Date() ? 'text-red-400' : 'text-slate-400'}>
                                {new Date(app.due_date).toLocaleDateString('en-IN')}
                              </span>
                            ) : '—'}
                          </td>
                        </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 bg-slate-700 text-slate-300 rounded text-xs disabled:opacity-40 hover:bg-slate-600 transition-colors"
              >
                Previous
              </button>
              <span className="px-3 py-1.5 text-slate-400 text-xs">Page {page}</span>
              <button
                onClick={() => setPage(p => p + 1)}
                disabled={filtered.length < 20}
                className="px-3 py-1.5 bg-slate-700 text-slate-300 rounded text-xs disabled:opacity-40 hover:bg-slate-600 transition-colors"
              >
                Next
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
