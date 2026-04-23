/**
 * API client for Premium Trader dashboard.
 */
const BASE = '/api';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-cache',
      'Pragma': 'no-cache',
      ...options.headers,
    },
    cache: 'no-store',
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// ── Portfolio (used by Command Center positions panel) ────────
export const fetchOptions = () => request('/portfolio/options');

// ── Research Dashboard ───────────────────────────────────────
export const fetchDashboardStatus = () => request('/dashboard/status');
export const fetchDashboardPromotions = (date) =>
  request(`/dashboard/promotions${date ? `?date=${date}` : ''}`);
export const fetchDashboardSignals = (days = 14) => request(`/dashboard/signals?days=${days}`);
export const fetchDashboardReflection = () => request('/dashboard/reflection');
export const fetchDashboardPlaybook = (limit = 30) => request(`/dashboard/playbook?limit=${limit}`);
export const fetchDashboardCycles = (limit = 10) => request(`/dashboard/cycles?limit=${limit}`);
export const fetchDashboardDailyStats = (days = 30) => request(`/dashboard/daily-stats?days=${days}`);
export const fetchDashboardTrades = (days = 30) => request(`/dashboard/trades?days=${days}`);
