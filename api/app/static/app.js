/* Interfaz de LifeMap: consume la API de este mismo origen. Mapa: Leaflet (BSD-2), dibujo: Leaflet.draw (MIT),
   mosaicos: OpenStreetMap (ODbL). */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 0) => Number(n).toLocaleString("es-CO", { maximumFractionDigits: d });
const OPEN = "#0f766e", CLOSED = "#c2410c", ACCENT = "#c2410c";

/* ---------- mapa ---------- */
const map = L.map("map", { preferCanvas: true }).setView([39.9526, -75.1652], 14);   // centro de Filadelfia
const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a>",
}).addTo(map);
let tileErrors = 0;
tiles.on("tileerror", () => { if (++tileErrors > 3) $("notice").hidden = false; });
tiles.on("tileload", () => { tileErrors = 0; $("notice").hidden = true; });

const results = L.layerGroup().addTo(map);   // negocios
const overlay = L.layerGroup().addTo(map);   // centro, círculo, celdas
const drawn = new L.FeatureGroup().addTo(map);

/* ---------- llamada a la API + panel de JSON crudo ---------- */
let lastUrl = "";
const inflight = {};
async function api(path, { method = "GET", body, key } = {}) {
  const url = location.origin + path;
  const t0 = performance.now();
  lastUrl = url;
  $("raw-url").textContent = method + " " + path;
  $("raw-url").title = $("raw-url").textContent;
  $("raw-open").hidden = method !== "GET";
  if (method === "GET") $("raw-open").href = url;
  $("raw-meta").textContent = "consultando…";
  let signal;
  if (key) { inflight[key]?.abort(); const ac = (inflight[key] = new AbortController()); signal = ac.signal; }
  const res = await fetch(url, { method, signal, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  const text = await res.text();
  const ms = Math.round(performance.now() - t0);
  let data = null;
  try { data = JSON.parse(text); } catch { /* respuesta no JSON */ }
  let meta = `HTTP ${res.status} · ${ms} ms · ${fmt(text.length)} bytes`;
  if (method === "POST") meta += `\ncurl -X POST -H "Content-Type: application/json" -d '${JSON.stringify(body)}' "${url}"`;
  $("raw-meta").textContent = meta;
  const pretty = data ? JSON.stringify(data, null, 2) : text;
  const LIM = 40000;
  $("raw-body").textContent = pretty.length > LIM ? pretty.slice(0, LIM) + `\n… (${fmt(pretty.length - LIM)} caracteres más; usa "Abrir" para verlo completo)` : pretty;
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

$("raw-copy").onclick = () => {
  const txt = $("raw-url").textContent.startsWith("POST") ? $("raw-meta").textContent.split("\n")[1] || "" : lastUrl;
  navigator.clipboard?.writeText(txt);
  $("raw-copy").textContent = "Copiado";
  setTimeout(() => ($("raw-copy").textContent = "Copiar URL"), 1200);
};

function fail(err) {
  if (err.name === "AbortError") return;
  $("summary").innerHTML = `<span class="warn">Error: ${esc(err.message)}</span>`;
  $("list").innerHTML = "";
}
const clearOut = () => { $("summary").innerHTML = ""; $("list").innerHTML = ""; };

/* ---------- pestañas ---------- */
let tab = "near";
function setTab(name) {
  tab = name;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== "tab-" + name));
  results.clearLayers(); overlay.clearLayers(); drawn.clearLayers(); clearOut();
  map.off("click", onMapClick);
  name === "within" ? map.addControl(drawCtl) : map.removeControl(drawCtl);
  if (name === "near") { map.on("click", onMapClick); drawCenter(); runNear(); }
  if (name === "closure") runClosure();
}
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => setTab(b.dataset.tab)));

/* ---------- negocios: marcadores y lista ---------- */
const years = (d) => (d / 365).toFixed(1);
function popup(p) {
  const l = p.life || {};
  const estado = p.is_open ? "abierto" : "cerrado";
  return `<b>${esc(p.name)}</b><br>${esc(p.main_category || "")} · ${esc(p.city || "")}<br>` +
    `<span class="m">★ ${p.stars} · ${fmt(p.review_count)} reseñas · ${estado}</span>` +
    (l.business_days != null ? `<br><span class="m">${years(l.business_days)} años de vida observados${l.closed ? " · cierre" : l.censored ? " · censurado" : ""}</span>` : "");
}
function plot(features, fit) {
  results.clearLayers();
  const list = $("list"); list.innerHTML = "";
  const pts = [];
  features.forEach((f, i) => {
    const [lon, lat] = f.geometry.coordinates, p = f.properties;
    const c = p.is_open ? OPEN : CLOSED;
    pts.push([lat, lon]);
    const m = L.circleMarker([lat, lon], { radius: 6, color: "#fff", weight: 1.5, fillColor: c, fillOpacity: 0.95 }).bindPopup(popup(p));
    m.addTo(results);
    if (i < 60) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="dot" style="background:${c}"></span><span class="nm">${esc(p.name)}</span><span class="mt">★ ${p.stars}</span>`;
      li.onclick = () => { map.panTo([lat, lon]); m.openPopup(); };
      list.appendChild(li);
    }
  });
  if (fit && pts.length) map.fitBounds(pts, { padding: [40, 40], maxZoom: 17 });
}
function catOpt(key) { return key ? `&category=${encodeURIComponent(key)}` : ""; }

/* ---------- pestaña: cerca ---------- */
let center = { lat: 39.9526, lng: -75.1652 }, circle = null;
function drawCenter() {
  overlay.clearLayers();
  $("n-center").value = `${center.lat.toFixed(5)}, ${center.lng.toFixed(5)}`;
  const mk = L.marker([center.lat, center.lng], { draggable: true }).addTo(overlay);
  mk.on("dragend", () => { const p = mk.getLatLng(); center = { lat: p.lat, lng: p.lng }; drawCenter(); runNear(); });
  circle = L.circle([center.lat, center.lng], { radius: +$("n-radius").value, color: ACCENT, weight: 1.5, fillOpacity: 0.06, interactive: false }).addTo(overlay);
}
function onMapClick(e) { center = { lat: e.latlng.lat, lng: e.latlng.lng }; drawCenter(); runNear(); }
$("n-radius").oninput = () => {
  const v = +$("n-radius").value;
  $("n-radius-o").textContent = v >= 1000 ? (v / 1000).toFixed(1).replace(".0", "") + " km" : v + " m";
  circle && circle.setRadius(v);
};
["n-radius", "n-cat", "n-limit"].forEach((id) => ($(id).onchange = () => runNear()));
$("n-go").onclick = () => runNear();

async function runNear() {
  const base = `lat=${center.lat.toFixed(6)}&lon=${center.lng.toFixed(6)}&radius=${$("n-radius").value}`;
  try {
    const d = await api(`/businesses/near?${base}&limit=${$("n-limit").value}${catOpt($("n-cat").value.trim())}`, { key: "biz" });
    plot(d.features);
    $("summary").innerHTML = d.count ? `<b>${fmt(d.count)}</b> negocios a ≤ ${fmt($("n-radius").value)} m` +
      (d.count >= +$("n-limit").value ? ` <span class="warn">· tope de ${$("n-limit").value} alcanzado</span>` : "")
      : "Sin negocios en ese radio. Prueba un radio mayor o el centro de Filadelfia.";
    const z = await api(`/zones/summary?${base}`, { key: "zone" });   // $geoNear: resumen de toda la zona, sin límite
    $("zone").innerHTML = z.businesses
      ? `<div>Negocios en la zona<b>${fmt(z.businesses)}</b></div><div>Estrellas promedio<b>${z.avg_stars}</b></div>` +
        `<div>Reseñas negativas<b>${z.pct_negative ?? "—"}%</b></div>` +
        `<div>Tasa de cierre<b>${z.closure_rate_pct != null ? fmt(z.closure_rate_pct, 2) + "%" : "—"}</b></div>`
      : "";
  } catch (e) { fail(e); }
}

/* ---------- pestaña: zona ---------- */
const drawCtl = new L.Control.Draw({
  draw: { polygon: { allowIntersection: false, shapeOptions: { color: "#0f766e" } }, rectangle: { shapeOptions: { color: "#0f766e" } },
          polyline: false, circle: false, marker: false, circlemarker: false },
  edit: { featureGroup: drawn, edit: false },
});
let lastPoly = null;
map.on(L.Draw.Event.CREATED, (e) => {
  if (tab !== "within") return;
  drawn.clearLayers(); drawn.addLayer(e.layer);
  const ring = e.layer.getLatLngs()[0].map((p) => [+p.lng.toFixed(6), +p.lat.toFixed(6)]);
  ring.push(ring[0]);
  lastPoly = { type: "Polygon", coordinates: [ring] };
  runWithin();
});
map.on(L.Draw.Event.DELETED, () => { lastPoly = null; results.clearLayers(); clearOut(); });
["w-cat", "w-limit"].forEach((id) => ($(id).onchange = () => lastPoly && runWithin()));
$("w-clear").onclick = () => { drawn.clearLayers(); results.clearLayers(); lastPoly = null; clearOut(); };

async function runWithin() {
  try {
    const d = await api(`/businesses/within?limit=${$("w-limit").value}${catOpt($("w-cat").value.trim())}`,
      { method: "POST", body: { polygon: lastPoly }, key: "biz" });
    plot(d.features);
    $("summary").innerHTML = `<b>${fmt(d.count)}</b> negocios dentro de la zona` +
      (d.count >= +$("w-limit").value ? ` <span class="warn">· tope de ${$("w-limit").value} alcanzado</span>` : "");
  } catch (e) { fail(e); }
}

/* ---------- pestaña: cierre ---------- */
let by = "category";
document.querySelectorAll("#c-by button").forEach((b) => (b.onclick = () => {
  by = b.dataset.by;
  document.querySelectorAll("#c-by button").forEach((x) => x.classList.toggle("on", x === b));
  runClosure();
}));
["c-min", "c-order", "c-limit"].forEach((id) => ($(id).onchange = () => runClosure()));
$("c-go").onclick = () => runClosure();

/* geohash -> rectángulo [[sur, oeste], [norte, este]] */
const B32 = "0123456789bcdefghjkmnpqrstuvwxyz";
function geohashBox(h) {
  let lat = [-90, 90], lon = [-180, 180], even = true;
  for (const ch of h) {
    const v = B32.indexOf(ch);
    for (let b = 4; b >= 0; b--) {
      const rng = even ? lon : lat, mid = (rng[0] + rng[1]) / 2;
      (v >> b) & 1 ? (rng[0] = mid) : (rng[1] = mid);
      even = !even;
    }
  }
  return [[lat[0], lon[0]], [lat[1], lon[1]]];
}

async function runClosure() {
  results.clearLayers(); overlay.clearLayers(); clearOut();
  const q = new URLSearchParams({ by, min_days: $("c-min").value, order: $("c-order").value, limit: $("c-limit").value });
  try {
    const d = await api(`/stats/closure?${q}`, { key: "closure" });
    const list = $("list");
    const max = Math.max(0.0001, ...d.results.map((r) => r.closure_rate_pct));
    const boxes = [];
    d.results.forEach((r, i) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="nm">${esc(r.key)}</span><span class="mt">${fmt(r.closure_rate_pct, 2)}% · ${fmt(r.businesses)} neg.</span>`;
      const tip = `<b>${esc(r.key)}</b><br>Tasa de cierre: <b>${fmt(r.closure_rate_pct, 2)}%</b><br>` +
        `<span class="m">${fmt(r.closures)} cierres · ${fmt(r.businesses)} negocios · ${fmt(r.business_days)} días-negocio<br>${fmt(r.pct_negative, 1)}% reseñas negativas</span>`;
      if (by === "geohash") {
        const box = geohashBox(r.key);
        const rect = L.rectangle(box, { color: ACCENT, weight: 1, fillColor: ACCENT, fillOpacity: 0.12 + 0.6 * (r.closure_rate_pct / max) })
          .bindPopup(tip).addTo(overlay);
        boxes.push(box[0], box[1]);
        li.onclick = () => { map.fitBounds(box, { maxZoom: 15 }); rect.openPopup(); };
      } else {
        li.style.display = "grid"; li.style.gridTemplateColumns = "1fr auto";
        li.innerHTML += `<span class="bar" style="grid-column:1/3;height:5px;border-radius:3px;background:${ACCENT};opacity:.7;width:${(100 * r.closure_rate_pct / max).toFixed(0)}%"></span>`;
        li.title = "Clic: ver estos negocios en el mapa";
        li.onclick = () => { $("n-cat").value = r.key; $("w-cat").value = r.key; setTab("near"); };
      }
      list.appendChild(li);
    });
    $("summary").innerHTML = `<b>${fmt(d.count)}</b> ${by === "geohash" ? "zonas" : "categorías"} con ≥ ${fmt(d.min_days)} días-negocio` +
      (by === "category" ? `<br><span class="hint">Clic en una categoría para verla en el mapa.</span>` : "");
    if (boxes.length) map.fitBounds(boxes, { padding: [30, 30] });
  } catch (e) { fail(e); }
}

/* ---------- pestaña: sentimiento ---------- */
$("s-go").onclick = async () => {
  const out = $("s-out");
  out.innerHTML = "Clasificando…";
  try {
    const d = await api("/predict", { method: "POST", body: { text: $("s-text").value } });
    const names = { negative: ["Negativo", "neg"], neutral: ["Neutral", "neu"], positive: ["Positivo", "pos"] };
    out.innerHTML = `<p style="margin:0 0 6px">Predicción: <b>${names[d.sentiment][0]}</b></p>` +
      Object.keys(names).map((k) => `<div class="prob ${names[k][1]}"><span>${names[k][0]}</span>` +
        `<span class="track"><span class="fill" style="width:${(100 * d.probabilities[k]).toFixed(1)}%"></span></span>` +
        `<span class="v">${(100 * d.probabilities[k]).toFixed(1)}%</span></div>`).join("");
  } catch (e) { out.innerHTML = `<span class="warn" style="color:var(--accent)">Error: ${esc(e.message)}</span>`; }
};

/* ---------- inicio ---------- */
(async function init() {
  try {
    const h = await fetch("/health").then((r) => r.json());
    $("health").textContent = h.status === "ok" ? "API y servicios activos" : "servicio caído";
    $("health").className = "health " + (h.status === "ok" ? "ok" : "bad");
    $("health").title = "commit " + h.commit;
  } catch { $("health").textContent = "API sin respuesta"; $("health").className = "health bad"; }
  setTab("near");
  try {   // sugerencias de categoría: las de más días-negocio
    const d = await fetch("/stats/closure?by=category&min_days=50000&limit=100").then((r) => r.json());
    $("cats").innerHTML = d.results.map((r) => `<option value="${esc(r.key)}">`).join("");
  } catch { /* sin sugerencias */ }
})();
