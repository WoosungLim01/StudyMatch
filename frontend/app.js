/* StudyMatch — frontend logic */

'use strict';

// ── API base URL (change for deployment) ─────────────────────────────────
const API = '';  // empty = same origin; set to 'https://your-backend.com' if split

// ── App state ─────────────────────────────────────────────────────────────
let cohort = null;        // raw students from /api/generate
let scored = null;        // scored students from /api/pipeline
let clusters = null;      // cluster result from /api/cluster
let matchResult = null;   // match result from /api/match

// ── Archetype color palette ───────────────────────────────────────────────
const ARCHETYPE_COLORS = [
  '#4493f8', '#3fb950', '#f0883e', '#d2a8ff', '#79c0ff', '#56d364', '#ff7b72', '#ffa657'
];
const AXES = ['planning', 'environment', 'collaboration', 'flexibility', 'feedback', 'motivation'];
const AXIS_LABELS = ['Planning', 'Environment', 'Collaboration', 'Flexibility', 'Feedback', 'Motivation'];

// ── Registered Chart.js instances (destroyed before re-render) ────────────
const _charts = {};

function mkChart(id, config) {
  if (_charts[id]) _charts[id].destroy();
  _charts[id] = new Chart(document.getElementById(id).getContext('2d'), config);
  return _charts[id];
}

// ── Tab switching ─────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (btn.disabled) return;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
  });
});

// ── Slider live preview ───────────────────────────────────────────────────
function bindSlider(id, valId, fmt) {
  const sl = document.getElementById(id);
  const vl = document.getElementById(valId);
  vl.textContent = fmt(sl.value);
  sl.addEventListener('input', () => { vl.textContent = fmt(sl.value); });
}
bindSlider('sl-n',    'vl-n',     v => v);
bindSlider('sl-noise','vl-noise', v => (v/100).toFixed(2));
bindSlider('sl-sep',  'vl-sep',   v => (v/100).toFixed(2));
bindSlider('sl-low',  'vl-low',   v => v + '%');
bindSlider('sl-k',    'vl-k',     v => v);
bindSlider('sl-seed', 'vl-seed',  v => v);

// ── Status helpers ────────────────────────────────────────────────────────
function setStatus(el, msg, cls = '') {
  el.textContent = msg;
  el.className = 'status-bar ' + cls;
  el.style.display = msg ? 'block' : 'none';
}

function loading(el, msg) { setStatus(el, '⧗ ' + msg, ''); }
function ok(el, msg)      { setStatus(el, '✓ ' + msg, 'ok'); }
function err(el, msg)     { setStatus(el, '✗ ' + msg, 'error'); }

// ── API calls ─────────────────────────────────────────────────────────────
async function apiFetch(path, body) {
  const res = await fetch(API + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t);
  }
  return res.json();
}

// ══════════════════════════════════════════════════════════════════════════
//  TAB 1 — Generator
// ══════════════════════════════════════════════════════════════════════════

document.getElementById('btn-generate').addEventListener('click', generateCohort);
document.getElementById('btn-run-pipeline').addEventListener('click', () => {
  document.querySelector('[data-tab="pipeline"]').click();
  runPipeline();
});

async function generateCohort() {
  const statusEl = document.getElementById('gen-status');
  const btn = document.getElementById('btn-generate');
  btn.disabled = true;
  btn.textContent = '⧗ Generating…';
  loading(statusEl, 'Calling /api/generate…');

  try {
    const res = await apiFetch('/api/generate', {
      n_students:          +document.getElementById('sl-n').value,
      noise_level:         +document.getElementById('sl-noise').value / 100,
      archetype_separation:+document.getElementById('sl-sep').value / 100,
      low_effort_pct:      +document.getElementById('sl-low').value / 100,
      n_archetypes:        +document.getElementById('sl-k').value,
      seed:                +document.getElementById('sl-seed').value,
    });

    cohort = res.students;
    scored = null; clusters = null; matchResult = null;

    // Lock downstream tabs
    ['tab-pipeline','tab-cluster','tab-match'].forEach(id => {
      document.getElementById(id).disabled = true;
    });

    renderGenTable(cohort);
    renderGenStats(cohort);
    renderArchetypeDist(cohort);

    ok(statusEl, `Generated ${cohort.length} students.`);
    document.getElementById('btn-run-pipeline').disabled = false;
    document.getElementById('tab-pipeline').disabled = false;

  } catch(e) {
    err(statusEl, e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ GENERATE COHORT';
  }
}

function renderGenStats(students) {
  document.getElementById('st-n').textContent    = students.length;
  document.getElementById('st-low').textContent  = students.filter(s => s.is_low_effort).length;
  document.getElementById('st-k').textContent    = +document.getElementById('sl-k').value;
  document.getElementById('st-noise').textContent= (+document.getElementById('sl-noise').value/100).toFixed(2);
}

function renderGenTable(students) {
  document.getElementById('gen-table-count').textContent = `(${students.length} rows)`;
  const tbody = document.getElementById('gen-tbody');
  tbody.innerHTML = students.slice(0, 100).map(s => {
    const tv = s.true_axis_scores;
    return `<tr>
      <td>${s.id}</td>
      <td>${s.name}</td>
      <td>${s.primary_archetype}</td>
      <td class="${s.is_low_effort ? 'flag-cell' : 'ok-cell'}">${s.is_low_effort ? '⚠ YES' : 'ok'}</td>
      ${AXES.map(ax => `<td>${tv[ax].toFixed(1)}</td>`).join('')}
    </tr>`;
  }).join('');
}

function renderArchetypeDist(students) {
  const counts = {};
  students.forEach(s => { counts[s.primary_archetype] = (counts[s.primary_archetype] || 0) + 1; });
  const labels = Object.keys(counts);
  const data   = labels.map(l => counts[l]);

  mkChart('chart-archetype-dist', {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: labels.map((_,i) => ARCHETYPE_COLORS[i % ARCHETYPE_COLORS.length]),
        borderWidth: 0,
      }]
    },
    options: chartDefaults({ legend: false, xLabel: 'Archetype', yLabel: 'Count' }),
  });
}

// ══════════════════════════════════════════════════════════════════════════
//  TAB 2 — Pipeline
// ══════════════════════════════════════════════════════════════════════════

async function runPipeline() {
  if (!cohort) return;
  const statusEl = document.getElementById('pipeline-status');
  const btn = document.getElementById('btn-run-cluster');
  loading(statusEl, 'Scoring responses + consistency check…');

  try {
    const res = await apiFetch('/api/pipeline', { students: cohort });
    scored = res.scored_students;

    document.getElementById('pp-n').textContent       = scored.length;
    document.getElementById('pp-flagged').textContent = res.n_flagged;
    document.getElementById('pp-pct').textContent     = (res.n_flagged / scored.length * 100).toFixed(1) + '%';
    document.getElementById('pp-clean').textContent   = scored.length - res.n_flagged;

    renderPipelineTable(scored);
    renderAxisDistChart(scored);
    renderSdDistChart(scored);

    ok(statusEl, `Scored ${scored.length} students. ${res.n_flagged} flagged.`);
    btn.disabled = false;
    document.getElementById('tab-cluster').disabled = false;

  } catch(e) {
    err(statusEl, e.message);
  }
}

document.getElementById('btn-run-cluster').addEventListener('click', () => {
  document.querySelector('[data-tab="cluster"]').click();
  runClustering();
});

function renderPipelineTable(students) {
  const tbody = document.getElementById('pipeline-tbody');
  tbody.innerHTML = students.map(s => {
    const c = s.consistency;
    const ax = s.axis_scores;
    return `<tr>
      <td>${s.name}</td>
      <td class="${c.flag_low_effort ? 'flag-cell' : 'ok-cell'}">${c.flag_low_effort ? '⚠ FLAG' : 'ok'}</td>
      <td style="font-size:10px; color:var(--muted); max-width:200px;">${c.issues.join('; ') || '—'}</td>
      <td>${c.response_sd}</td>
      ${AXES.map(a => `<td>${ax[a].toFixed(2)}</td>`).join('')}
    </tr>`;
  }).join('');
}

function renderAxisDistChart(students) {
  const means = AXES.map(ax => {
    const vals = students.map(s => s.axis_scores[ax]);
    return vals.reduce((a,b) => a+b, 0) / vals.length;
  });
  const sds = AXES.map(ax => {
    const vals = students.map(s => s.axis_scores[ax]);
    const m = vals.reduce((a,b) => a+b, 0) / vals.length;
    return Math.sqrt(vals.reduce((a,b) => a + (b-m)**2, 0) / vals.length);
  });

  mkChart('chart-axis-dist', {
    type: 'bar',
    data: {
      labels: AXIS_LABELS,
      datasets: [
        { label: 'Mean score', data: means, backgroundColor: ARCHETYPE_COLORS.slice(0,6), borderWidth: 0 },
        { label: '±1 SD',      data: sds,   backgroundColor: '#ffffff22',                  borderWidth: 0 },
      ]
    },
    options: {
      ...chartDefaults({ yLabel: 'Axis Score (1–6)' }),
      scales: { y: { min: 1, max: 6, ...darkAxis() }, x: { ...darkAxis() } },
    },
  });
}

function renderSdDistChart(students) {
  const sds = students.map(s => +s.consistency.response_sd);
  const bins = Array.from({length: 12}, (_, i) => i * 0.4);
  const counts = bins.map((lo, i) => {
    const hi = lo + 0.4;
    return sds.filter(v => v >= lo && v < hi).length;
  });

  mkChart('chart-sd-dist', {
    type: 'bar',
    data: {
      labels: bins.map(b => b.toFixed(1)),
      datasets: [{
        label: 'Students',
        data: counts,
        backgroundColor: counts.map((_, i) => bins[i] < 0.75 ? '#f85149' : '#4493f855'),
        borderWidth: 0,
      }]
    },
    options: {
      ...chartDefaults({ xLabel: 'Response SD', yLabel: 'Count' }),
      plugins: {
        ...chartDefaults().plugins,
        annotation: { annotations: { line1: { type: 'line', x: 0.75, borderColor: '#f85149', borderWidth: 1 } } },
        legend: { display: false },
      }
    },
  });
}

// ══════════════════════════════════════════════════════════════════════════
//  TAB 3 — Clustering
// ══════════════════════════════════════════════════════════════════════════

async function runClustering() {
  if (!scored) return;
  const statusEl = document.getElementById('cluster-status');
  loading(statusEl, 'Running GMM over k = 2…8…');

  try {
    const res = await apiFetch('/api/cluster', { scored_students: scored });
    clusters = res;

    document.getElementById('cl-k').textContent      = res.n_optimal;
    document.getElementById('cl-n').textContent      = scored.length;
    document.getElementById('cl-best-bic').textContent = res.bic_curve.reduce((a,b) => a.bic < b.bic ? a : b).k;
    document.getElementById('cl-best-sil').textContent = res.silhouette_curve.reduce((a,b) => a.silhouette > b.silhouette ? a : b).k;

    renderBicChart(res.bic_curve);
    renderSilChart(res.silhouette_curve);
    renderRadarChart(res.archetypes);
    renderArchetypeCards(res.archetypes);
    renderClusterTable(res.student_clusters, res.archetypes);

    ok(statusEl, `Found ${res.n_optimal} archetypes.`);
    document.getElementById('btn-run-match').disabled = false;
    document.getElementById('tab-match').disabled = false;
    buildWeightControls();

  } catch(e) {
    err(statusEl, e.message);
  }
}

document.getElementById('btn-run-match').addEventListener('click', () => {
  document.querySelector('[data-tab="match"]').click();
  runMatching();
});

function renderBicChart(curve) {
  mkChart('chart-bic', {
    type: 'line',
    data: {
      labels: curve.map(d => d.k),
      datasets: [{ label: 'BIC', data: curve.map(d => d.bic), borderColor: '#4493f8', backgroundColor: '#4493f820', fill: true, tension: 0.3 }]
    },
    options: chartDefaults({ xLabel: 'k', yLabel: 'BIC' }),
  });
}

function renderSilChart(curve) {
  mkChart('chart-sil', {
    type: 'line',
    data: {
      labels: curve.map(d => d.k),
      datasets: [{ label: 'Silhouette', data: curve.map(d => d.silhouette), borderColor: '#3fb950', backgroundColor: '#3fb95020', fill: true, tension: 0.3 }]
    },
    options: chartDefaults({ xLabel: 'k', yLabel: 'Silhouette Score' }),
  });
}

function renderRadarChart(archetypes) {
  mkChart('chart-radar', {
    type: 'radar',
    data: {
      labels: AXIS_LABELS,
      datasets: archetypes.map((a, i) => ({
        label: a.name,
        data: AXES.map(ax => a.mean_normalized[ax]),
        borderColor: ARCHETYPE_COLORS[i],
        backgroundColor: ARCHETYPE_COLORS[i] + '20',
        pointBackgroundColor: ARCHETYPE_COLORS[i],
        borderWidth: 2,
      }))
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        r: {
          min: 0, max: 1,
          ticks: { color: '#7d8590', backdropColor: 'transparent', stepSize: 0.25 },
          grid: { color: '#30363d' },
          pointLabels: { color: '#e6edf3', font: { family: 'Courier New', size: 11 } },
          angleLines: { color: '#30363d' },
        }
      },
      plugins: { legend: { labels: { color: '#e6edf3', font: { family: 'Courier New' }, boxWidth: 12 } } },
    }
  });
}

function renderArchetypeCards(archetypes) {
  const el = document.getElementById('archetype-cards');
  el.innerHTML = archetypes.map((a, i) => {
    const topAx = AXES.slice().sort((x, y) => a.mean_normalized[y] - a.mean_normalized[x]).slice(0, 3);
    return `<div class="card" style="border-color:${ARCHETYPE_COLORS[i]}44; margin-bottom:0;">
      <div style="color:${ARCHETYPE_COLORS[i]}; font-size:11px; letter-spacing:2px; margin-bottom:6px;">${a.name}</div>
      <div style="font-size:11px; color:var(--muted); margin-bottom:8px;">${a.n_members} members</div>
      ${topAx.map(ax => `
        <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
          <span style="width:90px; font-size:10px; color:var(--muted);">${ax}</span>
          <div style="flex:1; background:var(--border); height:5px;">
            <div style="background:${ARCHETYPE_COLORS[i]}; height:100%; width:${(a.mean_normalized[ax]*100).toFixed(0)}%"></div>
          </div>
          <span style="font-size:10px; width:32px; text-align:right; color:${ARCHETYPE_COLORS[i]}">${(a.mean_normalized[ax]*100).toFixed(0)}%</span>
        </div>
      `).join('')}
    </div>`;
  }).join('');
}

function renderClusterTable(students, archetypes) {
  const tbody = document.getElementById('cluster-tbody');
  tbody.innerHTML = students.map(s => {
    const arch = archetypes[s.primary_archetype_id];
    const color = ARCHETYPE_COLORS[s.primary_archetype_id % ARCHETYPE_COLORS.length];
    // Membership bar
    const bar = archetypes.map((a, i) => {
      const pct = ((s.soft_membership[i] || 0) * 100).toFixed(1);
      return `<div class="membership-seg" style="width:${pct}%; background:${ARCHETYPE_COLORS[i]}; opacity:.8;"></div>`;
    }).join('');
    const membershipText = archetypes.map((a, i) =>
      `${a.name}: ${((s.soft_membership[i] || 0) * 100).toFixed(1)}%`
    ).join(' | ');
    return `<tr>
      <td>${s.name}</td>
      <td style="color:${color}">${arch ? arch.name : s.primary_archetype_id}</td>
      <td>${s.strength_pct}%</td>
      <td>
        <div class="membership-bar">${bar}</div>
        <div style="font-size:9px; color:var(--muted); margin-top:2px;">${membershipText}</div>
      </td>
    </tr>`;
  }).join('');
}

// ══════════════════════════════════════════════════════════════════════════
//  TAB 4 — Matching
// ══════════════════════════════════════════════════════════════════════════

const DEFAULT_WEIGHTS = { planning:1.0, environment:0.8, collaboration:1.0, flexibility:0.7, feedback:0.7, motivation:1.5 };

function buildWeightControls() {
  const el = document.getElementById('weight-controls');
  el.innerHTML = `
    <div style="margin-bottom:10px; font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:2px;">Axis Weights</div>
    ${AXES.map(ax => `
      <div class="control-row">
        <label>${ax} <span style="font-size:10px;">${ax === 'motivation' ? '(quasi-mandatory)' : ''}</span></label>
        <input type="range" id="w-${ax}" min="0" max="30" value="${Math.round(DEFAULT_WEIGHTS[ax]*10)}" step="1">
        <span class="val" id="wv-${ax}">${DEFAULT_WEIGHTS[ax].toFixed(1)}</span>
      </div>
    `).join('')}
  `;
  AXES.forEach(ax => {
    const sl = document.getElementById(`w-${ax}`);
    const vl = document.getElementById(`wv-${ax}`);
    sl.addEventListener('input', () => { vl.textContent = (sl.value / 10).toFixed(1); });
  });
}

function getWeights() {
  const w = {};
  AXES.forEach(ax => {
    const el = document.getElementById(`w-${ax}`);
    w[ax] = el ? el.value / 10 : DEFAULT_WEIGHTS[ax];
  });
  return w;
}

document.getElementById('btn-rerun-match').addEventListener('click', runMatching);

async function runMatching() {
  if (!scored) return;
  const statusEl = document.getElementById('match-status');
  const btn = document.getElementById('btn-rerun-match');
  btn.disabled = true;
  loading(statusEl, 'Running ILP + Random + Oracle… (may take up to 30s for large cohorts)');

  try {
    const res = await apiFetch('/api/match', {
      scored_students: scored,
      axis_weights: getWeights(),
      group_size_min: 4,
      group_size_max: 5,
      time_limit_s: 30.0,
    });
    matchResult = res;

    const rnd = res.random_result.total_compat;
    const ilp = res.ilp_result.total_compat;
    const orc = res.oracle_result.total_compat;
    const maxV = Math.max(rnd, ilp, orc);

    document.getElementById('mc-random').textContent = rnd.toFixed(3);
    document.getElementById('mc-ilp').textContent    = ilp.toFixed(3);
    document.getElementById('mc-oracle').textContent = orc.toFixed(3);

    document.getElementById('bar-random').style.width = (rnd / maxV * 100).toFixed(1) + '%';
    document.getElementById('bar-ilp').style.width    = (ilp / maxV * 100).toFixed(1) + '%';
    document.getElementById('bar-oracle').style.width = (orc / maxV * 100).toFixed(1) + '%';

    document.getElementById('cmp-random-val').textContent = rnd.toFixed(3);
    document.getElementById('cmp-ilp-val').textContent    = ilp.toFixed(3);
    document.getElementById('cmp-oracle-val').textContent = orc.toFixed(3);

    const gapOracle = orc > 0 ? ((orc - ilp) / orc * 100).toFixed(1) + '%' : '—';
    const gapRandom = ilp > 0 ? '+' + ((ilp - rnd) / Math.max(rnd, 0.001) * 100).toFixed(1) + '%' : '—';
    document.getElementById('gap-oracle').textContent = gapOracle + ' below Oracle';
    document.getElementById('gap-random').textContent = gapRandom + ' over Random';
    document.getElementById('solve-time').textContent =
      `ILP ${res.ilp_result.solve_time_s}s, Oracle ${res.oracle_result.solve_time_s}s [${res.ilp_result.status}]`;

    renderGroupCards('groups-random', res.random_result.groups, 'var(--muted)');
    renderGroupCards('groups-ilp',    res.ilp_result.groups,    'var(--accent)');
    renderGroupCards('groups-oracle', res.oracle_result.groups,  'var(--warn)');
    renderGroupCompatChart(res);
    renderHeatmap(res.compat_matrix, res.ilp_result.groups, res.student_ids);

    ok(statusEl, `ILP: ${ilp.toFixed(3)}  |  Random: ${rnd.toFixed(3)}  |  Oracle: ${orc.toFixed(3)}`);

  } catch(e) {
    err(statusEl, e.message);
  } finally {
    btn.disabled = false;
  }
}

function renderGroupCards(containerId, groups, color) {
  const el = document.getElementById(containerId);
  el.innerHTML = groups.map(g => `
    <div class="group-card">
      <div class="gc-title" style="color:${color}">Group ${g.group_id + 1}</div>
      <div class="gc-score" style="color:${color}">${g.group_compat.toFixed(3)}</div>
      ${g.member_names.map(n => `<div class="gc-member">${n}</div>`).join('')}
    </div>
  `).join('');
}

function renderGroupCompatChart(res) {
  const rndScores = res.random_result.groups.map(g => g.group_compat);
  const ilpScores = res.ilp_result.groups.map(g => g.group_compat);
  const orcScores = res.oracle_result.groups.map(g => g.group_compat);
  const maxLen = Math.max(rndScores.length, ilpScores.length, orcScores.length);
  const labels = Array.from({length: maxLen}, (_, i) => `G${i+1}`);

  mkChart('chart-group-compat', {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Random', data: rndScores, backgroundColor: '#7d859055', borderColor: '#7d8590', borderWidth: 1 },
        { label: 'ILP',    data: ilpScores, backgroundColor: '#4493f855', borderColor: '#4493f8', borderWidth: 1 },
        { label: 'Oracle', data: orcScores, backgroundColor: '#f0883e55', borderColor: '#f0883e', borderWidth: 1 },
      ]
    },
    options: chartDefaults({ xLabel: 'Group', yLabel: 'Group Compat Score' }),
  });
}

function renderHeatmap(matrix, groups, studentIds) {
  const n = matrix.length;
  if (n > 80) return; // skip for very large cohorts (too slow to render)

  // Sort students by ILP group assignment for a block-diagonal appearance
  const groupOrder = [];
  groups.forEach(g => g.members.forEach(sid => groupOrder.push(studentIds.indexOf(sid))));
  // Remaining students not in a group (shouldn't happen)
  for (let i = 0; i < n; i++) {
    if (!groupOrder.includes(i)) groupOrder.push(i);
  }

  const size = Math.min(Math.floor(480 / n), 8);
  const canvas = document.getElementById('chart-heatmap');
  canvas.width  = n * size;
  canvas.height = n * size;
  const ctx = canvas.getContext('2d');

  for (let ri = 0; ri < n; ri++) {
    for (let ci = 0; ci < n; ci++) {
      const i = groupOrder[ri];
      const j = groupOrder[ci];
      const v = matrix[i][j];
      const alpha = Math.round(v * 255).toString(16).padStart(2, '0');
      ctx.fillStyle = i === j ? '#4493f8' : `#4493f8${alpha}`;
      ctx.fillRect(ci * size, ri * size, size, size);
    }
  }
}

// ══════════════════════════════════════════════════════════════════════════
//  Chart.js defaults (dark theme)
// ══════════════════════════════════════════════════════════════════════════

function darkAxis() {
  return {
    grid: { color: '#30363d' },
    ticks: { color: '#7d8590', font: { family: 'Courier New', size: 10 } },
  };
}

function chartDefaults({ legend = true, xLabel = '', yLabel = '' } = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: legend,
        labels: { color: '#e6edf3', font: { family: 'Courier New', size: 10 }, boxWidth: 10 }
      },
    },
    scales: {
      x: { ...darkAxis(), title: { display: !!xLabel, text: xLabel, color: '#7d8590', font: { family: 'Courier New', size: 10 } } },
      y: { ...darkAxis(), title: { display: !!yLabel, text: yLabel, color: '#7d8590', font: { family: 'Courier New', size: 10 } } },
    },
  };
}

// ── Auto-generate on load (optional convenience for demo) ─────────────────
// Comment out if you want the user to manually click Generate first.
// generateCohort();
