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
export const fetchDashboardCycles = (limit = 10, days = null) =>
  request(`/dashboard/cycles?limit=${limit}${days ? `&days=${days}` : ''}`);
export const fetchDashboardDailyStats = (days = 30) => request(`/dashboard/daily-stats?days=${days}`);
export const fetchDashboardTrades = (days = 30) => request(`/dashboard/trades?days=${days}`);
export const fetchPositionAlerts = () => request('/dashboard/position-alerts');
export const fetchReconciliation = () => request('/dashboard/reconciliation');

// ── Redesign additions (structured-data architecture) ────────
export const fetchConflicts = (days = 7) => request(`/dashboard/conflicts?days=${days}`);
export const fetchActivity = (limit = 40) => request(`/dashboard/activity?limit=${limit}`);
export const fetchMessageBus = (limit = 30) => request(`/dashboard/message-bus?limit=${limit}`);
export const fetchAgentCosts = () => request('/dashboard/agent-costs');
export const fetchFillQuality = (days = 30) => request(`/dashboard/fill-quality?days=${days}`);
