/* Panel en vivo de LifeMap: consume los endpoints de esta misma API (/health, /live/*, /alerts, /survival) y se
   actualiza solo. Gráficas en SVG propio (sin librerías); mapa con Leaflet. */
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 0) => (n == null ? "—" : Number(n).toLocaleString("es-CO", { maximumFractionDigits: d }));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const PALETA = ["#2a78d6", "#eb6834", "#7d8e12", "#9c6ade", "#c24b86"];

async function cargarSalud() {   // /health responde 503 si falta algún servicio (p. ej. Spark apagado), pero el cuerpo sigue siendo útil
  const r = await fetch("/health", { headers: { Accept: "application/json" } });
  return r.json();
}

async function get(path) {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(path + " → " + r.status);
  return r.json();
}

/* ---------- mapa ---------- */
const map = L.map("map", { preferCanvas: true }).setView([39.99, -75.15], 10);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18, attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a>",
}).addTo(map);
const capaCeldas = L.layerGroup().addTo(map), capaAlertas = L.layerGroup().addTo(map);
let encuadrado = false;

function mezcla(a, b, t) {   // interpola dos colores #rrggbb
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

function pintarMapa(celdas, alertas) {
  capaCeldas.clearLayers(); capaAlertas.clearLayers();
  const maxP = Math.max(30, ...celdas.map((c) => c.pct_negative || 0));
  for (const c of celdas) {
    if (!c.geometry) continue;
    const t = Math.min(1, (c.pct_negative || 0) / maxP);
    L.geoJSON(c.geometry, {
      style: { color: c.hotspot ? "#eb6834" : "#6c685c", weight: c.hotspot ? 3 : 1, fillColor: mezcla("#2a78d6", "#eb6834", t), fillOpacity: 0.45 },
    }).bindTooltip(`<b>${esc(c.geohash)}</b><br>${fmt(c.n)} reseñas · ${fmt(c.pct_negative, 1)} % negativo` +
      (c.delta_pp != null ? `<br>cambio: ${c.delta_pp > 0 ? "+" : ""}${fmt(c.delta_pp, 1)} pp` : "") + (c.hotspot ? "<br><b>HOTSPOT</b>" : "")).addTo(capaCeldas);
  }
  for (const a of alertas) {
    L.circleMarker([a.lat, a.lon], { radius: 4 + 6 * a.probability, color: "#fff", weight: 1, fillColor: "#7a1f5c", fillOpacity: 0.85 })
      .bindTooltip(`<b>${esc(a.name)}</b><br>${esc(a.main_category || "")}<br>riesgo de cierre: ${fmt(a.probability * 100, 0)} %`).addTo(capaAlertas);
  }
  if (!encuadrado && celdas.length) {
    const pts = celdas.filter((c) => c.lat != null).map((c) => [c.lat, c.lon]);
    if (pts.length) { map.fitBounds(L.latLngBounds(pts).pad(0.15)); encuadrado = true; }
  }
}

/* ---------- gráficas SVG ---------- */
function ejeY(maxV, W, H, m, etiqueta) {
  let s = "";
  for (let i = 0; i <= 4; i++) {
    const y = H - m.b - ((H - m.t - m.b) * i) / 4, v = (maxV * i) / 4;
    s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}" stroke="${css("--line")}"/><text x="${m.l - 6}" y="${y + 4}" text-anchor="end" font-size="11" fill="${css("--muted")}">${fmt(v, maxV < 10 ? 1 : 0)}${etiqueta}</text>`;
  }
  return s;
}

function graficaTendencia(filas, ventana) {
  if (!filas.length) { $("trend").innerHTML = '<p class="empty">Sin ventanas todavía: el streaming no ha recibido reseñas.</p>'; return; }
  const W = 560, H = 280, m = { l: 44, r: 44, t: 14, b: 48 };
  const maxP = Math.max(10, ...filas.map((f) => f.pct_negative || 0)) * 1.15, maxH = Math.max(1, ...filas.map((f) => f.hotspots));
  const bw = ((W - m.l - m.r) / filas.length) * 0.6, paso = (W - m.l - m.r) / filas.length;
  const x = (i) => m.l + paso * i + paso / 2, yP = (v) => H - m.b - ((H - m.t - m.b) * v) / maxP, yH = (v) => H - m.b - ((H - m.t - m.b) * v) / maxH;
  let s = ejeY(maxP, W, H, m, "%");
  filas.forEach((f, i) => {
    const sel = f.window_start === ventana;
    s += `<rect x="${x(i) - bw / 2}" y="${yH(f.hotspots)}" width="${bw}" height="${H - m.b - yH(f.hotspots)}" fill="${css("--orange")}" opacity="${sel ? 0.75 : 0.35}"><title>${f.hotspots} hotspots</title></rect>`;
    if (filas.length <= 14 || i % 2 === 0)
      s += `<text x="${x(i)}" y="${H - m.b + 14}" text-anchor="middle" font-size="10" fill="${css("--muted")}" transform="rotate(35 ${x(i)} ${H - m.b + 14})">${f.window_start.slice(0, 10)}</text>`;
  });
  s += `<polyline fill="none" stroke="${css("--blue")}" stroke-width="2.5" points="${filas.map((f, i) => `${x(i)},${yP(f.pct_negative || 0)}`).join(" ")}"/>`;
  filas.forEach((f, i) => { s += `<circle cx="${x(i)}" cy="${yP(f.pct_negative || 0)}" r="3.5" fill="${css("--blue")}"><title>${f.window_start.slice(0, 10)}: ${fmt(f.pct_negative, 1)} % de ${fmt(f.n)} reseñas</title></circle>`; });
  s += `<text x="${W - m.r + 6}" y="${m.t + 4}" font-size="11" fill="${css("--orange")}">máx. ${maxH}</text>`;
  s += `<text x="${m.l}" y="8" font-size="11" fill="${css("--muted")}">línea azul: % negativo · columnas: hotspots (eje derecho)</text>`;
  $("trend").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="% negativo y hotspots por ventana">${s}</svg>`;
}

function graficaSupervivencia(id, curvas) {
  const con = curvas.filter((c) => c.curve && c.curve.length);
  if (!con.length) { $(id).innerHTML = '<p class="empty">Sin curvas calculadas (corre el paso de supervivencia).</p>'; return; }
  const W = 560, H = 310, m = { l: 44, r: 12, t: 14, b: 84 };
  const tmax = Math.max(...con.map((c) => c.curve[c.curve.length - 1].t)) / 365;
  const x = (t) => m.l + ((W - m.l - m.r) * (t / 365)) / tmax, y = (v) => H - m.b - (H - m.t - m.b) * v;
  let s = "";
  for (let i = 0; i <= 4; i++) {
    const v = i / 4;
    s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="${css("--line")}"/><text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="${css("--muted")}">${fmt(v * 100)}%</text>`;
  }
  for (let a = 0; a <= tmax; a += tmax > 12 ? 4 : 2)
    s += `<text x="${x(a * 365)}" y="${H - m.b + 14}" text-anchor="middle" font-size="11" fill="${css("--muted")}">${a} a</text>`;
  s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(0.5)}" y2="${y(0.5)}" stroke="${css("--muted")}" stroke-dasharray="4 4"/>`;
  con.forEach((c, i) => {
    const col = PALETA[i % PALETA.length];
    const pts = c.curve.map((p) => `${x(p.t)},${y(p.s)}`);
    const banda = c.curve.map((p) => `${x(p.t)},${y(p.hi)}`).concat(c.curve.slice().reverse().map((p) => `${x(p.t)},${y(p.lo)}`)).join(" ");
    s += `<polygon points="${banda}" fill="${col}" opacity="0.12"/><polyline fill="none" stroke="${col}" stroke-width="2.4" points="${pts.join(" ")}"><title>${esc(c.nombre)}: ${fmt(c.n)} negocios, ${fmt(c.events)} cierres</title></polyline>`;
    const lx = m.l + (i % 2) * 250, ly = H - 34 + Math.floor(i / 2) * 14;
    s += `<rect x="${lx}" y="${ly - 8}" width="10" height="10" rx="2" fill="${col}"/><text x="${lx + 14}" y="${ly + 1}" font-size="11" fill="${css("--ink")}">${esc(c.nombre.slice(0, 22))} (n=${fmt(c.n)}${c.median_years ? `, med ${fmt(c.median_years, 1)} a` : ""})</text>`;
  });
  s += `<text x="${(W + m.l) / 2}" y="${H - m.b + 28}" text-anchor="middle" font-size="11" fill="${css("--muted")}">años desde la primera reseña · banda = IC 95 % · línea punteada = 50 %</text>`;
  $(id).innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Curvas de supervivencia">${s}</svg>`;
}

/* ---------- carga ---------- */
let ventanaElegida = null, supervivenciaCargada = false;

async function curvas(dimension, ruta, max) {
  const lista = (await get(`/survival?dimension=${dimension}&limit=${max}`)).results;
  const nombre = (r) => r[dimension === "zone" ? "zone" : "category"];
  const det = await Promise.all(lista.map((r) => get(ruta + encodeURIComponent(nombre(r))).then((d) => ({ ...d, nombre: nombre(r) })).catch(() => null)));
  return det.filter(Boolean);
}

async function actualizar() {
  try {
    const [salud, tendencia] = await Promise.all([cargarSalud().catch(() => null), get("/live/trend")]);
    const filas = tendencia.results, sel = $("win");
    if (!ventanaElegida && filas.length) ventanaElegida = filas[filas.length - 1].window_start;
    const previa = sel.value;
    sel.innerHTML = filas.map((f) => `<option value="${esc(f.window_start)}">${esc(f.window_start.slice(0, 10))}</option>`).join("");
    sel.value = filas.some((f) => f.window_start === (previa || ventanaElegida)) ? (previa || ventanaElegida) : ventanaElegida;
    ventanaElegida = sel.value || null;

    const q = ventanaElegida ? `?window=${ventanaElegida.slice(0, 10)}&limit=500` : "?limit=500";
    const [celdas, alertas] = await Promise.all([get("/live/hotspots" + q), get("/alerts?limit=100")]);

    const st = salud && salud.streaming ? salud.streaming : {};
    const ok = st.status === "up";
    $("k-estado").textContent = st.status || (salud ? "—" : "sin conexión"); $("k-estado").className = ok ? "ok" : "bad";
    $("k-lag").textContent = st.consumer_lag == null ? "—" : fmt(st.consumer_lag);
    const hot = celdas.results.filter((c) => c.hotspot).length;
    $("k-hot").textContent = fmt(hot);
    $("k-alert").textContent = fmt(alertas.count);
    $("k-n").textContent = fmt(filas.reduce((a, f) => a + f.n, 0));
    $("map-note").textContent = ventanaElegida ? `ventana desde ${ventanaElegida.slice(0, 10)} · ${celdas.count} celdas` : "";

    pintarMapa(celdas.results, alertas.results);
    graficaTendencia(filas, ventanaElegida);
    $("alerts").querySelector("tbody").innerHTML = alertas.results.length ? alertas.results.map((a) => {
      const f = a.features || {};
      return `<tr><td>${esc(a.name)}</td><td>${esc(a.main_category)}</td><td class="num"><span class="bar" style="width:${Math.round(a.probability * 60)}px"></span>${fmt(a.probability * 100, 1)} %</td>` +
        `<td class="num">${fmt(f.pct_neg_6m, 0)} %</td><td class="num">${fmt(f.days_since_last)}</td><td>${esc((a.as_of || "").slice(0, 10))}</td></tr>`;
    }).join("") : '<tr><td colspan="6" class="empty">Sin alertas vigentes.</td></tr>';

    if (!supervivenciaCargada) {   // las curvas no cambian con el flujo: se piden una vez
      const [cat, zona] = await Promise.all([curvas("category", "/survival/", 4), curvas("zone", "/survival/zone/", 5)]);
      graficaSupervivencia("surv-cat", cat); graficaSupervivencia("surv-zone", zona);
      supervivenciaCargada = true;
    }
    estadoReproduccion();
    $("err").hidden = true;
    $("stamp").textContent = "actualizado " + new Date().toLocaleTimeString("es-CO");
  } catch (e) {
    $("err").hidden = false; $("err").textContent = "No se pudo actualizar: " + e.message;
  }
}

/* ---------- botón: reproducir el flujo ---------- */
const FASES = { idle: "listo para reproducir", reiniciando: "reiniciando el flujo (vaciando topic, checkpoint y colecciones)…", publicando: "publicando reseñas en Kafka…", terminado: "reproducción terminada", error: "error" };
async function estadoReproduccion() {
  try {
    const r = await fetch("/replay"), d = await r.json();
    const activo = d.phase === "reiniciando" || d.phase === "publicando";
    $("replay-go").disabled = activo;
    $("replay-state").className = "rstate" + (d.phase === "error" || !r.ok ? " bad" : "");
    $("replay-state").textContent = !r.ok ? (d.error || "controlador no disponible") :
      (FASES[d.phase] || d.phase) + (d.elapsed_s != null ? ` · ${d.elapsed_s} s` : "") + (d.phase === "error" ? ": " + d.error : "");
  } catch (e) { $("replay-state").textContent = "sin conexión con la API"; }
}
$("replay-go").addEventListener("click", async () => {
  $("replay-go").disabled = true;
  const r = await fetch("/replay", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ seconds_per_month: Number($("replay-speed").value) }) });
  if (!r.ok) { const d = await r.json().catch(() => ({})); $("replay-state").className = "rstate bad"; $("replay-state").textContent = d.error || "no se pudo iniciar"; $("replay-go").disabled = false; return; }
  ventanaElegida = null; encuadrado = false;   // al terminar el reinicio, seguir la ventana más reciente
  estadoReproduccion(); actualizar();
});

$("win").addEventListener("change", () => { ventanaElegida = $("win").value; actualizar(); });
let reloj = null;
function programar() { clearInterval(reloj); if ($("auto").checked) reloj = setInterval(actualizar, 5000); }
$("auto").addEventListener("change", programar);
actualizar(); programar();
setTimeout(() => map.invalidateSize(), 300);
