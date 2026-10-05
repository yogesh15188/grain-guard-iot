/* GrainGuard frontend.
   The UI NEVER computes risk. It only renders what the deterministic engine
   returns and calls the scenario API. No scenario result is hardcoded here. */
'use strict';

const $ = (id) => document.getElementById(id);
const fmt = (v, nd = 1, dash = '—') =>
  (v === null || v === undefined || Number.isNaN(v)) ? dash : Number(v).toFixed(nd);
const RISK_CLASS = { 'LOW': 'risk-low', 'MEDIUM': 'risk-med', 'MEDIUM-HIGH': 'risk-high', 'HIGH': 'risk-high', 'CRITICAL': 'risk-crit' };
let LIMITS = {};
let SCENARIOS = [];
let activeScenario = null;

/* ---------------- theme ---------------- */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem('gg-theme', t);
}
function toggleTheme(btn) {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  setTheme(next);
  btn.classList.add('flip');
  setTimeout(() => btn.classList.remove('flip'), 420);
}

/* ---------------- IST clock ---------------- */
const IST = { timeZone: 'Asia/Kolkata' };
function tickClock() {
  const now = new Date();
  const time = now.toLocaleTimeString('en-GB', { ...IST, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const full = `${now.toLocaleDateString('en-GB', { ...IST, day: '2-digit', month: 'short', year: 'numeric' })} • ${time} IST`;
  $('clock').textContent = full;
  $('clock2').textContent = full;
}

/* ---------------- pipeline animation ---------------- */
function runPipeline() {
  const steps = [...document.querySelectorAll('.pstep')];
  steps.forEach((s) => s.classList.remove('done', 'active'));
  steps.forEach((s, i) => setTimeout(() => {
    steps.forEach((o) => o.classList.remove('active'));
    s.classList.add('active');
    setTimeout(() => s.classList.replace('active', 'done'), 420);
  }, 260 * (i + 1)));
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ---------------- SVG mimic ---------------- */
function paintMimic(f) {
  const rhLimit = LIMITS.rh_limit ?? 65;
  const emcLimit = LIMITS.emc_ingress ?? 14;
  const ldrLimit = LIMITS.ldr_anomaly ?? 700;
  const forkLow = LIMITS.fork_low ?? 300;
  const forkLoaded = LIMITS.fork_loaded ?? 600;
  const rh = f.rh, emc = f.emc_estimate, ldr = f.ldr_raw, fork = f.fork_raw;

  const air = $('mAir');
  let airFill = 'var(--safe-bg)';
  if (rh === null || rh === undefined) airFill = 'var(--surface2)';
  else if (rh > rhLimit + 5 || (emc != null && emc > emcLimit + 1)) airFill = 'var(--crit-bg)';
  else if (rh > rhLimit) airFill = 'var(--alert-bg)';
  air.style.fill = airFill;

  const dh = f.delta_height_cm;
  if (dh != null) {
    const top = Math.max(70, Math.min(150, 120 + dh * 4));
    $('mGrain').setAttribute('d', `M46 ${top} H274 V164 H46 Z`);
  }

  const ldrEl = $('mLdr'), shEl = $('mShutter'), dhtEl = $('mDht');
  ldrEl.classList.toggle('bad', ldr != null && ldr >= ldrLimit);
  ldrEl.classList.toggle('warn', ldr != null && ldr < ldrLimit && ldr >= ldrLimit * 0.6);
  shEl.classList.toggle('bad', rh != null && rh > rhLimit);
  dhtEl.classList.toggle('bad', rh != null && rh > rhLimit + 5);

  const probe = $('mProbe');
  if (fork != null) probe.style.stroke = fork < forkLow ? 'var(--crit)' : fork >= forkLoaded ? 'var(--ink2)' : 'var(--watch)';
}
/* ---------------- main render ---------------- */
function renderStatus(payload) {
  const r = payload.result;
  LIMITS = payload.limits || {};

  const pill = $('modePill');
  pill.textContent = payload.mode;
  pill.className = 'modepill ' + (payload.mode === 'OFFLINE' ? 'off'
    : payload.mode === 'SIMULATION' ? 'sim' : 'live');
  $('facilityName').textContent = (payload.facility && payload.facility.name) || 'Demo Rice Storage';

  const hw = $('hwFlag');
  const detail = payload.source_detail || '';
  if (/HARDWARE OFFLINE/i.test(detail)) {
    hw.textContent = 'HARDWARE OFFLINE — SIMULATION MODE';
    hw.className = 'hwflag';
  } else if (/connected/i.test(detail)) {
    hw.textContent = 'HARDWARE LIVE';
    hw.className = 'hwflag ok';
  } else {
    hw.textContent = 'MOCK TELEMETRY — SIMULATION MODE';
    hw.className = 'hwflag';
  }
  hw.title = detail;

  // While a scenario is held on screen, say so instead of letting the operator
  // wonder why the live mock numbers are not moving.
  if (payload.sim_hold_seconds > 0) {
    $('simNote').textContent = `Simulation held for ${Math.ceil(payload.sim_hold_seconds)}s so the result stays readable. Live mock telemetry resumes automatically.`;
  }

  if (!r) return;

  $('shState').textContent = r.headline || '—';
  $('shSub').textContent = r.plain_summary || '';
  $('shCode').textContent = r.state || '';

  $('riskValue').parentElement.className = 'riskbox ' + (RISK_CLASS[r.risk] || 'risk-low');
  $('riskValue').textContent = r.risk || '—';
  $('aerBox').className = 'aerbox ' + (r.aeration_allowed ? 'aer-ok' : 'aer-locked');
  $('aerValue').textContent = r.aeration_allowed ? 'AVAILABLE — HUMAN VERIFICATION REQUIRED' : 'LOCKED';

  /* metrics */
  const f = r.facts || {};
  $('vTemp').textContent = fmt(f.temp);
  $('vRh').textContent = fmt(f.rh);
  $('vEmc').textContent = fmt(f.emc_estimate);
  $('vDh').textContent = f.delta_height_cm == null ? '—'
    : (f.delta_height_cm > 0 ? '+' : '') + fmt(f.delta_height_cm);
  $('fDh').textContent = `baseline ${fmt(payload.baseline_cm)} cm`;

  const tL = LIMITS.temp_limit ?? 28, rhL = LIMITS.rh_limit ?? 65;
  const eL = LIMITS.emc_ingress ?? 14, dL = LIMITS.delta_height_cm ?? 5;
  const band = (v, lim) => (v == null ? '' : v > lim + 1 ? 'bad' : v > lim ? 'warn' : 'ok');
  $('mTemp').className = 'card metric ' + band(f.temp, tL);
  $('mRh').className = 'card metric ' + band(f.rh, rhL);
  $('mEmc').className = 'card metric ' + band(f.emc_estimate, eL);
  $('mDh').className = 'card metric ' + (f.delta_height_cm == null ? ''
    : f.delta_height_cm > dL ? 'bad' : f.delta_height_cm > dL / 2 ? 'warn' : 'ok');

  /* why / evidence / checks */
  $('ruleText').textContent = r.rule || '—';
  $('eviList').innerHTML = (r.evidence || []).map((e) => `<li>${esc(e)}</li>`).join('');
  const checks = (r.checks && r.checks.length) ? r.checks
    : ['No action required. Keep the normal inspection round.'];
  $('checkList').innerHTML = checks.map((c) => `<li>${esc(c)}</li>`).join('');

  /* explanation - wording only, never the source of the decision */
  const ex = r.explanation || {};
  $('explainText').textContent = ex.text || r.plain_summary || '—';
  $('explainSrc').textContent = ex.source === 'slm'
    ? 'Wording from the optional local SLM. Risk, state and the aeration interlock were decided by the deterministic engine.'
    : 'Wording from the built-in deterministic template. The local SLM is unavailable or disabled — the system works fully without it.';

  /* manager detail */
  $('rTemp').textContent = fmt(f.temp) + ' °C';
  $('rRh').textContent = fmt(f.rh) + ' %';
  $('rEmc').textContent = fmt(f.emc_estimate, 2) + ' %';
  $('rDew').textContent = fmt(f.dew_point) + ' °C';
  $('rFork').textContent = fmt(f.fork_raw, 0);
  $('rLdr').textContent = fmt(f.ldr_raw, 0);
  $('rDist').textContent = fmt(f.distance_cm) + ' cm';
  $('rDh').textContent = fmt(f.delta_height_cm) + ' cm';
  $('rMs').textContent = fmt(f.moisture_stress_hours, 2) + ' h';
  $('rTs').textContent = fmt(f.thermal_stress_hours, 2) + ' h';
  $('rState').textContent = r.state || '—';
  $('rRule').textContent = r.rule || '—';
  $('rTime').textContent = r.timestamp || payload.server_time || '—';
  const ch = payload.chain || {};
  $('rChain').textContent = (ch.telemetry !== false && ch.events !== false && ch.acknowledgments !== false)
    ? 'INTACT' : 'BROKEN — ' + (ch.detail || '');
  $('ackState').textContent = payload.unverified_ack
    ? 'Unverified acknowledgment on record at ' + payload.unverified_ack.ts +
      '. The original alert was preserved, not deleted.'
    : 'No unverified acknowledgment on record.';

  paintMimic(f);
}

/* ---------------- events timeline ---------------- */
async function loadEvents() {
  try {
    const res = await fetch('/api/events?limit=14');
    const data = await res.json();
    const items = (data.events || []).slice().reverse();
    $('eventsList').innerHTML = items.length
      ? items.map((e) => {
          const t = new Date(e.ts);
          const hh = isNaN(t) ? '--:--' : t.toLocaleTimeString('en-GB', { ...IST, hour: '2-digit', minute: '2-digit' });
          const head = e.kind === 'STATE_CHANGE' ? e.rule || e.state
            : e.kind === 'TELEMETRY_LOST' ? 'Telemetry lost'
            : e.kind === 'AUDIT_ANOMALY' ? 'Unverified acknowledgment' : e.kind;
          return `<li><span class="tl-time">${hh}</span><span class="tl-txt"><b>${esc(head)}</b>
            <small>${esc(e.state || '')} · ${esc(e.risk || '')}</small></span></li>`;
        }).join('')
      : '<li><span class="tl-txt muted">No events recorded yet.</span></li>';
  } catch (e) {
    $('eventsList').innerHTML = '<li><span class="tl-txt muted">Event log unavailable.</span></li>';
  }
}
/* ---------------- scenario buttons ---------------- */
function buildScenarioButtons(list) {
  SCENARIOS = list;
  $('simBtns').innerHTML = list.map((s) =>
    `<button class="simbtn" data-scenario="${esc(s.id)}">${esc(s.label)}<small>${esc(s.expect)}</small></button>`
  ).join('');
  document.querySelectorAll('.simbtn').forEach((btn) => {
    btn.addEventListener('click', () => triggerScenario(btn.dataset.scenario, btn));
  });
}

async function triggerScenario(id, btn) {
  document.querySelectorAll('.simbtn').forEach((b) => b.classList.remove('on'));
  if (btn) btn.classList.add('on');
  activeScenario = id;
  $('simNote').textContent = `Running scenario "${id}" through the live pipeline…`;
  runPipeline();
  try {
    const res = await fetch(`/api/simulate/${encodeURIComponent(id)}`, { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
    const out = await res.json();
    // Render ONLY what the engine returned. No client-side scenario logic.
    renderStatus({
      result: out, mode: out.mode || 'SIMULATION', limits: LIMITS,
      baseline_cm: 15.0, facility: { name: 'Demo Rice Storage' },
      chain: { telemetry: true, events: true, acknowledgments: true },
      server_time: out.timestamp,
    });
    $('simNote').textContent =
      `Scenario "${id}" → ${out.state} / ${out.risk} / aeration ${out.aeration_allowed ? 'AVAILABLE' : 'LOCKED'}. ` +
      'That result came from the deterministic engine, not from the button.';
  } catch (err) {
    $('simNote').textContent = 'Scenario request failed: ' + err.message;
  }
  loadEvents();
}

/* ---------------- acknowledge ---------------- */
async function acknowledge(verified) {
  const note = $('ackNote').value || '';
  $('simNote').textContent = verified
    ? 'Recording a verified acknowledgment…'
    : 'Recording an acknowledgment WITHOUT physical verification…';
  runPipeline();
  try {
    const res = await fetch('/api/acknowledge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operator: 'console-operator', physically_verified: verified, note }),
    });
    const out = await res.json();
    renderStatus({
      result: out, mode: out.mode || 'SIMULATION', limits: LIMITS,
      baseline_cm: 15.0, facility: { name: 'Demo Rice Storage' },
      chain: { telemetry: true, events: true, acknowledgments: true },
      server_time: out.timestamp,
    });
    $('simNote').textContent = verified
      ? `Acknowledgment recorded and verified. State is now ${out.state}.`
      : `Unverified acknowledgment recorded. State is now ${out.state} — a manager must physically verify.`;
    $('ackNote').value = '';
  } catch (err) {
    $('simNote').textContent = 'Acknowledge failed: ' + err.message;
  }
  loadEvents();
}

/* ---------------- polling ---------------- */
async function poll() {
  try {
    const res = await fetch('/api/status');
    const payload = await res.json();
    renderStatus(payload);
    if (!SCENARIOS.length && payload.scenarios) buildScenarioButtons(payload.scenarios);
  } catch (e) {
    $('modePill').textContent = 'SERVER OFFLINE';
    $('modePill').className = 'modepill off';
    $('shState').textContent = 'SERVER UNREACHABLE';
    $('shSub').textContent = 'Start the backend with: python run.py';
  }
}

/* ---------------- wiring ---------------- */
function init() {
  setTheme(localStorage.getItem('gg-theme') || 'light');
  $('themeBtn').addEventListener('click', (e) => toggleTheme(e.currentTarget));
  $('themeBtn2').addEventListener('click', (e) => toggleTheme(e.currentTarget));

  document.querySelectorAll('.mtab').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.mtab').forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');
      document.body.classList.toggle('manager', tab.dataset.view === 'manager');
    });
  });

  $('ackVerified').addEventListener('click', () => acknowledge(true));
  $('ackUnverified').addEventListener('click', () => acknowledge(false));

  tickClock();
  setInterval(tickClock, 1000);
  poll();
  setInterval(poll, 1000);
  setInterval(loadEvents, 5000);
}

document.addEventListener('DOMContentLoaded', init);