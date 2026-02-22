const qs  = (s, el=document)=>el.querySelector(s);
const qsa = (s, el=document)=>Array.from(el.querySelectorAll(s));

const issueText       = qs('#issueText');
const runBtn          = qs('#runInvestigation');
const healthBtn       = qs('#healthBtn');
const serverStatusPill= qs('#serverStatusPill');
const stageStrip      = qs('#stageStrip');
const previewGrid     = qs('#previewGrid');
const refreshPreview  = qs('#refreshPreview');
const metadataTableSelect = qs('#metadataTableSelect');
const metadataSummary = qs('#metadataSummary');
const metadataColumns = qs('#metadataColumns');
const metadataSample  = qs('#metadataSample');
const summaryMetrics  = qs('#summaryMetrics');
const narrativeEl     = qs('#narrative');
const lineagePathEl   = qs('#lineagePath');
const diffTable       = qs('#diffTable');
const tooltip         = qs('#tooltip');
const seedBtn         = qs('#seedBtn');
const exportCsvBtn    = qs('#exportCsv');
const queriesContainer= qs('#queriesContainer');
const resultsContainer= qs('#resultsContainer');
const copyQueriesBtn  = qs('#copyQueries');
const copyResultsBtn  = qs('#copyResults');

let cachedPreviewTables = [];

/* ---------------- Tabs ---------------- */
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

/* ---------------- Toast ---------------- */
function toast(msg, type='ok'){
  const box = qs('#toasts');
  if (!box){ console.log(type.toUpperCase(), msg); return; }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icons = { ok: '✓', err: '✕', warn: '⚠' };
  el.innerHTML = `<span style="font-weight:700;margin-right:8px;">${icons[type]||''}</span>${msg}`;
  box.appendChild(el);
  setTimeout(()=>{ el.classList.add('fading'); setTimeout(()=> el.remove(), 300); }, 3200);
}

/* ---------------- Tooltip ---------------- */
document.addEventListener('mouseover', e=>{
  const t = e.target.closest('.info');
  if (!t || !t.dataset.tooltip || !tooltip) return;
  tooltip.textContent = t.dataset.tooltip;
  tooltip.classList.remove('hidden');
  const rect = t.getBoundingClientRect();
  tooltip.style.left = (rect.left + window.scrollX + 18) + 'px';
  tooltip.style.top  = (rect.top  + window.scrollY + 4)  + 'px';
});
document.addEventListener('mouseout', e=>{
  if (e.target.closest('.info') && tooltip) tooltip.classList.add('hidden');
});

/* ---------------- Investigation Overlay ---------------- */
let overlayStepTimers = [];
let overlayPulseTimer = null;

function clearOverlayTimers(){
  overlayStepTimers.forEach(id => clearTimeout(id));
  overlayStepTimers = [];
  if (overlayPulseTimer) {
    clearInterval(overlayPulseTimer);
    overlayPulseTimer = null;
  }
}

function showLoadingOverlay(){
  const overlay = qs('#investigationOverlay');
  if (!overlay) return;

  clearOverlayTimers();

  overlay.classList.remove('hidden');
  const steps = qsa('.step', overlay);
  const statusMsg = qs('.status-message', overlay);
  const startTs = Date.now();

  steps.forEach(step => {
    step.classList.remove('active', 'completed');
    const circle = qs('.step-circle', step);
    const label = step.dataset.step;
    circle.textContent = String(parseInt(label,10) + 1);
  });

  if (steps[0]) {
    steps[0].classList.add('active');
    if (statusMsg) statusMsg.textContent = 'Step 1 of 5: Parsing your question...';
  }

  const activateStep = (idx, msg) => {
    steps.forEach((step, i) => {
      step.classList.remove('active');
      if (i < idx) {
        step.classList.add('completed');
        const circle = qs('.step-circle', step);
        if (circle) circle.textContent = '✓';
      }
    });
    const step = steps[idx];
    if (step) step.classList.add('active');
    if (statusMsg) statusMsg.textContent = msg;
  };

  // Move through pre-analysis phases quickly, then stay in running state until actual response arrives.
  activateStep(0, 'Step 1 of 5: Parsing your question...');
  overlayStepTimers.push(setTimeout(() => activateStep(1, 'Step 2 of 5: Extracting entities...'), 500));
  overlayStepTimers.push(setTimeout(() => activateStep(2, 'Step 3 of 5: Generating queries...'), 1200));
  overlayStepTimers.push(setTimeout(() => activateStep(3, 'Step 4 of 5: Running analysis...'), 2100));

  overlayPulseTimer = setInterval(() => {
    if (!statusMsg) return;
    const elapsed = ((Date.now() - startTs) / 1000).toFixed(1);
    statusMsg.textContent = `Step 4 of 5: Running analysis... (${elapsed}s)`;
  }, 1000);
}

function hideLoadingOverlay(){
  const overlay = qs('#investigationOverlay');
  clearOverlayTimers();
  if (overlay) overlay.classList.add('hidden');
}

function completeLoadingOverlay(){
  const overlay = qs('#investigationOverlay');
  if (!overlay) return;

  clearOverlayTimers();

  const steps = qsa('.step', overlay);
  const statusMsg = qs('.status-message', overlay);

  steps.forEach((step) => {
    step.classList.remove('active');
    step.classList.add('completed');
    const circle = qs('.step-circle', step);
    if (circle) circle.textContent = '✓';
  });

  if (statusMsg) {
    statusMsg.textContent = 'Investigation complete! Displaying results...';
  }
}

/* ---------------- API Helpers ---------------- */
async function getJSON(url){
  const r = await fetch(url);
  if (!r.ok){ const txt = await r.text().catch(()=> ''); throw new Error(txt || r.statusText); }
  return r.json();
}

/* ---------------- Health ---------------- */
async function health(){
  try{
    const j = await getJSON('/lineage-api/health');
    setServerStatus(true, 'Connected');
    toast(`Lineage API OK${j.db ? ' • DB: '+j.db : ''}`, 'ok');
  }catch{
    setServerStatus(false, 'Disconnected');
    toast('Lineage API health failed', 'err');
  }
}
healthBtn?.addEventListener('click', health);

function setServerStatus(isUp, label){
  if (!serverStatusPill) return;
  serverStatusPill.classList.remove('ok', 'err', 'unknown');
  serverStatusPill.classList.add(isUp ? 'ok' : 'err');
  const txt = qs('.server-text', serverStatusPill);
  if (txt) txt.textContent = label;
}

async function pingServerHealth(silent = true){
  try{
    const j = await getJSON('/lineage-api/health');
    setServerStatus(true, 'Connected');
    return j;
  }catch(e){
    setServerStatus(false, 'Disconnected');
    if (!silent) toast('Lineage API health failed', 'err');
    return null;
  }
}

/* ---------------- Seed Demo ---------------- */
seedBtn?.addEventListener('click', async ()=>{
  try{
    seedBtn.disabled = true;
    seedBtn.textContent = 'Seeding…';
    const resp = await fetch('/lineage-api/seed', { method:'POST', headers:{'Content-Type':'application/json'} });
    if (!resp.ok) throw new Error(await resp.text());
    await resp.json();
    toast('Demo lineage data seeded.', 'ok');
    await Promise.all([loadSummary(), loadPreview()]);
  }catch{
    toast('Failed to seed lineage data.', 'err');
  }finally{
    seedBtn.disabled = false;
    seedBtn.textContent = 'Demo Data';
  }
});

/* ---------------- Stage Summary ---------------- */
async function loadSummary(){
  try{
    const j = await getJSON('/lineage-api/summary');
    renderStages(j.stages || []);
  }catch{
    if (stageStrip) stageStrip.innerHTML = '<small style="color:var(--danger)">Failed to load stage summary.</small>';
  }
}

function renderStages(stages){
  if (!stageStrip) return;

  if (!stages.length){
    stageStrip.innerHTML = '<small style="color:var(--text-muted)">No stage summary yet.</small>';
    return;
  }

  stageStrip.innerHTML = stages.map(s=>{
    const bc = (s.issues_count||0) > 0 ? 'err' : (Math.abs(s.variance_vs_prev||0) > 0.005 ? 'warn' : 'ok');
    const varPct = s.variance_vs_prev == null ? '—' : (s.variance_vs_prev*100).toFixed(2)+'%';
    const dir = (s.variance_vs_prev||0) > 0 ? '↑' : ((s.variance_vs_prev||0) < 0 ? '↓' : '→');
    return `
      <div class="stage-card">
        <div class="stage-meta">
          <div class="stage-name">${escapeHtml(s.label||s.stage_id||'')}</div>
          <div class="stage-tag">${escapeHtml(s.role||'')}</div>
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

/* ---------------- Sample Tables ---------------- */
async function loadPreview(){
  if (!previewGrid) return;
  previewGrid.innerHTML = '<div class="preview-card"><small>Loading…</small></div>';
  try{
    const j = await getJSON('/lineage-api/preview?limit=5');
    const tables = j.tables || j || [];
    cachedPreviewTables = tables;
    renderMetadataPicker(tables);

    if (!tables.length){
      previewGrid.innerHTML = `
        <div class="preview-card">
          <small>No tables yet. Click <strong>"Demo Data"</strong> to load sample lineage data.</small>
        </div>
      `;
      clearMetadataPanel('No tables available. Seed demo data to inspect metadata.');
      return;
    }

    previewGrid.innerHTML = tables.map(t=>{
      const cols = t.columns || [];
      const rows = t.rows || [];
      const head = cols.map(c=>`<th>${escapeHtml(c)}</th>`).join('');
      let body = rows.map(r=>`<tr>${r.map(v=>`<td>${escapeHtml(v)}</td>`).join('')}</tr>`).join('');
      if (!body) body = `<tr><td colspan="${cols.length||1}"><em>No rows</em></td></tr>`;

      return `
        <div class="preview-card">
          <h3>${escapeHtml(t.name||t.table||'')}</h3>
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

  }catch{
    cachedPreviewTables = [];
    renderMetadataPicker([]);
    clearMetadataPanel('Failed to load metadata. Check API connection.');
    previewGrid.innerHTML = '<div class="preview-card"><small style="color:var(--danger)">Failed to load sample tables.</small></div>';
  }
}
refreshPreview?.addEventListener('click', loadPreview);

function clearMetadataPanel(msg){
  if (metadataSummary) {
    metadataSummary.innerHTML = `
      <div class="meta-card"><span>Stage</span><strong>—</strong></div>
      <div class="meta-card"><span>Columns</span><strong>—</strong></div>
      <div class="meta-card"><span>Rows</span><strong>—</strong></div>
      <div class="meta-card"><span>Sample Size</span><strong>—</strong></div>
    `;
  }
  if (metadataColumns) metadataColumns.innerHTML = `<p class="placeholder">${escapeHtml(msg || 'Select a table to view schema attributes.')}</p>`;
  if (metadataSample) metadataSample.innerHTML = `<p class="placeholder">${escapeHtml(msg || 'Select a table to preview records.')}</p>`;
}

function renderMetadataPicker(tables){
  if (!metadataTableSelect) return;
  const options = ['<option value="">Choose a table...</option>'];
  let firstName = null;

  (tables || []).forEach(t => {
    const name = t.name || t.table;
    if (!name) return;
    if (!firstName) firstName = String(name);
    options.push(`<option value="${encodeURIComponent(String(name))}">${escapeHtml(name)} (${escapeHtml(t.stage || 'main')})</option>`);
  });

  metadataTableSelect.innerHTML = options.join('');
  if (firstName) {
    metadataTableSelect.value = encodeURIComponent(firstName);
    renderMetadataForTable(firstName);
  } else {
    clearMetadataPanel('No tables available. Seed demo data to inspect metadata.');
  }
}

function renderMetadataForTable(tableName){
  if (!tableName){
    clearMetadataPanel();
    return;
  }

  const t = cachedPreviewTables.find(x => (x.name || x.table) === tableName);
  if (!t){
    clearMetadataPanel('Selected table not found in current preview payload.');
    return;
  }

  const cols = t.columns || [];
  const rows = t.rows || [];
  const colMeta = Array.isArray(t.column_meta) && t.column_meta.length
    ? t.column_meta
    : cols.map(c => ({ name: c, dtype: 'UNKNOWN', notnull: false, default: null, pk: false }));

  if (metadataSummary) {
    metadataSummary.innerHTML = `
      <div class="meta-card"><span>Stage</span><strong>${escapeHtml(t.stage || 'main')}</strong></div>
      <div class="meta-card"><span>Columns</span><strong>${colMeta.length}</strong></div>
      <div class="meta-card"><span>Rows</span><strong>${(t.row_count ?? '—')}</strong></div>
      <div class="meta-card"><span>Sample Size</span><strong>${rows.length}</strong></div>
    `;
  }

  if (metadataColumns) {
    const body = colMeta.map(c => `
      <tr>
        <td>${escapeHtml(c.name)}</td>
        <td>${escapeHtml(c.dtype || 'TEXT')}</td>
        <td>${c.notnull ? 'YES' : 'NO'}</td>
        <td>${c.pk ? 'YES' : 'NO'}</td>
        <td>${escapeHtml(c.default ?? 'NULL')}</td>
      </tr>
    `).join('');

    metadataColumns.innerHTML = `
      <div class="tablewrap">
        <table>
          <thead>
            <tr><th>Column</th><th>Type</th><th>Not Null</th><th>Primary Key</th><th>Default</th></tr>
          </thead>
          <tbody>${body || '<tr><td colspan="5"><em>No columns</em></td></tr>'}</tbody>
        </table>
      </div>
    `;
  }

  if (metadataSample) {
    const head = cols.map(c => `<th>${escapeHtml(c)}</th>`).join('');
    const body = rows.length
      ? rows.map(r => `<tr>${r.map(v => `<td>${escapeHtml(v)}</td>`).join('')}</tr>`).join('')
      : `<tr><td colspan="${Math.max(cols.length,1)}"><em>No sample rows</em></td></tr>`;

    metadataSample.innerHTML = `
      <div class="tablewrap">
        <table>
          <thead><tr>${head || '<th>Value</th>'}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    `;
  }
}

metadataTableSelect?.addEventListener('change', (e) => {
  const selected = decodeURIComponent(e.target.value || '');
  renderMetadataForTable(selected);
});

/* ---------------- Quick Prompts ---------------- */
qsa('.quick-prompt').forEach(btn => {
  btn.addEventListener('click', (e) => {
    const prompt = e.currentTarget.dataset.prompt;
    if (prompt && issueText && runBtn) {
      issueText.value = prompt;
      issueText.focus();
      setTimeout(() => runBtn.click(), 100);
    }
  });
});

/* ---------------- Investigation Run ---------------- */
runBtn?.addEventListener('click', async ()=>{
  const question = (issueText?.value||'').trim();
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

    setTimeout(() => {
      completeLoadingOverlay();
      toast(`Investigation complete — ${elapsed}s`, 'ok');
      qs('[data-tab="investigation"]')?.click();
      setTimeout(() => hideLoadingOverlay(), 1200);
    }, 200);

  }catch(err){
    console.error(err);
    toast('Investigation failed: ' + (err.message || 'Unknown error'), 'err');
    hideLoadingOverlay();
  }finally{
    runBtn.disabled = false;
    runBtn.classList.remove('loading');
  }
});

/* ---------------- Renderers ---------------- */
function renderMetrics(m){
  if (!summaryMetrics) return;
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

function renderNarrative(text){
  if (narrativeEl) narrativeEl.textContent = text || 'No narrative available for this investigation.';
}

function renderPath(path){
  if (!lineagePathEl) return;

  if (!path.length){
    lineagePathEl.innerHTML = '<small style="color:var(--text-muted)">No lineage path returned for this entity.</small>';
    return;
  }

  const stageInfo = {
    raw:   { icon: '⬡', name: 'Source',  badge: 'RAW' },
    stage: { icon: '⬢', name: 'Staging', badge: 'STAGE' },
    mart:  { icon: '◆', name: 'Mart',    badge: 'MART' },
  };

  const pieces = [];
  path.forEach((p, idx) => {
    const label = p.label || p.stage || '';
    const stage = (p.stage || '').toLowerCase();
    const info  = stageInfo[stage] || { icon: '●', name: '', badge: stage.toUpperCase() };

    const bal  = p.balance != null ? formatCurrency(p.balance) : '—';
    const tx   = p.txn_count != null ? p.txn_count.toLocaleString() + ' txns' : '';
    const d    = p.delta_balance  != null ? formatCurrency(p.delta_balance)  : null;
    const dPct = p.delta_percent  != null ? (p.delta_percent * 100).toFixed(2) + '%' : null;

    const isPos = p.delta_balance != null && p.delta_balance > 0;
    const isNeg = p.delta_balance != null && p.delta_balance < 0;
    const deltaClass = isPos ? 'delta-change' : isNeg ? 'delta-change-neg' : '';
    const deltaSign  = isPos ? '+' : '';

    pieces.push(`
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

          ${(d || dPct) ? `
            <div class="delta">
              <span class="delta-label">Δ prev</span>
              <span class="delta-value ${deltaClass}">
                ${deltaSign}${escapeHtml(d || '')}
                ${dPct ? ` <span style="opacity:0.7;font-size:10px;">(${escapeHtml(dPct)})</span>` : ''}
              </span>
            </div>` : ''
          }
        </div>
      </div>
    `);

    if (idx < path.length - 1) {
      pieces.push(`
        <div class="path-connector">
          <div class="path-connector-dot"></div>
          <div class="path-connector-dot"></div>
        </div>
      `);
    }
  });

  lineagePathEl.innerHTML = pieces.join('');
}

function renderDiffTable(diffs){
  if (!diffTable) return;

  if (!diffs.length){
    diffTable.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted);font-size:14px;">No row-level diffs for this scope.</div>';
    return;
  }

  const cols = Object.keys(diffs[0]);
  const head = cols.map(c=>`<th>${escapeHtml(c)}</th>`).join('');
  const body = diffs.map(row=>'<tr>'+cols.map(c=>`<td>${escapeHtml(row[c])}</td>`).join('')+'</tr>').join('');

  diffTable.innerHTML = `
    <table>
      <thead><tr>${head}</tr></thead>
      <tbody>${body}</tbody>
    </table>
  `;
}

function renderQueries(queries, totalElapsed){
  if (!queriesContainer) return;

  if (!queries || !queries.length){
    queriesContainer.innerHTML = '<p class="placeholder">No queries generated for this investigation</p>';
    copyQueriesBtn?.classList.add('hidden');
    return;
  }

  const perQuery = totalElapsed ? (totalElapsed / queries.length).toFixed(2) : null;

  queriesContainer.innerHTML = queries.map((q, idx)=>{
    const queryText = typeof q === 'string' ? q : (q.query || q);
    const queryType = typeof q === 'object' ? (q.type || 'SQL') : 'SQL';
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
            <button class="btn btn-sm" type="button" style="background:var(--bg-alt);color:var(--text-muted);border:1px solid var(--border);" data-index="${idx}">Copy</button>
          </div>
        </div>
        <pre><code class="language-sql">${escapeHtml(queryText)}</code></pre>
      </div>
    `;
  }).join('');

  if (window.hljs) hljs.highlightAll();

  qsa('[data-index]', queriesContainer).forEach(btn=>{
    btn.addEventListener('click', e=>{
      const idx = e.currentTarget.dataset.index;
      const qt  = typeof queries[idx]==='string' ? queries[idx] : (queries[idx].query||queries[idx]);
      navigator.clipboard.writeText(qt).then(()=>toast('Query copied','ok')).catch(()=>toast('Copy failed','err'));
    });
  });

  copyQueriesBtn?.classList.remove('hidden');
}

function renderResults(results){
  if (!resultsContainer) return;

  if (!results){
    resultsContainer.innerHTML = '<p class="placeholder">No results available for this investigation</p>';
    copyResultsBtn?.classList.add('hidden');
    return;
  }

  const arr = Array.isArray(results) ? results : [results];
  if (!arr.length){
    resultsContainer.innerHTML = '<p class="placeholder">No results data available</p>';
    copyResultsBtn?.classList.add('hidden');
    return;
  }

  resultsContainer.innerHTML = arr.map((result, idx)=>{
    if (typeof result === 'string'){
      return `<div class="result-block" style="animation-delay:${idx*0.07}s"><pre><code>${escapeHtml(result)}</code></pre></div>`;
    }
    if (result && Array.isArray(result.rows) && result.rows.length){
      const cols = result.columns || (Array.isArray(result.rows[0]) ? [] : Object.keys(result.rows[0]));
      const head = cols.map(c=>`<th>${escapeHtml(c)}</th>`).join('');

      let body = '';
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
  copyResultsBtn?.classList.remove('hidden');
}

/* ---------------- Copy Buttons ---------------- */
copyQueriesBtn?.addEventListener('click', ()=>{
  const text = qsa('.query-block pre code', queriesContainer).map(el=>el.textContent).join('\n\n---\n\n');
  if (!text){ toast('No queries to copy','err'); return; }
  navigator.clipboard.writeText(text).then(()=>toast('All queries copied','ok')).catch(()=>toast('Failed to copy','err'));
});

copyResultsBtn?.addEventListener('click', ()=>{
  const text = qsa('.result-block', resultsContainer).map(el=>el.textContent).join('\n\n---\n\n');
  if (!text){ toast('No results to copy','err'); return; }
  navigator.clipboard.writeText(text).then(()=>toast('All results copied','ok')).catch(()=>toast('Failed to copy','err'));
});

/* ---------------- Export CSV ---------------- */
exportCsvBtn?.addEventListener('click', ()=>{
  if (!diffTable?.querySelector('table')){ toast('No diff data to export.','err'); return; }

  const rows = [];
  rows.push(Array.from(diffTable.querySelectorAll('thead th')).map(th=>th.textContent.trim()));
  diffTable.querySelectorAll('tbody tr').forEach(tr=>{
    rows.push(Array.from(tr.querySelectorAll('td')).map(td=>td.textContent.trim()));
  });

  const csv  = rows.map(r=>r.map(escapeCsv).join(',')).join('\n');
  const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
  const url  = URL.createObjectURL(blob);

  const a = document.createElement('a');
  a.href = url; a.download = 'lineage_diffs.csv';
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);

  toast('Exported CSV','ok');
});

/* ---------------- Chatbot ---------------- */
const chatbotFAQs = {
  'How do I use this tool?': 'Start with one Demo Starter. Click Investigate, then walk through Summary, Narrative, Lineage Path, and finally SQL/Results to prove traceability.',
  'What is SQL and Results?': 'This tab shows the exact SQL used for the answer and the returned rows, so clients can audit every claim.',
  'What is Detailed Analysis?': 'Detailed Analysis lists row-level raw vs stage deltas and highlights which accounts create the customer-level drift.',
  'What are Sample Tables?': 'Sample Tables previews raw, stage, and mart schemas plus data slices, helpful for explaining transformation flow.',
  'What is Data Lineage Path?': 'Lineage Path visualizes how values move from raw ingestion to staging cleanup to mart aggregation.',
  'How does Investigation work?': 'The system parses your question, picks focus entity + metric, runs reconciliation queries, and generates an evidence-backed narrative.'
};

function initChatbot(){
  const toggle = qs('#chatbotToggle');
  const close  = qs('#chatbotClose');
  const panel  = qs('#chatbotPanel');
  const content= qs('#chatbotContent');

  if (!toggle || !panel) return;

  toggle.addEventListener('click', (e) => {
    e.preventDefault();
    panel.classList.toggle('hidden');
  });

  close?.addEventListener('click', (e) => {
    e.preventDefault();
    panel.classList.add('hidden');
  });

  qsa('.faq-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const question = btn.dataset.question;
      const answer = chatbotFAQs[question];
      if (!answer || !content) return;

      const userMsg = document.createElement('div');
      userMsg.className = 'chatbot-message user';
      userMsg.innerHTML = `<p>${escapeHtml(question)}</p>`;
      content.appendChild(userMsg);

      const assistantMsg = document.createElement('div');
      assistantMsg.className = 'chatbot-message assistant';
      assistantMsg.innerHTML = `<p>${escapeHtml(answer)}</p>`;
      content.appendChild(assistantMsg);

      content.scrollTop = content.scrollHeight;
    });
  });

  qsa('.chatbot-prompt-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const prompt = btn.dataset.prompt;
      if (!prompt || !issueText) return;

      issueText.value = prompt;
      issueText.focus();
      toast('Question added. Click Investigate to run.', 'ok');

      if (!content) return;

      const userMsg = document.createElement('div');
      userMsg.className = 'chatbot-message user';
      userMsg.innerHTML = `<p>${escapeHtml(`Use this question: ${prompt}`)}</p>`;
      content.appendChild(userMsg);

      const assistantMsg = document.createElement('div');
      assistantMsg.className = 'chatbot-message assistant';
      assistantMsg.innerHTML = '<p>Loaded into the investigation box. Run it and then open SQL & Results for explainability.</p>';
      content.appendChild(assistantMsg);

      content.scrollTop = content.scrollHeight;
    });
  });
}

/* ---------------- Utilities ---------------- */
function escapeHtml(x){
  if (x==null) return '';
  return String(x).replace(/[&<>"']/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
function escapeCsv(x){
  const s = String(x??'');
  return /[",\n]/.test(s) ? `"${s.replace(/"/g,'""')}"` : s;
}
function formatCurrency(v){
  if (v==null || isNaN(Number(v))) return '—';
  return Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
}

/* ---------------- Boot ---------------- */
document.addEventListener('DOMContentLoaded', async () => {
  initTabs();
  initChatbot();

  try{
    await Promise.all([pingServerHealth(true), loadSummary(), loadPreview()]);
    toast('MCPilot Lineage ready', 'ok');
  }catch{
    setServerStatus(false, 'Disconnected');
    toast('Loaded UI, but failed initial data fetch.', 'warn');
  }

  setInterval(() => {
    pingServerHealth(true);
  }, 10000);
});
