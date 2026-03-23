import { useState, useEffect, useRef } from 'react'

/**
 * Two-step confirmation modal for switching to LIVE trading.
 *
 * Step 1: Warning message + "I understand the risks" button.
 * Step 2: Type "CONFIRM" to finalize.
 */
export default function ConfirmLiveModal({ open, onConfirm, onCancel }) {
  const [step, setStep] = useState(1)
  const [typed, setTyped] = useState('')
  const inputRef = useRef(null)

  // Reset state when modal opens/closes
  useEffect(() => {
    if (open) {
      setStep(1)
      setTyped('')
    }
  }, [open])

  // Auto-focus the confirm input on step 2
  useEffect(() => {
    if (step === 2 && inputRef.current) {
      inputRef.current.focus()
    }
  }, [step])

  if (!open) return null

  const canConfirm = typed.trim().toUpperCase() === 'CONFIRM'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Modal */}
      <div className="relative w-full max-w-md mx-4 bg-[#1e293b] border border-red-500/40 rounded-xl shadow-2xl shadow-red-500/10 overflow-hidden">
        {/* Red top accent */}
        <div className="h-1 bg-gradient-to-r from-red-500 via-red-600 to-red-500" />

        <div className="p-6">
          {/* Header */}
          <div className="flex items-center gap-3 mb-4">
            <div className="flex items-center justify-center w-10 h-10 rounded-full bg-red-500/20">
              <svg className="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Switch to Live Trading</h2>
              <p className="text-xs text-red-400 font-medium">Real money will be at risk</p>
            </div>
          </div>

          {step === 1 && (
            <>
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 mb-5">
                <ul className="space-y-2 text-sm text-slate-300">
                  <li className="flex items-start gap-2">
                    <span className="text-red-400 mt-0.5">•</span>
                    All orders will execute with <strong className="text-white">real money</strong> on your live Alpaca account.
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-red-400 mt-0.5">•</span>
                    Portfolio data will switch to your <strong className="text-white">live account balances</strong>.
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-red-400 mt-0.5">•</span>
                    Agent actions will result in <strong className="text-white">actual trades</strong> being placed.
                  </li>
                </ul>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={onCancel}
                  className="flex-1 px-4 py-2.5 text-sm font-medium text-slate-300 bg-[#334155] rounded-lg hover:bg-[#475569] transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => setStep(2)}
                  className="flex-1 px-4 py-2.5 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors"
                >
                  I understand the risks
                </button>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <p className="text-sm text-slate-300 mb-4">
                Type <code className="px-1.5 py-0.5 bg-red-500/20 text-red-300 rounded font-mono text-xs">CONFIRM</code> below to switch to live trading:
              </p>

              <input
                ref={inputRef}
                type="text"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder="Type CONFIRM"
                className="w-full px-4 py-2.5 text-sm font-mono bg-[#0f172a] border border-[#475569] rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-red-500/50 focus:border-red-500 transition-colors"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && canConfirm) onConfirm()
                  if (e.key === 'Escape') onCancel()
                }}
              />

              <div className="flex gap-3 mt-4">
                <button
                  onClick={onCancel}
                  className="flex-1 px-4 py-2.5 text-sm font-medium text-slate-300 bg-[#334155] rounded-lg hover:bg-[#475569] transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={onConfirm}
                  disabled={!canConfirm}
                  className={`flex-1 px-4 py-2.5 text-sm font-bold rounded-lg transition-colors ${
                    canConfirm
                      ? 'bg-red-600 text-white hover:bg-red-700'
                      : 'bg-[#334155] text-slate-500 cursor-not-allowed'
                  }`}
                >
                  Switch to Live
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
