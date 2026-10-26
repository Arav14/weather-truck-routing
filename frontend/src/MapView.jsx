import { useEffect, useRef } from "react";
import L from "leaflet";
import {
  LEVELS,
  LEVEL_COLORS,
  ROUTE_COLORS,
  fmtDuration,
  fmtMi,
  fmtTime,
} from "./lib.js";

const RGB = [
  [45, 164, 78],
  [212, 167, 44],
  [229, 119, 43],
  [209, 36, 47],
  [130, 80, 223],
];
const ALPHA = [0.2, 0.45, 0.55, 0.62, 0.7];

/* Heatmap: one soft radial blob per forecast point, coloured by the risk level at the slider hour.
   Drawn on a single canvas; the slider only triggers a cheap redraw (no DOM or data work). */
const HeatLayer = L.Layer.extend({
  initialize(heat) {
    this._heat = heat;
    this._hour = 0;
    this._raf = 0;
  },
  onAdd(map) {
    this._map = map;
    this._canvas = L.DomUtil.create("canvas", "heat-canvas leaflet-zoom-hide");
    map.getPane("heat").appendChild(this._canvas);
    map.on("moveend zoomend resize", this._reset, this);
    this._reset();
  },
  onRemove(map) {
    cancelAnimationFrame(this._raf);
    map.off("moveend zoomend resize", this._reset, this);
    this._canvas.remove();
    this._map = null;
  },
  setHour(h) {
    this._hour = h;
    this._schedule();
  },
  _schedule() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = 0;
      this._draw();
    });
  },
  _reset() {
    const m = this._map;
    const size = m.getSize();
    const c = this._canvas;
    if (c.width !== size.x || c.height !== size.y) {
      c.width = size.x;
      c.height = size.y;
    }
    L.DomUtil.setPosition(c, m.containerPointToLayerPoint([0, 0]));
    this._draw();
  },
  _draw() {
    const m = this._map;
    if (!m) return;
    const c = this._canvas;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    const { points, interval_mi: spacing } = this._heat;
    const radiusM = Math.max(spacing, 10) * 1609.34 * 0.75;
    const zoom = m.getZoom();
    const h = this._hour;
    const order = points
      .map((p) => ({ p, l: +p.levels[h] || 0 }))
      .sort((a, b) => a.l - b.l);
    for (const { p, l } of order) {
      const pt = m.latLngToContainerPoint([p.lat, p.lng]);
      const mpp =
        (40075016.686 * Math.cos((p.lat * Math.PI) / 180)) / (256 * 2 ** zoom);
      const r = Math.min(110, Math.max(10, radiusM / mpp));
      if (pt.x < -r || pt.y < -r || pt.x > c.width + r || pt.y > c.height + r)
        continue;
      const [R, G, B] = RGB[l];
      const g = ctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, r);
      g.addColorStop(0, `rgba(${R},${G},${B},${ALPHA[l]})`);
      g.addColorStop(0.55, `rgba(${R},${G},${B},${ALPHA[l] * 0.6})`);
      g.addColorStop(1, `rgba(${R},${G},${B},0)`);
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, r, 0, Math.PI * 2);
      ctx.fill();
    }
  },
});

const popupHtml = (route, cp) => `
  <div class="pop">
    <strong>Route ${route.id} · mile ${Math.round(cp.mile)}</strong><br/>
    ETA ${fmtTime(cp.eta)}<br/>
    Wind ${cp.wind_mph} mph · Rain ${cp.rain_in_hr} in/hr · Snow ${cp.snow_in_hr} in/hr<br/>
    <b style="color:${LEVEL_COLORS[cp.level]}">${cp.level_name}</b>
  </div>`;

export default function MapView({
  routes,
  selectedId,
  onSelect,
  heat,
  hour,
  showHeat,
}) {
  const el = useRef(null);
  const map = useRef(null);
  const routeGroup = useRef(null);
  const cpGroup = useRef(null);
  const lines = useRef({});
  const heatLayer = useRef(null);

  useEffect(() => {
    const m = L.map(el.current, {
      preferCanvas: true,
      zoomControl: true,
    }).setView([39.5, -98.35], 4);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(m);
    m.createPane("heat").style.zIndex = 350;
    routeGroup.current = L.layerGroup().addTo(m);
    cpGroup.current = L.layerGroup().addTo(m);
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
  }, []);

  // draw routes
  useEffect(() => {
    routeGroup.current.clearLayers();
    lines.current = {};
    if (!routes?.length) return;
    const all = [];
    for (const r of routes) {
      const line = L.polyline(r.geometry, {
        color: ROUTE_COLORS[r.id],
        weight: 4,
        opacity: 0.6,
      })
        .bindTooltip(
          `Route ${r.id} · ${fmtDuration(r.duration_s)} · ${fmtMi(r.distance_mi)}`,
          { sticky: true },
        )
        .on("click", () => onSelect(r.id))
        .addTo(routeGroup.current);
      lines.current[r.id] = line;
      all.push(...r.geometry);
    }
    map.current.fitBounds(L.latLngBounds(all), { padding: [40, 40] });
  }, [routes, onSelect]);

  // selection styling + checkpoint markers
  useEffect(() => {
    cpGroup.current.clearLayers();
    if (!routes?.length) return;
    for (const [id, line] of Object.entries(lines.current)) {
      const sel = id === selectedId;
      line.setStyle({ weight: sel ? 7 : 4, opacity: sel ? 0.95 : 0.5 });
      if (sel) line.bringToFront();
    }
    const ordered = [...routes].sort(
      (a, b) => (a.id === selectedId) - (b.id === selectedId),
    );
    for (const r of ordered) {
      const sel = r.id === selectedId;
      for (const cp of r.checkpoints) {
        L.circleMarker([cp.lat, cp.lng], {
          radius: sel ? 6 : 3.5,
          color: "#fff",
          weight: sel ? 1.5 : 1,
          fillColor: LEVEL_COLORS[cp.level],
          fillOpacity: sel ? 1 : 0.8,
        })
          .bindPopup(() => popupHtml(r, cp))
          .addTo(cpGroup.current);
      }
    }
  }, [routes, selectedId]);

  // heatmap layer lifecycle + slider updates
  useEffect(() => {
    if (heatLayer.current) map.current.removeLayer(heatLayer.current);
    heatLayer.current = heat ? new HeatLayer(heat) : null;
  }, [heat]);

  useEffect(() => {
    const layer = heatLayer.current;
    if (!layer) return;
    if (showHeat && !map.current.hasLayer(layer)) map.current.addLayer(layer);
    if (!showHeat && map.current.hasLayer(layer))
      map.current.removeLayer(layer);
    layer.setHour(hour);
  }, [heat, hour, showHeat]);

  return <div ref={el} className="map" />;
}
