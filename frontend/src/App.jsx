import { memo, useCallback, useEffect, useState } from 'react';
import SearchBox from './SearchBox.jsx';
import MapView from './MapView.jsx';
import { analyze } from './api.js';
import { LEVELS, LEVEL_COLORS, ROUTE_COLORS, fmtDuration, fmtMi, fmtTime } from './lib.js';

function defaultDeparture() {
  const d = new Date(Date.now() + 3600e3);
  d.setMinutes(0, 0, 0);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:00`;
}

const RiskBar = ({ miles }) => {
  const total = miles.reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="riskbar">
      {miles.map(
        (m, i) =>
          m > 0 && (
            <span key={i} style={{ width: `${(m / total) * 100}%`, background: LEVEL_COLORS[i] }} title={`${LEVELS[i]}: ${Math.round(m)} mi`} />
          ),
      )}
    </div>
  );
};

const RouteCard = memo(function RouteCard({ route, selected, recommended, onSelect }) {
  const s = route.summary;
  return (
    <section className={`card ${selected ? 'sel' : ''}`}>
      <button className="cardhead" onClick={() => onSelect(route.id)} aria-pressed={selected}>
        <b className="badge" style={{ background: ROUTE_COLORS[route.id] }}>{route.id}</b>
        <span className="main">
          <strong>{fmtDuration(route.duration_s)}</strong> <span className="dim">{fmtMi(route.distance_mi)}</span>
          {recommended && <em className="rec">Recommended</em>}
        </span>
        <span className="dim arrive">arrives {fmtTime(route.arrival)}</span>
      </button>
      <RiskBar miles={s.miles_by_level} />
      <p className="stats">
        {s.no_travel_miles > 0 && <span><b>{Math.round(s.no_travel_miles)}</b> mi No Travel</span>}
        <span><b>{Math.round(s.severe_miles)}</b> mi Severe</span>
        <span><b>{Math.round(s.high_miles)}</b> mi High</span>
        <span>avg risk <b>{s.avg_risk.toFixed(2)}</b>/4</span>
      </p>
      {selected && <CheckpointTable checkpoints={route.checkpoints} />}
    </section>
  );
});

const CheckpointTable = memo(function CheckpointTable({ checkpoints }) {
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr><th>Mile</th><th>ETA</th><th>Wind</th><th>Rain</th><th>Snow</th><th>Risk</th></tr>
        </thead>
        <tbody>
          {checkpoints.map((c) => (
            <tr key={c.mile}>
              <td>{Math.round(c.mile)}</td>
              <td>{fmtTime(c.eta)}</td>
              <td>{c.wind_mph}</td>
              <td>{c.rain_in_hr}</td>
              <td>{c.snow_in_hr}</td>
              <td><span className="pill" style={{ background: LEVEL_COLORS[c.level] }}>{c.level_name}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="dim small">Wind in mph, rain and snow in in/hr, at the truck’s estimated arrival time. Times in your local zone.</p>
    </div>
  );
});

function HeatSlider({ start, hour, setHour, show, setShow }) {
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing || !show) return;
    const id = setInterval(() => setHour((h) => (h + 1) % 49), 450);
    return () => clearInterval(id);
  }, [playing, show, setHour]);
  const t = new Date(new Date(start).getTime() + hour * 3600e3);
  return (
    <div className="slider">
      <label className="toggle">
        <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} /> Weather heatmap
      </label>
      <button type="button" className="play" onClick={() => setPlaying((p) => !p)} disabled={!show}>
        {playing ? 'Pause' : 'Play'}
      </button>
      <input type="range" min="0" max="48" step="1" value={hour} disabled={!show} onChange={(e) => setHour(+e.target.value)} aria-label="Forecast hour" />
      <span className="when">
        <b>+{hour}h</b> {t.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })}
      </span>
    </div>
  );
}

const Legend = () => (
  <div className="legend">
    {LEVELS.map((l, i) => (
      <span key={l}><i style={{ background: LEVEL_COLORS[i] }} />{l}</span>
    ))}
  </div>
);

export default function App() {
  const [origin, setOrigin] = useState(null);
  const [dest, setDest] = useState(null);
  const [departure, setDeparture] = useState(defaultDeparture);
  const [weight, setWeight] = useState(40000);
  const [spacing, setSpacing] = useState(25);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [selected, setSelected] = useState(null);
  const [hour, setHour] = useState(0);
  const [showHeat, setShowHeat] = useState(true);

  const onSelect = useCallback((id) => setSelected(id), []);

  async function submit(e) {
    e.preventDefault();
    setError('');
    const dep = new Date(departure);
    if (!origin || !dest) return setError('Pick an origin and a destination from the suggestions.');
    if (Number.isNaN(dep.getTime())) return setError('Enter a departure date and time.');
    setLoading(true);
    try {
      const res = await analyze({
        origin,
        destination: dest,
        departure: dep.toISOString(),
        weight_lb: Number(weight),
        interval_mi: spacing,
      });
      setResult(res);
      setSelected(res.recommendation.route_id);
      setHour(0);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const rec = result?.recommendation;
  return (
    <div className="app">
      <aside className="side">
        <header>
          <h1>Weather-aware truck routing</h1>
          <p className="dim">Compare three routes by forecast weather at your arrival time, your load and travel time.</p>
        </header>
        <form onSubmit={submit}>
          <SearchBox label="Origin" placeholder="e.g. Dallas, TX" onChange={setOrigin} />
          <SearchBox label="Destination" placeholder="e.g. Denver, CO" onChange={setDest} />
          <div className="row">
            <label className="field">
              <span>Departure</span>
              <input type="datetime-local" value={departure} onChange={(e) => setDeparture(e.target.value)} />
            </label>
            <label className="field">
              <span>Load (lb)</span>
              <input type="number" min="1" max="150000" step="500" value={weight} onChange={(e) => setWeight(e.target.value)} />
            </label>
          </div>
          <label className="field">
            <span>Weather checkpoint every</span>
            <select value={spacing} onChange={(e) => setSpacing(+e.target.value)}>
              <option value={10}>10 miles (most detailed)</option>
              <option value={25}>25 miles</option>
              <option value={50}>50 miles (fastest)</option>
            </select>
          </label>
          <button className="go" disabled={loading}>{loading ? 'Checking forecasts…' : 'Find safest route'}</button>
        </form>
        {error && <div className="error" role="alert">{error}</div>}
        {rec && (
          <div className="results">
            <div className="banner">
              <strong>Route {rec.route_id} is the safest choice.</strong>
              <p>{rec.reason}</p>
              {rec.advisory && <p className="warn">{rec.advisory}</p>}
              {result.meta.forecast_clamped && (
                <p className="dim small">Some times fall outside the forecast range; the nearest available hour was used.</p>
              )}
            </div>
            {result.routes.map((r) => (
              <RouteCard key={r.id} route={r} selected={r.id === selected} recommended={r.id === rec.route_id} onSelect={onSelect} />
            ))}
          </div>
        )}
      </aside>
      <main className="mapwrap">
        <MapView routes={result?.routes} selectedId={selected} onSelect={onSelect} heat={result?.heat} hour={hour} showHeat={showHeat} />
        {result && <HeatSlider start={result.heat.start} hour={hour} setHour={setHour} show={showHeat} setShow={setShowHeat} />}
        {result && <Legend />}
      </main>
    </div>
  );
}
