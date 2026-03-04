/**
 * API client for Premium Trader backend.
 */
const BASE = '/api';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// ── Portfolio ──────────────────────────────────────────────────
export const fetchPortfolio = () => request('/portfolio/');
export const fetchPortfolioSummary = () => request('/portfolio/summary');
export const fetchPositions = () => request('/portfolio/positions');
export const fetchOptions = () => request('/portfolio/options');
export const refreshPortfolio = () => request('/portfolio/refresh', { method: 'POST' });

// ── Trades ─────────────────────────────────────────────────────
export const fetchTradeHistory = (params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/trades/history?${q}`);
};
export const fetchJournal = (params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/trades/journal?${q}`);
};
export const fetchPerformance = () => request('/trades/performance');
export const fetchAgentPerformance = (name, days = 30) =>
  request(`/trades/performance/${name}?days=${days}`);
export const fetchSymbolStats = (symbol) => request(`/trades/symbol/${symbol}`);

// ── Agents ─────────────────────────────────────────────────────
export const fetchAgentStatus = () => request('/agents/status');
export const fetchRegime = () => request('/agents/regime');
export const refreshRegime = () => request('/agents/regime/refresh', { method: 'POST' });
export const fetchStrategies = () => request('/agents/strategies');
export const updateStrategy = (strategy_name, params) =>
  request('/agents/strategies', {
    method: 'PUT',
    body: JSON.stringify({ strategy_name, params }),
  });

// ── Scanner ────────────────────────────────────────────────────
export const fetchOpportunities = (top_n) =>
  request(`/scanner/opportunities${top_n ? `?top_n=${top_n}` : ''}`);
export const runScanner = () => request('/scanner/run', { method: 'POST' });
export const fetchScannerConfig = () => request('/scanner/config');
export const updateScannerConfig = (update) =>
  request('/scanner/config', { method: 'PUT', body: JSON.stringify(update) });
export const previewScanner = (overrides) =>
  request('/scanner/preview', { method: 'POST', body: JSON.stringify(overrides) });

// ── Backtest ───────────────────────────────────────────────────
export const runBacktest = (params) =>
  request('/backtest/run', { method: 'POST', body: JSON.stringify(params) });
export const getBacktestStatus = (jobId) => request(`/backtest/status/${jobId}`);
export const getBacktestResults = (jobId) => request(`/backtest/results/${jobId}`);
export const listBacktestResults = () => request('/backtest/results');
export const runCompare = (params) =>
  request('/backtest/compare', { method: 'POST', body: JSON.stringify(params) });
export const listJobs = () => request('/backtest/jobs');

// ── Health ─────────────────────────────────────────────────────
export const fetchHealth = () => request('/health');
