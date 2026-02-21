const qs = (s, el=document)=>el.querySelector(s);
const qsa = (s, el=document)=>Array.from(el.querySelectorAll(s));

const issueText = qs('#issueText');
const runBtn = qs('#runInvestigation');
const healthBtn = qs('#healthBtn');
const stageStrip = qs('#stageStrip');
const previewGrid = qs('#previewGrid');
const refreshPreview = qs('#refreshPreview');
const summaryMetrics = qs('#summaryMetrics');
const narrativeEl = qs('#narrative');
const lineagePathEl = qs('#lineagePath');
const diffTable = qs('#diffTable');
const tooltip = qs('#tooltip');
const seedBtn = qs('#seedBtn');
const exportCsvBtn = qs('#exportCsv');
const queriesContainer = qs('#queriesContainer');
const resultsContainer = qs('#resultsContainer');
const copyQueriesBtn = qs('#copyQueries');
const copyResultsBtn = qs('#copyResults');

/* ═══════════════════════ Tab System ═══════════════════════ */
function initTabs(){
  qsa('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tabName = btn.dataset.tab;
      if (!tabName) return;
      qsa('.tab-btn').forEach(b => b.classList.remove('active'));
      qsa('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      const content = qs(`#${tabName}`);
      if (content) content.classList.add('active');
    });
  });
}
document.addEventListener('DOMContentLoaded', initTabs);

/* ═══════════════════════ Toast Notifications ═══════════════════════ */
function toast(msg, type='ok'){
  const box = qs('#toasts');
  if (!box){ console.log(type.toUpperCase(), msg); return; }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  // Add icon prefix
  const icons = { ok: '✓', err: '✕', warn: '⚠' };
  el.innerHTML = `<span style="font-weight:700;margin-right:8px;">${icons[type]||''}</span>${msg}`;
  box.appendChild(el);
  setTimeout(()=>{ el.classList.add('fading'); setTimeout(()=> el.remove(), 300); }, 3200);
}

/* ═══════════════════════ Tooltip ═══════════════════════ */
document.addEventListener('mouseover', e=>{
  const t = e.target.closest('.info');
  if (!t || !t.dataset.tooltip) return;
  tooltip.textContent = t.dataset.tooltip;
  tooltip.classList.remove('hidden');
  const rect = t.getBoundingClientRect();
  tooltip.style.left = (rect.left + window.scrollX + 18) + 'px';
  tooltip.style.top  = (rect.top  + window.scrollY + 4)  + 'px';
});
document.addEventListener('mouseout', e=>{
  if (e.target.closest('.info')) tooltip.classList.add('hidden');
});

/* ═══════════════════════ Investigation Loading Overlay ═══════════════════════ */
const LOADING_STEPS = [
  { id: 'step-parse',   label: 'Parsing investigation parameters…' },
  { id: 'step-query',   label: 'Building lineage queries…' },
  { id: 'step-exec',    label: 'Executing reconciliation…' },
  { id: 'step-analyze', label: 'Analysing data diffs…' },
  { id: 'step-report',  label: 'Generating narrative report…' },
];

let loadingOverlay = null;
let loadingTimer   = null;

function showLoadingOverlay(){
  if (loadingOverlay) return;

  loadingOverlay = document.createElement('div');
  loadingOverlay.className = 'investigation-loading';
  loadingOverlay.innerHTML = `
    <div class="loading-card">
      <div class="loading-spinner"></div>
      <div class="loading-title">Investigating…</div>
      <p style="font-size:13px;color:var(--text-muted);margin-bottom:4px;">Running lineage reconciliation</p>
      <div class="loading-steps">
        ${LOADING_STEPS.map(s=>`
          <div class="loading-step" id="${s.id}">
            <div class="step-icon">○</div>
            <span>${s.label}</span>
          </div>
        `).join('')}
      </div>
    </div>
  `;
  document.body.appendChild(loadingOverlay);

  // Animate steps progressively
  let currentStep = 0;
  const markDone = (idx) => {
    const el = qs(`#${LOADING_STEPS[idx].id}`, loadingOverlay);
    if (!el) return;
    el.classList.remove('active');
    el.classList.add('done');
    el.querySelector('.step-icon').textContent = '✓';
  };
  const markActive = (idx) => {
    const el = qs(`#${LOADING_STEPS[idx].id}`, loadingOverlay);
    if (!el) return;
    el.classList.add('active');
    el.querySelector('.step-icon').textContent = '↻';
  };

  markActive(0);
  const delays = [0, 600, 1300, 2000, 2700];
  LOADING_STEPS.forEach((_, idx) => {
    setTimeout(() => {
      if (idx > 0) markDone(idx - 1);
      if (idx < LOADING_STEPS.length) markActive(idx);
    }, delays[idx] || idx * 650);
  });

  loadingTimer = setTimeout(() => {
    const last = LOADING_STEPS.length - 1;
    markDone(last);
  }, 3000);
}

function hideLoadingOverlay(){
  clearTimeout(loadingTimer);
  if (!loadingOverlay) return;
  loadingOverlay.style.animation = 'overlayOut 0.3s ease forwards';
  setTimeout(() => {
    if (loadingOverlay) { loadingOverlay.remove(); loadingOverlay = null; }
  }, 320);
}

// inject overlayOut animation
const overlayOutStyle = document.createElement('style');
overlayOutStyle.textContent = `@keyframes overlayOut { from{opacity:1}to{opacity:0} }`;
document.head.appendChild(overlayOutStyle);

/* ═══════════════════════ API Helpers ═══════════════════════ */
async function getJSON(url){
  const r = await fetch(url);
  if (!r.ok){ const txt = await r.text(); throw new Error(txt || r.statusText); }
  return r.json();
}

/* ═══════════════════════ Health ═══════════════════════ */
async function health(){
  try{
    const j = await getJSON('/lineage-api/health');
    toast(`Lineage API OK${j.db ? ' • DB: '+j.db : ''}`, 'ok');
  }catch(err){
    toast('Lineage API health failed', 'err');
  }
}
if (healthBtn) healthBtn.addEventListener('click', health);

/* ═══════════════════════ Seed Demo ═══════════════════════ */
if (seedBtn){
  seedBtn.addEventListener('click', async ()=>{
    try{
      seedBtn.disabled = true;
      seedBtn.textContent = 'Seeding…';
      const resp = await fetch('/lineage-api/seed', { method:'POST', headers:{'Content-Type':'application/json'} });
      if (!resp.ok) throw new Error(await resp.text());
      await resp.json();
      toast('Demo lineage data seeded.', 'ok');
      await Promise.all([loadSummary(), loadPreview()]);
    }catch(err){
      toast('Failed to seed lineage data.', 'err');
    }finally{
      seedBtn.disabled = false;
      seedBtn.textContent = 'Demo Data';
    }
  });
}

/* ═══════════════════════ Stage Summary ═══════════════════════ */
async function loadSummary(){
  try{
    const j = await getJSON('/lineage-api/summary');
    renderStages(j.stages || []);
  }catch(err){
    stageStrip.innerHTML = '<small style="color:var(--danger)">Failed to load stage summary.</small>';
  }
}

function renderStages(stages){
  if (!stages.length){
    stageStrip.innerHTML = '<small style="color:var(--text-muted)">No stage summary yet.</small>';
    return;
  }
  stageStrip.innerHTML = stages.map(s=>{
    const bc = s.issues_count > 0 ? 'err' : (Math.abs(s.variance_vs_prev||0) > 0.005 ? 'warn' : 'ok');
    const varPct = s.variance_vs_prev == null ? '—' : (s.variance_vs_prev*100).toFixed(2)+'%';
    const dir = (s.variance_vs_prev||0) > 0 ? '↑' : ((s.variance_vs_prev||0) < 0 ? '↓' : '→');
    return `
      <div class="stage-card">
        <div class="stage-meta">
          <div class="stage-name">${s.label||s.stage_id}</div>
          <div class="stage-tag">${s.role||''}</div>
        </div>
        <div class="stage-kpis">
          <span class="label">Rows</span>
          <span style="font-family:'DM Mono',monospace;font-size:13px;">${(s.row_count??0).toLocaleString()}</span>
          <span class="label">Balance</span>
          <span style="font-family:'DM Mono',monospace;font-size:13px;">${formatCurrency(s.total_balance)}</span>
        </div>
        <div class="stage-variance" style="margin-top:8px;">
          <span class="label">Drift</span>
          <span style="font-family:'DM Mono',monospace;font-size:12px;">${dir} ${varPct}</span>
          <span class="label">Issues</span>
          <span class="badge ${bc}">${s.issues_count||0} open</span>
        </div>
      </div>
    `;
  }).join('');
}

/* ═══════════════════════ Sample Tables ═══════════════════════ */
async function loadPreview(){
  previewGrid.innerHTML = '<div class="preview-card"><small>Loading…</small></div>';
  try{
    const j = await getJSON('/lineage-api/preview?limit=5');
    const tables = j.tables || j || [];
    if (!tables.length){
      previewGrid.innerHTML = `
        <div class="preview-card">
          <small>No tables yet. Click <strong>"Demo Data"</strong> to load sample lineage data.</small>
        </div>
      `;
      return;
    }
    let anyRows = false;
    previewGrid.innerHTML = tables.map(t=>{
      const cols = t.columns || [];
      const rows = t.rows || [];
      if (rows.length) anyRows = true;
      const head = cols.map(c=>`<th>${escapeHtml(c)}</th>`).join('');
      let body = rows.map(r=>`<tr>${r.map(v=>`<td>${escapeHtml(v)}</td>`).join('')}</tr>`).join('');
      if (!body) body = `<tr><td colspan="${cols.length||1}"><em>No rows</em></td></tr>`;
      return `
        <div class="preview-card">
          <h3>${escapeHtml(t.name||t.table)}</h3>
          <small>${escapeHtml(t.stage||'')}</small>
          <div class="tablewrap" style="margin-top:10px;">
            <table>
              <thead><tr>${head}</tr></thead>
              <tbody>${body}</tbody>
            </table>
          </div>
        </div>
      `;
    }).join('');
    if (!anyRows) toast('Tables loaded but empty. Try "Demo Data".', 'warn');
  }catch(err){
    previewGrid.innerHTML = '<div class="preview-card"><small style="color:var(--danger)">Failed to load sample tables.</small></div>';
  }
}
if (refreshPreview) refreshPreview.addEventListener('click', loadPreview);

/* ═══════════════════════ Quick Prompts ═══════════════════════ */
qsa('.quick-prompt').forEach(btn => {
  btn.addEventListener('click', (e) => {
    const prompt = e.target.dataset.prompt;
    if (prompt) {
      issueText.value = prompt;
      issueText.focus();
      setTimeout(() => runBtn.click(), 100);
    }
  });
});

/* ═══════════════════════ Investigation Run ═══════════════════════ */
if (runBtn){
  runBtn.addEventListener('click', async ()=>{
    const question = (issueText.value||'').trim();
    if (!question){ toast('Please ask a question about your data.', 'err'); return; }

    runBtn.disabled = true;
    runBtn.classList.add('loading');

    showLoadingOverlay();
    const t0 = performance.now();

    try{
      const r = await fetch('/lineage-api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question })
      });
      if (!r.ok){ const txt = await r.text(); throw new Error(txt || r.statusText); }
      const j = await r.json();
      const elapsed = ((performance.now() - t0) / 1000).toFixed(2);

      renderMetrics(j.metrics || {});
      renderNarrative(j.narrative || '');
      renderPath(j.path || []);
      renderDiffTable(j.diffs || []);
      renderQueries(j.queries || [], elapsed);
      renderResults(j.results || null);

      toast(`Investigation complete — ${elapsed}s`, 'ok');
      qs('[data-tab="investigation"]')?.click();
    }catch(err){
      console.error(err);
      toast('Investigation failed: ' + (err.message || 'Unknown error'), 'err');
    }finally{
      hideLoadingOverlay();
      runBtn.disabled = false;
      runBtn.classList.remove('loading');
    }
  });
}

/* ═══════════════════════ Render Metrics ═══════════════════════ */
function renderMetrics(m){
  summaryMetrics.innerHTML = '';
  const blocks = [];
  if (m.raw_balance != null || m.mart_balance != null){
    blocks.push({
      label:'Total Balance Drift',
      value: m.gross_drift != null ? formatCurrency(m.gross_drift) : '—',
      tag:`raw: ${formatCurrency(m.raw_balance)} • mart: ${formatCurrency(m.mart_balance)}`
    });
  }
  if (m.discrepant_accounts != null){
    blocks.push({
      label:'Accounts with Discrepancies',
      value: m.discrepant_accounts.toLocaleString(),
      tag:`max variance: ${m.max_variance_percent != null ? (m.max_variance_percent*100).toFixed(2)+'%' : '—'}`
    });
  }
  if (m.total_transactions != null){
    blocks.push({
      label:'Transactions Considered',
      value: m.total_transactions.toLocaleString(),
      tag:`period: ${m.window || 'full'}`
    });
  }
  // Fallback: individual stage metrics (account-level reconcile response)
  if (!blocks.length && (m.raw_balance != null || m.stage_balance != null || m.mart_customer_total != null)){
    if (m.raw_balance != null)
      blocks.push({ label:'Raw Balance',   value: formatCurrency(m.raw_balance),          tag:'' });
    if (m.stage_balance != null)
      blocks.push({ label:'Stage Balance', value: formatCurrency(m.stage_balance),         tag: m.delta_stage_vs_raw ? `Δ ${formatCurrency(m.delta_stage_vs_raw)}` : '' });
    if (m.mart_customer_total != null)
      blocks.push({ label:'Mart Total',    value: formatCurrency(m.mart_customer_total),   tag: m.fees_total ? `Fees: ${formatCurrency(m.fees_total)}` : '' });
  }

  if (!blocks.length){
    summaryMetrics.innerHTML = '<small style="color:var(--text-muted)">No metrics available for this focus.</small>';
    return;
  }
  summaryMetrics.innerHTML = blocks.map(b=>`
    <div class="metric">
      <div class="metric-label">${escapeHtml(b.label)}</div>
      <div class="metric-value">${escapeHtml(b.value)}</div>
      <div class="metric-tag">${escapeHtml(b.tag||'')}</div>
    </div>
  `).join('');
}

/* ═══════════════════════ Render Narrative ═══════════════════════ */
function renderNarrative(text){
  narrativeEl.textContent = text || 'No narrative available for this investigation.';
}

/* ═══════════════════════ Render Lineage Path ═══════════════════════ */
function renderPath(path){
  if (!path.length){
    lineagePathEl.innerHTML = '<small style="color:var(--text-muted)">No lineage path returned for this entity.</small>';
    return;
  }

  // Stage label → display name + icon
  const stageInfo = {
    raw:   { icon: '⬡', name: 'Source',  badge: 'RAW'     },
    stage: { icon: '⬢', name: 'Staging', badge: 'STAGE'   },
    mart:  { icon: '◆', name: 'Mart',    badge: 'MART'    },
  };

  const pieces = [];

  path.forEach((p, idx) => {
    const label   = p.label || p.stage;
    const stage   = (p.stage || '').toLowerCase();
    const bal     = p.balance != null ? formatCurrency(p.balance) : '—';
    const tx      = p.txn_count != null ? p.txn_count.toLocaleString() + ' txns' : '';
    const d       = p.delta_balance  != null ? formatCurrency(p.delta_balance)  : null;
    const dPct    = p.delta_percent  != null ? (p.delta_percent * 100).toFixed(2) + '%' : null;

    const info     = stageInfo[stage] || { icon: '●', name: '', badge: stage.toUpperCase() };
    const isPos    = p.delta_balance != null && p.delta_balance > 0;
    const isNeg    = p.delta_balance != null && p.delta_balance < 0;
    const deltaClass = isPos ? 'delta-change' : isNeg ? 'delta-change-neg' : '';
    const deltaSign  = isPos ? '+' : '';

    const deltaRow = (d || dPct) ? `
      <div class="delta">
        <span class="delta-label">Δ prev</span>
        <span class="delta-value ${deltaClass}">${deltaSign}${d || ''}${dPct ? ' <span style="opacity:0.7;font-size:10px;">('+dPct+')</span>' : ''}</span>
      </div>` : '';

    const node = `
      <div class="path-node" data-stage="${escapeHtml(stage)}" style="animation-delay:${0.05 + idx*0.17}s">
        <div class="path-node-top"></div>
        <div class="path-node-body">
          <div class="path-node-badge">${escapeHtml(info.icon)} ${escapeHtml(info.badge)}</div>
          <h4>${escapeHtml(label)}</h4>
          <div class="stage">${escapeHtml(info.name)}</div>
          <div class="path-node-divider"></div>
          <div class="delta">
            <span class="delta-label">Balance</span>
            <span class="delta-value delta-balance-val">${escapeHtml(bal)}</span>
          </div>
          ${tx ? `<div class="delta"><span class="delta-label">Volume</span><span class="delta-value">${escapeHtml(tx)}</span></div>` : ''}
          ${deltaRow}
        </div>
      </div>`;

    pieces.push(node);

    // Insert connector between nodes
    if (idx < path.length - 1) {
      pieces.push(`
        <div class="path-connector">
          <div class="path-connector-dot"></div>
          <div class="path-connector-dot"></div>
        </div>`);
    }
  });

  lineagePathEl.innerHTML = pieces.join('');
}

/* ═══════════════════════ Render Diff Table ═══════════════════════ */
function renderDiffTable(diffs){
  if (!diffs.length){
    diffTable.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted);font-size:14px;">No row-level diffs for this scope.</div>';
    return;
  }
  const cols = Object.keys(diffs[0]);
  const head = cols.map(c=>`<th>${escapeHtml(c)}</th>`).join('');
  const body = diffs.map(row=>'<tr>'+cols.map(c=>`<td>${escapeHtml(row[c])}</td>`).join('')+'</tr>').join('');
  // diffTable itself IS the scrollable container (overflow:auto in CSS)
  diffTable.innerHTML = `
    <table>
      <thead><tr>${head}</tr></thead>
      <tbody>${body}</tbody>
    </table>
  `;
}

/* ═══════════════════════ Render Queries ═══════════════════════ */
function renderQueries(queries, totalElapsed){
  if (!queries || !queries.length){
    queriesContainer.innerHTML = '<p class="placeholder">No queries generated for this investigation</p>';
    if (copyQueriesBtn) copyQueriesBtn.classList.add('hidden');
    return;
  }
  // Distribute total elapsed time roughly equally across queries as an estimate
  const perQuery = totalElapsed ? (totalElapsed / queries.length).toFixed(2) : null;

  queriesContainer.innerHTML = queries.map((q, idx)=>{
    const queryText = typeof q === 'string' ? q : q.query || q;
    const queryType = typeof q === 'object' ? (q.type || 'SQL') : 'SQL';
    // Use per-query time from response if available, else distribute evenly
    const execMs = typeof q === 'object' && q.exec_ms != null
      ? (q.exec_ms / 1000).toFixed(2) + 's'
      : (perQuery ? `~${perQuery}s` : null);
    return `
      <div class="query-block" style="animation-delay:${idx*0.07}s">
        <div class="query-header">
          <div style="display:flex;align-items:center;gap:8px;">
            <span class="query-type">${escapeHtml(queryType)}</span>
            <span style="font-size:10px;color:var(--text-muted);font-family:'DM Sans',sans-serif;">Query ${idx+1} of ${queries.length}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            ${execMs ? `<span title="Estimated execution time" style="font-size:11px;color:var(--text-muted);font-family:'DM Mono',monospace;background:var(--bg-alt);border:1px solid var(--border-soft);padding:2px 8px;border-radius:5px;">⏱ ${execMs}</span>` : ''}
            <button class="btn btn-sm" style="background:var(--bg-alt);color:var(--text-muted);border:1px solid var(--border);" data-index="${idx}">Copy</button>
          </div>
        </div>
        <pre><code class="language-sql">${escapeHtml(queryText)}</code></pre>
      </div>
    `;
  }).join('');
  if (window.hljs) hljs.highlightAll();
  qsa('[data-index]', queriesContainer).forEach(btn=>{
    btn.addEventListener('click', e=>{
      const idx = e.target.dataset.index;
      const qt  = typeof queries[idx]==='string' ? queries[idx] : queries[idx].query||queries[idx];
      navigator.clipboard.writeText(qt).then(()=>toast('Query copied','ok')).catch(()=>toast('Copy failed','err'));
    });
  });
  if (copyQueriesBtn) copyQueriesBtn.classList.remove('hidden');
}

/* ═══════════════════════ Render Results ═══════════════════════ */
function renderResults(results){
  if (!results){
    resultsContainer.innerHTML = '<p class="placeholder">No results available for this investigation</p>';
    if (copyResultsBtn) copyResultsBtn.classList.add('hidden');
    return;
  }
  let arr = Array.isArray(results) ? results : [results];
  if (!arr.length){
    resultsContainer.innerHTML = '<p class="placeholder">No results data available</p>';
    if (copyResultsBtn) copyResultsBtn.classList.add('hidden');
    return;
  }
  resultsContainer.innerHTML = arr.map((result, idx)=>{
    if (typeof result === 'string'){
      return `<div class="result-block" style="animation-delay:${idx*0.07}s"><pre><code>${escapeHtml(result)}</code></pre></div>`;
    }
    if (result && Array.isArray(result.rows) && result.rows.length){
      const cols = result.columns || (Array.isArray(result.rows[0]) ? [] : Object.keys(result.rows[0]));
      const head = cols.map(c=>`<th>${escapeHtml(c)}</th>`).join('');
      let body;
      if (Array.isArray(result.rows[0])){
        body = result.rows.map(r=>'<tr>'+r.map(v=>`<td>${escapeHtml(v)}</td>`).join('')+'</tr>').join('');
      } else {
        body = result.rows.map(r=>'<tr>'+cols.map(c=>`<td>${escapeHtml(r[c])}</td>`).join('')+'</tr>').join('');
      }
      return `
        <div class="result-block" style="animation-delay:${idx*0.07}s">
          ${result.name ? `<h4>${escapeHtml(result.name)}</h4>` : ''}
          <div class="tablewrap">
            <table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
          </div>
        </div>
      `;
    }
    if (typeof result === 'object'){
      return `<div class="result-block" style="animation-delay:${idx*0.07}s"><pre><code>${escapeHtml(JSON.stringify(result, null, 2))}</code></pre></div>`;
    }
    return `<div class="result-block"><pre><code>${escapeHtml(String(result))}</code></pre></div>`;
  }).join('');
  if (window.hljs) hljs.highlightAll();
  if (copyResultsBtn) copyResultsBtn.classList.remove('hidden');
}

/* ═══════════════════════ Copy Buttons ═══════════════════════ */
if (copyQueriesBtn){
  copyQueriesBtn.addEventListener('click', ()=>{
    const text = qsa('.query-block pre code', queriesContainer).map(el=>el.textContent).join('\n\n---\n\n');
    if (!text){ toast('No queries to copy','err'); return; }
    navigator.clipboard.writeText(text).then(()=>toast('All queries copied','ok')).catch(()=>toast('Failed to copy','err'));
  });
}
if (copyResultsBtn){
  copyResultsBtn.addEventListener('click', ()=>{
    const text = qsa('.result-block', resultsContainer).map(el=>el.textContent).join('\n\n---\n\n');
    if (!text){ toast('No results to copy','err'); return; }
    navigator.clipboard.writeText(text).then(()=>toast('All results copied','ok')).catch(()=>toast('Failed to copy','err'));
  });
}

/* ═══════════════════════ Export CSV ═══════════════════════ */
if (exportCsvBtn){
  exportCsvBtn.addEventListener('click', ()=>{
    if (!diffTable.querySelector('table')){ toast('No diff data to export.','err'); return; }
    const rows = [];
    rows.push(Array.from(diffTable.querySelectorAll('thead th')).map(th=>th.textContent.trim()));
    diffTable.querySelectorAll('tbody tr').forEach(tr=>{
      rows.push(Array.from(tr.querySelectorAll('td')).map(td=>td.textContent.trim()));
    });
    const csv  = rows.map(r=>r.map(escapeCsv).join(',')).join('\n');
    const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = 'lineage_diffs.csv';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
    toast('Exported CSV','ok');
  });
}

/* ═══════════════════════ Utilities ═══════════════════════ */
function escapeHtml(x){
  if (x==null) return '';
  return String(x).replace(/[&<>"']/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
function escapeCsv(x){
  const s = String(x??'');
  return /[",\n]/.test(s) ? `"${s.replace(/"/g,'""')}"` : s;
}
function formatCurrency(v){
  if (v==null||isNaN(Number(v))) return '—';
  return Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
}

/* ═══════════════════════ Boot ═══════════════════════ */
(async function init(){
  await Promise.all([loadSummary(), loadPreview()]);
  toast('MCPilot Lineage ready', 'ok');
})();