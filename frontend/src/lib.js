export const LEVELS = ['Low', 'Moderate', 'High', 'Severe', 'No Travel'];
export const LEVEL_COLORS = ['#2da44e', '#d4a72c', '#e5772b', '#d1242f', '#8250df'];
export const ROUTE_COLORS = { A: '#0b7285', B: '#4263eb', C: '#c2255c' };

export function fmtDuration(s) {
  const m = Math.round(s / 60);
  const h = Math.floor(m / 60);
  return h ? `${h}h ${String(m % 60).padStart(2, '0')}m` : `${m}m`;
}
export const fmtTime = (iso) =>
  new Date(iso).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
export const fmtMi = (n) => `${Math.round(n).toLocaleString()} mi`;
