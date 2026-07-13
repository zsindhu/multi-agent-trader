/**
 * Shared design constants + helpers for the Win95 × Bloomberg redesign.
 * Tokens per design handoff — no border radius, no shadows, instant states.
 */

export const SLEEVES = {
  event_driven: { tag: 'EVT', name: 'Event-Driven', bg: '#e8e8ff' },
  vol_reversion: { tag: 'VOL', name: 'Vol Reversion', bg: '#e8ffe8' },
  sector_rotation: { tag: 'SEC', name: 'Sector Rotation', bg: '#fff0e0' },
  yield_farming: { tag: 'YLD', name: 'Yield Farming', bg: '#ffffe0' },
}

export const sleeveInfo = (id) =>
  SLEEVES[id] || { tag: id ? id.slice(0, 3).toUpperCase() : '—', name: id || 'Unattributed', bg: '#f0f0f0' }

export const MONO = "'Cascadia Mono', monospace"
export const UI = 'Tahoma, sans-serif'

export const outset = { border: '2px outset #dfdfdf' }
export const inset = { border: '2px inset #dfdfdf' }

export function fmtMoney(n, { sign = false, dp = 0 } = {}) {
  if (n == null) return '--'
  const s = Number(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  return (sign && n > 0 ? '+$' : n < 0 ? '-$' : '$') + s.replace('-', '')
}

export function pnlColor(n) {
  if (n == null) return '#000'
  return n > 0 ? '#008000' : n < 0 ? '#ff0000' : '#000'
}

export function etClock(now = new Date()) {
  // ET = UTC-4 (EDT approximation, matches existing dashboard convention)
  const et = new Date(now.getTime() - 4 * 3600 * 1000)
  const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  const hh = String(et.getUTCHours()).padStart(2, '0')
  const mm = String(et.getUTCMinutes()).padStart(2, '0')
  const mins = et.getUTCHours() * 60 + et.getUTCMinutes()
  const weekday = et.getUTCDay()
  const open = weekday >= 1 && weekday <= 5 && mins >= 570 && mins <= 960
  return `${days[weekday]} ${months[et.getUTCMonth()]} ${et.getUTCDate()} · ${hh}:${mm} ET · MARKET ${open ? 'OPEN' : 'CLOSED'}`
}

export function fmtTimeET(iso) {
  if (!iso) return '--'
  const d = new Date(iso)
  const et = new Date(d.getTime() - 4 * 3600 * 1000)
  return `${String(et.getUTCHours()).padStart(2, '0')}:${String(et.getUTCMinutes()).padStart(2, '0')}`
}

export const isAdmin = () =>
  typeof window !== 'undefined' && window.localStorage.getItem('pt_admin') === '1'

// Typing ?admin=1 into the URL arms the (paper-grade) admin gate.
export function checkAdminParam() {
  if (typeof window === 'undefined') return
  const params = new URLSearchParams(window.location.search)
  if (params.get('admin') === '1') window.localStorage.setItem('pt_admin', '1')
  if (params.get('admin') === '0') window.localStorage.removeItem('pt_admin')
}
