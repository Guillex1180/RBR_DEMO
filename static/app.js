const API = "/api/v1";
const SCEN_LABELS = { SEAT_CHANGE: "Seat Change", CREDIT_SHELL: "Credit Shell", VOUCHERS: "Vouchers", NAME_CHANGE_FEE: "Name Change Fee", NONE: "Conciliado" };
const FAMILY_COLORS = { SEAT_CHANGE: "#0a84ff", CREDIT_SHELL: "#d7a419", VOUCHERS: "#6c5ce7", NAME_CHANGE_FEE: "#d64545", NONE: "#1a9d64" };
let lastPnrs = [];

// ---------- Login ----------
function doLogin(e) {
  e.preventDefault();
  const u = document.getElementById("user").value.trim();
  const p = document.getElementById("pass").value;
  if (u === "admin" && p === "rbr2026") {
    document.getElementById("login").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");
    loadAll();
  } else {
    document.getElementById("loginErr").textContent = "Credenciales inválidas. Usa admin / rbr2026.";
  }
}
function logout() {
  document.getElementById("app").classList.add("hidden");
  document.getElementById("login").classList.remove("hidden");
}

// ---------- Clock ----------
function tick() { const el = document.getElementById("clock"); if (el) el.textContent = new Date().toLocaleString("es-ES"); }
setInterval(tick, 1000); tick();

const money = n => "$" + Number(n || 0).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// ---------- Metrics ----------
async function loadMetrics() {
  const m = await (await fetch(`${API}/metrics`)).json();
  document.getElementById("m-total").textContent = m.total_pnrs;
  document.getElementById("m-balanced").textContent = m.balanced;
  document.getElementById("m-balanced-sub").textContent = `${((m.balanced / (m.total_pnrs || 1)) * 100).toFixed(0)}% del total`;
  document.getElementById("m-unbalanced").textContent = m.unbalanced;
  document.getElementById("m-rate").textContent = m.success_rate + "%";
  document.getElementById("m-revenue").textContent = money(m.pending_revenue_usd);
  document.getElementById("verBadge").textContent = "v" + m.version;
  drawTrend(m);
  drawScenarios(m.by_scenario || []);
}

// ---------- Charts (SVG puro) ----------
function drawTrend(m) {
  // Serie sintetica de progreso de balanceo hacia la tasa de exito actual
  const rate = m.success_rate;
  const pts = [Math.max(0, rate - 28), rate - 20, rate - 11, rate - 6, rate - 2, rate];
  const W = 420, H = 180, pad = 28;
  const maxY = 100;
  const stepX = (W - pad * 2) / (pts.length - 1);
  const coords = pts.map((v, i) => [pad + i * stepX, H - pad - (v / maxY) * (H - pad * 2)]);
  const line = coords.map((c, i) => (i ? "L" : "M") + c[0].toFixed(1) + " " + c[1].toFixed(1)).join(" ");
  const area = `${line} L ${coords[coords.length-1][0].toFixed(1)} ${H-pad} L ${pad} ${H-pad} Z`;
  const grid = [0,25,50,75,100].map(g => { const y = H - pad - (g/maxY)*(H-pad*2); return `<line x1="${pad}" y1="${y}" x2="${W-pad}" y2="${y}" stroke="#eef2f8"/><text x="4" y="${y+3}" font-size="9" fill="#9aa7bb">${g}</text>`; }).join("");
  const dots = coords.map(c => `<circle cx="${c[0].toFixed(1)}" cy="${c[1].toFixed(1)}" r="3.5" fill="#0a84ff"/>`).join("");
  document.getElementById("chart-trend").innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}">
      <defs><linearGradient id="g1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0a84ff" stop-opacity="0.28"/><stop offset="1" stop-color="#0a84ff" stop-opacity="0"/></linearGradient></defs>
      ${grid}
      <path d="${area}" fill="url(#g1)"/>
      <path d="${line}" fill="none" stroke="#0a84ff" stroke-width="2.5"/>
      ${dots}
    </svg>
    <div class="legend"><span><i style="background:#0a84ff"></i>Tasa de éxito acumulada (%)</span></div>`;
}

function drawScenarios(byScenario) {
  const el = document.getElementById("chart-scenarios");
  if (!byScenario.length) { el.innerHTML = `<div style="color:var(--muted);font-size:13px;">Sin desbalances 🎉</div>`; return; }
  const top = byScenario.slice(0, 8);
  const max = Math.max(...top.map(s => s.count));
  const barW = 34, gap = 14, H = 180, pad = 24;
  const W = pad * 2 + top.length * (barW + gap);
  const bars = top.map((s, i) => {
    const h = (s.count / max) * (H - pad * 2);
    const x = pad + i * (barW + gap);
    const y = H - pad - h;
    const col = FAMILY_COLORS[s.family] || "#0a84ff";
    return `<rect x="${x}" y="${y}" width="${barW}" height="${h}" rx="5" fill="${col}"/>
            <text x="${x + barW/2}" y="${y - 5}" font-size="10" font-weight="700" fill="#16233a" text-anchor="middle">${s.count}</text>
            <text x="${x + barW/2}" y="${H - pad + 13}" font-size="9" fill="#6b7a90" text-anchor="middle">#${s.scenario_id}</text>`;
  }).join("");
  const fams = [...new Set(top.map(s => s.family))];
  const legend = fams.map(f => `<span><i style="background:${FAMILY_COLORS[f]}"></i>${SCEN_LABELS[f] || f}</span>`).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="xMidYMid meet">${bars}</svg><div class="legend">${legend}</div>`;
}

// ---------- PNRs ----------
async function loadPnrs() {
  const qs = new URLSearchParams();
  const st = document.getElementById("f-status").value;
  const q = document.getElementById("f-queue").value;
  const fam = document.getElementById("f-family").value;
  if (st) qs.set("status", st);
  if (q) qs.set("queue", q);
  if (fam) qs.set("family", fam);
  const data = await (await fetch(`${API}/pnrs?${qs}`)).json();
  lastPnrs = data.pnrs;
  document.getElementById("pnr-count").textContent = `${data.count} resultados`;
  const tbody = document.getElementById("pnr-tbody");
  if (!data.pnrs.length) { tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:22px;">Sin resultados</td></tr>`; return; }
  tbody.innerHTML = data.pnrs.map(p => `
    <tr class="pnr-row" onclick="showTimeline('${p.pnr_id}')" title="Ver línea de tiempo del PNR">
      <td class="mono">${p.pnr_id}</td>
      <td>${p.passenger_name}</td>
      <td>${p.flight_number}<br><small style="color:var(--muted)">${p.flight_date}</small></td>
      <td title="${p.scenario_description}"><span class="pill" style="background:${hexA(FAMILY_COLORS[p.scenario_family],0.12)};color:${FAMILY_COLORS[p.scenario_family]}">#${p.scenario_id}</span></td>
      <td style="color:${p.pending_amount > 0 ? 'var(--red)' : (p.pending_amount < 0 ? 'var(--accent)' : 'var(--green)')};font-weight:600;">${money(p.pending_amount)}</td>
      <td><span class="pill ${p.balance_status === 'BALANCED' ? 'balanced' : 'unbalanced'}">${p.balance_status}</span></td>
      <td><span class="pill queue">${p.queue}</span></td>
      <td>${p.notes && p.notes.length ? `<span class="pill note" onclick="event.stopPropagation();showNotes('${p.pnr_id}')">${p.notes.length} 📝</span>` : '<span style="color:var(--muted)">—</span>'}</td>
    </tr>`).join("");
}
function hexA(hex, a) { const h = (hex||"#0a84ff").replace("#",""); const n = parseInt(h,16); return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`; }

function loadAll() { loadMetrics(); loadPnrs(); loadAlerts(); loadScenarioConfig(); }

// ---------- Notas modal ----------
function showNotes(pnrId) {
  const p = lastPnrs.find(x => x.pnr_id === pnrId);
  if (!p) return;
  document.getElementById("notesTitle").textContent = `Notas internas · PNR ${pnrId}`;
  document.getElementById("notesBody").innerHTML = (p.notes || []).map(n => `
    <div class="note-item"><div class="meta"><b>${n.author}</b> · ${n.created_at}</div>${n.note.replace(/</g,"&lt;")}</div>`).join("")
    || `<div style="color:var(--muted)">Sin notas.</div>`;
  document.getElementById("notesModal").classList.add("open");
}
function closeNotes() { document.getElementById("notesModal").classList.remove("open"); }
document.getElementById("notesModal").addEventListener("click", e => { if (e.target.id === "notesModal") closeNotes(); });

// ---------- RBCheck ----------
async function rbcheckBalance() {
  const pnr = document.getElementById("rbcheck-pnr").value.trim().toUpperCase();
  const box = document.getElementById("resultBox");
  if (pnr.length !== 6) { box.innerHTML = `<span class="err">El PNR debe tener 6 caracteres.</span>`; return; }
  box.innerHTML = `Balanceando ${pnr}…`;
  const d = await (await fetch(`${API}/agent/query`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role: "Operaciones", prompt: `Balancea el PNR ${pnr}` })
  })).json();
  box.innerHTML = `<span class="ok">✔</span> ${d.answer.replace(/</g,"&lt;")}`;
  loadAll();
}

// Balanceo masivo
function onBulkScopeChange() {
  const scope = document.getElementById("bulk-scope").value;
  const val = document.getElementById("bulk-value");
  if (scope === "all") { val.style.display = "none"; return; }
  val.style.display = "";
  val.placeholder = scope === "queue" ? "SLRCVR…" : (scope === "scenario" ? "3" : "SEAT_CHANGE");
}
async function runBulkBalance() {
  const scope = document.getElementById("bulk-scope").value;
  const value = document.getElementById("bulk-value").value.trim() || null;
  const box = document.getElementById("resultBox");
  box.innerHTML = "Ejecutando balanceo masivo…";
  try {
    const d = await (await fetch(`${API}/pnr/balance-bulk`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope, value, role: "Operaciones" })
    })).json();
    box.innerHTML = `<span class="ok">✔</span> ${d.answer.replace(/</g,"&lt;")}`;
    loadAll();
  } catch (err) { box.innerHTML = `<span class="err">✘ ${err.message}</span>`; }
}

const dz = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
dz.addEventListener("click", () => fileInput.click());
dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("drag"); });
dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
dz.addEventListener("drop", e => { e.preventDefault(); dz.classList.remove("drag"); if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]); });
fileInput.addEventListener("change", () => { if (fileInput.files.length) uploadFile(fileInput.files[0]); });

async function uploadFile(file) {
  const box = document.getElementById("resultBox");
  box.innerHTML = `Subiendo <b>${file.name}</b>…`;
  const fd = new FormData(); fd.append("file", file);
  try {
    const r = await fetch(`${API}/pnr/import`, { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "Error al importar");
    box.innerHTML = `<span class="ok">✔ Importación (${d.format})</span> · recibidos ${d.received}, insertados ${d.inserted}, actualizados ${d.updated}, omitidos ${d.skipped}.`;
    loadAll();
  } catch (err) { box.innerHTML = `<span class="err">✘ ${err.message}</span>`; }
}

// ---------- Asistente ----------
const fab = document.getElementById("rbrFab");
const chat = document.getElementById("rbrChat");
fab.addEventListener("click", () => {
  chat.classList.toggle("open");
  if (chat.classList.contains("open") && !document.getElementById("rbrMsgs").children.length) {
    botMsg("¡Hola! Soy el Asistente RBR. Selecciona tu rol y pídeme: montos pendientes, escenarios con más desbalance, PNRs en riesgo por el vuelo, balancear un PNR (ej. «Balancea el PNR HX982A»), o agregar notas (ej. «Agregar nota al PNR AMX101: Revisión por contracargo»).");
  }
});
function botMsg(text, meta) {
  const d = document.createElement("div"); d.className = "msg bot";
  d.innerHTML = text.replace(/</g,"&lt;") + (meta ? `<div class="meta">${meta}</div>` : "");
  const box = document.getElementById("rbrMsgs"); box.appendChild(d); box.scrollTop = box.scrollHeight;
}
function userMsg(text, role) {
  const d = document.createElement("div"); d.className = "msg user";
  d.innerHTML = text.replace(/</g,"&lt;") + `<div class="meta">${role}</div>`;
  const box = document.getElementById("rbrMsgs"); box.appendChild(d); box.scrollTop = box.scrollHeight;
}
function quickAsk(q) { if (!chat.classList.contains("open")) fab.click(); document.getElementById("rbrInput").value = q; sendAgent(); }

async function sendAgent() {
  const input = document.getElementById("rbrInput");
  const msg = input.value.trim(); if (!msg) return;
  const role = document.getElementById("rbrRole").value;
  userMsg(msg, role); input.value = "";
  try {
    const d = await (await fetch(`${API}/agent/query`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, prompt: msg })
    })).json();
    botMsg(d.answer || "No tengo respuesta.", d.tool ? `${d.tool} · intent: ${d.intent}` : `intent: ${d.intent}`);
    if (["balance_pnr", "add_note"].includes(d.intent)) loadAll();
  } catch (err) { botMsg("Error al contactar el servidor: " + err.message); }
}

// ---------- Timeline modal (Módulo 2) ----------
async function showTimeline(pnrId) {
  const body = document.getElementById("tlBody");
  document.getElementById("tlTitle").textContent = `Línea de tiempo · PNR ${pnrId}`;
  body.innerHTML = "Cargando…";
  document.getElementById("timelineModal").classList.add("open");
  try {
    const d = await (await fetch(`${API}/pnr/${pnrId}/timeline`)).json();
    const p = d.pnr;
    const head = `<div style="margin-bottom:14px;font-size:13px;">
      <b>${p.passenger_name}</b> · ${p.flight_number} · ${p.route}<br>
      <span class="pill ${p.balance_status==='BALANCED'?'balanced':'unbalanced'}">${p.balance_status}</span>
      tarifa ${money(p.total_fare)} · pagado ${money(p.total_paid)} · pendiente ${money(p.pending_amount)}
    </div>`;
    const TYPE_LABEL = { CREATED:"Creación", PROCESS_ATTEMPT:"Procesamiento RBR", STATE_CHANGE:"Cambio de estado", NOTE:"Nota interna", BALANCED:"Conciliado" };
    const items = (d.events||[]).map(e => `
      <div class="tl-item ${e.event_type}">
        <div class="tl-head"><span class="tl-type">${TYPE_LABEL[e.event_type]||e.event_type}</span><span>${e.timestamp}</span></div>
        <div class="tl-desc">${(e.description||'').replace(/</g,'&lt;')}</div>
        <div class="tl-head"><span>por ${e.performed_by}</span></div>
      </div>`).join("");
    body.innerHTML = head + `<div class="tl">${items || '<span style="color:var(--muted)">Sin eventos.</span>'}</div>`;
  } catch (err) { body.innerHTML = `<span style="color:var(--red)">Error: ${err.message}</span>`; }
}
function closeTimeline() { document.getElementById("timelineModal").classList.remove("open"); }
document.getElementById("timelineModal").addEventListener("click", e => { if (e.target.id === "timelineModal") closeTimeline(); });
document.getElementById("execModal").addEventListener("click", e => { if (e.target.id === "execModal") e.currentTarget.classList.remove("open"); });

// ---------- Export (Módulo 3) ----------
function exportPnrs(fmt) { window.open(`${API}/pnrs/export?format=${fmt}`, "_blank"); }

// ---------- Resumen ejecutivo (Módulo 3) ----------
async function runExecutiveSummary() {
  const role = document.getElementById("rbrRole") ? document.getElementById("rbrRole").value : "Finanzas";
  document.getElementById("execBody").textContent = "Generando…";
  document.getElementById("execMode").textContent = "";
  document.getElementById("execModal").classList.add("open");
  try {
    const d = await (await fetch(`${API}/agent/executive-summary`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role })
    })).json();
    document.getElementById("execBody").textContent = d.answer;
    const mode = (d.data && d.data.mode) || "rules";
    document.getElementById("execMode").textContent = mode === "rules" ? "motor local" : mode;
  } catch (err) { document.getElementById("execBody").textContent = "Error: " + err.message; }
}

// ---------- Alertas tempranas por ruta (Módulo 4) ----------
async function loadAlerts() {
  const el = document.getElementById("alertBanner");
  try {
    const d = await (await fetch(`${API}/analytics/route-risk?threshold=15&min_pnrs=3`)).json();
    if (!d.routes || !d.routes.length) {
      el.innerHTML = `<div class="alert-banner ok"><span class="ico">✅</span><div>Sin rutas en riesgo. Ninguna ruta supera el ${d.threshold}% de reservas con error en 24h.</div></div>`;
    } else {
      const chips = d.routes.slice(0,8).map(r => `<span class="alert-chip">${r.route} · ${r.error_rate}% (${r.error_pnrs}/${r.total_pnrs})</span>`).join("");
      el.innerHTML = `<div class="alert-banner warn"><span class="ico">⚠️</span><div><b>Alerta temprana:</b> ${d.count} ruta(s) superan el umbral de riesgo del ${d.threshold}%.<div class="alert-routes">${chips}</div></div></div>`;
    }
  } catch (err) { el.innerHTML = ""; }
}

// ---------- Editor no-code de escenarios (Módulo 4) ----------
async function loadScenarioConfig() {
  const body = document.getElementById("scnBody");
  try {
    const d = await (await fetch(`${API}/scenarios/config`)).json();
    body.innerHTML = d.config.filter(c => c.scenario_id !== 0).map(c => `
      <tr class="${c.enabled ? '' : 'off'}" id="scn-${c.scenario_id}">
        <td class="mono">#${c.scenario_id}</td>
        <td title="${c.description}">${c.code}</td>
        <td><small>${c.family}</small></td>
        <td><input class="scn-input" type="number" min="0" step="10" value="${c.amount_threshold}" id="amt-${c.scenario_id}"></td>
        <td><input class="scn-input" type="number" min="0" step="1" value="${c.time_threshold_h}" id="tim-${c.scenario_id}"></td>
        <td>
          <label class="switch"><input type="checkbox" ${c.enabled?'checked':''} onchange="saveScenario(${c.scenario_id})"><span class="slider"></span></label>
          <button class="btn sm" style="margin-left:6px;padding:4px 8px;" onclick="saveScenario(${c.scenario_id})">Guardar</button>
        </td>
      </tr>`).join("");
    document.getElementById("scnStatus").textContent = `${d.count-1} reglas configurables`;
  } catch (err) { body.innerHTML = `<tr><td colspan="6" style="color:var(--red)">Error: ${err.message}</td></tr>`; }
}
async function saveScenario(sid) {
  const enabled = document.querySelector(`#scn-${sid} input[type=checkbox]`).checked;
  const amount_threshold = parseFloat(document.getElementById(`amt-${sid}`).value) || 0;
  const time_threshold_h = parseInt(document.getElementById(`tim-${sid}`).value) || 24;
  try {
    await fetch(`${API}/scenarios/config/${sid}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, amount_threshold, time_threshold_h })
    });
    const row = document.getElementById(`scn-${sid}`);
    row.classList.toggle("off", !enabled);
    document.getElementById("scnStatus").textContent = `Escenario #${sid} actualizado ✓`;
  } catch (err) { document.getElementById("scnStatus").textContent = "Error al guardar #" + sid; }
}

// ---------- Suite de Auditoría (20 preguntas) ----------
const AUDIT = {
  "Bloque 1 · Diagnóstico": [
    ["1.1", "Éxito últimas 24h y causas", "¿Cuál fue el porcentaje de éxito del RBR durante las últimas 24 horas y cuáles fueron las principales causas de fallo?"],
    ["1.2", "Conteo diario", "¿Cuántos PNR procesamos hoy y cuántos terminaron correctamente, con error o sin procesar?"],
    ["1.3", "Escenarios críticos", "¿Cuáles son los escenarios que están generando más errores actualmente?"],
    ["1.4", "Top 10 PNR con error", "Muéstrame los 10 PNR con más errores durante el día y explícame qué ocurrió en cada uno"],
    ["1.5", "Patrones de error", "¿Hay algún patrón común entre los errores ocurridos durante las últimas 24 horas?"],
  ],
  "Bloque 2 · Escenarios": [
    ["2.1", "Tasa más baja", "¿Qué escenario tiene actualmente la tasa de éxito más baja y qué errores lo provocan?"],
    ["2.2", "Auditoría escenario 7", "Para el escenario 7, ¿cuántos casos se procesaron correctamente y cuántos fallaron? ¿Cuál fue la causa?"],
    ["2.3", "Comparativo temporal", "Comparar el comportamiento del escenario 7 entre ayer y hoy indicando mejora o degradación"],
    ["2.4", "Anomalías", "¿Existe algún escenario que haya comenzado a fallar más que antes? ¿Cuándo comenzó el incremento?"],
    ["2.5", "Reintentos", "¿Qué escenarios están generando más reintentos y cuáles son las causas?"],
  ],
  "Bloque 3 · PNR / Pasajeros": [
    ["3.1", "Multipasajero", "Busca los PNR con múltiples pasajeros que presentaron errores. ¿Hay relación entre nº de pasajeros y fallos?"],
    ["3.2", "Bucles de proceso", "¿Hay algún PNR que esté siendo procesado repetidamente sin llegar a completarse?"],
    ["3.3", "Historial de intentos", "Muéstrame los PNR que tuvieron más de un intento de procesamiento"],
    ["3.4", "Estados inconsistentes", "¿Hay PNR que hayan quedado en un estado inconsistente después de que RBR intentara procesarlos?"],
    ["3.5", "Concentración por SSR", "¿Los errores están concentrados en algún código SSR particular como asientos o equipaje?"],
  ],
  "Bloque 4 · Balance / Deuda": [
    ["4.1", "Frecuencia de desbalance", "¿Cuáles son las transacciones que generan diferencias de balance con mayor frecuencia?"],
    ["4.2", "Balance ≠ 0", "Muéstrame los casos donde el balance terminó diferente de cero y qué transacciones lo provocaron"],
    ["4.3", "Códigos de transacción", "¿Qué códigos de transacción (TC, DD, AD, CC, CD, PC) aparecen más en los casos fallidos?"],
    ["4.4", "Tipos de deuda", "Identifica casos de deuda del cliente versus deuda de JetSMART/Aerolínea con ejemplos"],
    ["4.5", "Origen de fallo 7 días", "Analiza los errores de los últimos 7 días y clasifícalos en datos/PNR, internos de RBR o externos (Navitaire, token)"],
  ],
};

function renderAudit() {
  const grid = document.getElementById("auditGrid");
  const cols = Object.entries(AUDIT).map(([title, qs]) => `
    <div class="audit-col">
      <h4>${title}</h4>
      ${qs.map(([id, label, prompt]) =>
        `<button class="audit-q" onclick="auditAsk(this.dataset.p)" data-p="${prompt.replace(/"/g,'&quot;')}"><b>${id}</b> ${label}</button>`
      ).join("")}
    </div>`).join("");
  grid.innerHTML = `<div class="audit-blocks">${cols}</div>`;
}
function auditAsk(prompt) {
  if (!chat.classList.contains("open")) fab.click();
  document.getElementById("rbrInput").value = prompt;
  sendAgent();
}
// Reflejar el rol activo del asistente en el panel de auditoría
document.addEventListener("DOMContentLoaded", () => {
  renderAudit();
  const sel = document.getElementById("rbrRole");
  if (sel) sel.addEventListener("change", () => { document.getElementById("auditRole").textContent = sel.value; });
});
