const qs = (s, el=document)=>el.querySelector(s);
const qsa = (s, el=document)=>Array.from(el.querySelectorAll(s));

const issueText = qs('#issueText');
const focusBy = qs('#focusBy');
const focusId = qs('#focusId');
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
const seedBtn = qs('#seedBtn');      // seed demo data button
const exportCsvBtn = qs('#exportCsv');

function toast(msg, type='ok'){
  const box = qs('#toasts');
  if (!box) {
    console.log(type.toUpperCase(), msg);
    return;
  }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(()=>{
    el.style.opacity = 0;
    setTimeout(()=> el.remove(), 350);
  }, 3000);
}

/* Info tooltips */
document.addEventListener('mouseover', e=>{
  const t = e.target.closest('.info');
  if (!t || !t.dataset.tooltip) return;
  tooltip.textContent = t.dataset.tooltip;
  tooltip.classList.remove('hidden');
  const rect = t.getBoundingClientRect();
  const tx = rect.left + window.scrollX + 18;
  const ty = rect.top + window.scrollY + 4;
  tooltip.style.left = tx + 'px';
  tooltip.style.top = ty + 'px';
});
document.addEventListener('mouseout', e=>{
  if (e.target.closest('.info')){
    tooltip.classList.add('hidden');
  }
});

/* API helpers */
async function getJSON(url){
  const r = await fetch(url);
  if (!r.ok){
    const txt = await r.text();
    throw new Error(txt || r.statusText);
  }
  return r.json();
}

async function health(){
  try{
    const j = await getJSON('/lineage-api/health');
    toast(`Lineage API OK${j.db ? ' • DB: '+j.db : ''}`, 'ok');
  }catch(err){
    toast('Lineage API health failed', 'err');
    console.error(err);
  }
}
if (healthBtn) {
  healthBtn.addEventListener('click', health);
}

/* SEED demo data */
if (seedBtn) {
  seedBtn.addEventListener('click', async ()=>{
    try{
      seedBtn.disabled = true;
      seedBtn.textContent = 'Seeding…';

      const resp = await fetch('/lineage-api/seed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      if (!resp.ok) throw new Error(await resp.text());
      const j = await resp.json();
      console.log('Seed response', j);

      toast('Demo lineage data seeded.', 'ok');

      // refresh UI so rows show up
      await Promise.all([loadSummary(), loadPreview()]);
    }catch(err){
      console.error(err);
      toast('Failed to seed lineage data.', 'err');
    }finally{
      seedBtn.disabled = false;
      seedBtn.textContent = 'Seed demo data';
    }
  });
}

/* Stage summary */
async function loadSummary(){
  try{
    const j = await getJSON('/lineage-api/summary');
    renderStages(j.stages || []);
  }catch(err){
    console.error(err);
    stageStrip.innerHTML = '<small style="color:#fca5a5;">Failed to load stage summary.</small>';
  }
}

function renderStages(stages){
  if (!stages.length){
    stageStrip.innerHTML = '<small>No stage summary yet.</small>';
    return;
  }
  stageStrip.innerHTML = stages.map((s, idx)=>{
    const badgeClass =
      s.issues_count > 0 ? 'err' :
      (Math.abs(s.variance_vs_prev || 0) > 0.005 ? 'warn' : 'ok');
    const varPct = s.variance_vs_prev == null ? '—' :
      (s.variance_vs_prev*100).toFixed(2) + '%';
    const dir = (s.variance_vs_prev || 0) > 0 ? '↑' :
                ((s.variance_vs_prev || 0) < 0 ? '↓' : '→');
    return `
      <div class="stage-card">
        <div class="stage-meta">
          <div class="stage-name">${s.label || s.stage_id}</div>
          <div class="stage-tag">${s.role || ''}</div>
        </div>
        <div class="stage-kpis">
          <span class="label">Rows</span>
          <span>${(s.row_count ?? 0).toLocaleString()}</span>
          <span class="label" style="margin-top:2px;">Total balance</span>
          <span>${formatCurrency(s.total_balance)}</span>
        </div>
        <div class="stage-variance">
          <span class="label">Drift vs previous</span>
          <span>${dir} ${varPct}</span>
          <span class="label" style="margin-top:2px;">Issues</span>
          <span class="badge ${badgeClass}">${s.issues_count || 0} open</span>
        </div>
      </div>
    `;
  }).join('');
}

/* Sample tables */
async function loadPreview(){
  previewGrid.innerHTML = '<div class="preview-card"><small>Loading…</small></div>';
  try{
    const j = await getJSON('/lineage-api/preview?limit=5');
    const tables = j.tables || j || [];

    if (!tables.length){
      previewGrid.innerHTML = `
        <div class="preview-card">
          <small>No tables yet. Click <strong>“Seed demo data”</strong> to load sample lineage data.</small>
        </div>
      `;
      return;
    }

    let anyRows = false;

    previewGrid.innerHTML = tables.map(t=>{
      const cols = t.columns || [];
      const rows = t.rows || [];
      if (rows && rows.length) anyRows = true;

      let head = cols.map(c=>`<th>${escapeHtml(c)}</th>`).join('');
      let body = rows.map(r=>
        `<tr>${r.map(v=>`<td>${escapeHtml(v)}</td>`).join('')}</tr>`
      ).join('');
      if (!body){
        body = `<tr><td colspan="${cols.length||1}"><em>No rows</em></td></tr>`;
      }
      return `
        <div class="preview-card">
          <h3>${escapeHtml(t.name || t.table)}</h3>
          <small>${escapeHtml(t.stage || '')}</small>
          <div class="tablewrap" style="margin-top:6px;">
            <table>
              <thead><tr>${head}</tr></thead>
              <tbody>${body}</tbody>
            </table>
          </div>
        </div>
      `;
    }).join('');

    if (!anyRows){
      // Gentle hint if schema exists but is empty.
      toast('Lineage tables have no rows yet. Try “Seed demo data”.', 'warn');
    }

  }catch(err){
    console.error(err);
    previewGrid.innerHTML = '<div class="preview-card"><small style="color:#fca5a5;">Failed to load sample tables.</small></div>';
  }
}
if (refreshPreview) {
  refreshPreview.addEventListener('click', loadPreview);
}

/* Investigation run */
if (runBtn) {
  runBtn.addEventListener('click', async ()=>{
    const issue = (issueText.value || '').trim();
    const fb = (focusBy.value || 'account').trim();
    const id = (focusId.value || '').trim();
    if (!id){
      toast('Please enter an identifier (e.g. account id).', 'err');
      return;
    }
    runBtn.disabled = true;
    runBtn.textContent = 'Investigating…';

    try{
      const qsParams = new URLSearchParams({
        focusBy: fb,
        identifier: id,
        issue: issue
      });
      const j = await getJSON('/lineage-api/reconcile?' + qsParams.toString());

      renderMetrics(j.metrics || {});
      renderNarrative(j.narrative || '', fb, id);
      renderPath(j.path || []);
      renderDiffTable(j.diffs || []);

      toast('Lineage investigation completed', 'ok');
    }catch(err){
      console.error(err);
      toast('Investigation failed', 'err');
    }finally{
      runBtn.disabled = false;
      runBtn.textContent = 'Run Lineage Investigation';
    }
  });
}

/* Render metrics */
function renderMetrics(m){
  summaryMetrics.innerHTML = '';

  const blocks = [];
  if (m.raw_balance != null || m.stage_balance != null || m.mart_balance != null){
    const grossDrift = m.gross_drift != null ? formatCurrency(m.gross_drift) : '—';
    blocks.push({
      label:'Total balance drift',
      value: grossDrift,
      tag:`raw: ${formatCurrency(m.raw_balance)} • mart: ${formatCurrency(m.mart_balance)}`
    });
  }
  if (m.discrepant_accounts != null){
    blocks.push({
      label:'Accounts with discrepancies',
      value: m.discrepant_accounts.toLocaleString(),
      tag:`max variance: ${m.max_variance_percent != null ? (m.max_variance_percent*100).toFixed(2)+'%' : '—'}`
    });
  }
  if (m.total_transactions != null){
    blocks.push({
      label:'Transactions considered',
      value: m.total_transactions.toLocaleString(),
      tag:`period: ${m.window || 'full'}` 
    });
  }

  if (!blocks.length){
    summaryMetrics.innerHTML = '<small>No metrics available for this focus.</small>';
    return;
  }

  summaryMetrics.innerHTML = blocks.map(b=>`
    <div class="metric">
      <div class="metric-label">${escapeHtml(b.label)}</div>
      <div class="metric-value">${escapeHtml(b.value)}</div>
      <div class="metric-tag">${escapeHtml(b.tag || '')}</div>
    </div>
  `).join('');
}

/* Narrative */
function renderNarrative(text, fb, id){
  if (!text){
    narrativeEl.textContent = `No explicit narrative returned yet for ${fb} ${id}.`;
  }else{
    narrativeEl.textContent = text;
  }
}

/* Lineage path */
function renderPath(path){
  if (!path.length){
    lineagePathEl.innerHTML = '<small>No lineage path returned for this entity.</small>';
    return;
  }
  lineagePathEl.innerHTML = path.map(p=>{
    const label = p.label || p.stage;
    const stage = p.stage || '';
    const bal = p.balance != null ? formatCurrency(p.balance) : '—';
    const tx = p.txn_count != null ? `${p.txn_count.toLocaleString()} txns` : '';
    const d = p.delta_balance != null ? formatCurrency(p.delta_balance) : null;
    const dPct = p.delta_percent != null ? (p.delta_percent*100).toFixed(2)+'%' : null;
    const deltaText = (d || dPct) ? `${d || ''} (${dPct || '—'})` : '—';

    return `
      <div class="path-node">
        <h4>${escapeHtml(label)}</h4>
        <div class="stage">${escapeHtml(stage)}</div>
        <div class="delta">Balance: ${bal}</div>
        ${tx ? `<div class="delta">Volume: ${tx}</div>` : ''}
        <div class="delta">Δ vs prev: ${escapeHtml(deltaText)}</div>
      </div>
    `;
  }).join('');
}

/* Diff table */
function renderDiffTable(diffs){
  if (!diffs.length){
    diffTable.innerHTML = '<small>No row-level diffs for this scope.</small>';
    return;
  }
  const cols = Object.keys(diffs[0]);
  let head = cols.map(c=>`<th>${escapeHtml(c)}</th>`).join('');
  let body = diffs.map(row=>{
    return '<tr>' + cols.map(c=>`<td>${escapeHtml(row[c])}</td>`).join('') + '</tr>';
  }).join('');
  diffTable.innerHTML = `
    <div class="tablewrap">
      <table>
        <thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

/* Export CSV */
if (exportCsvBtn) {
  exportCsvBtn.addEventListener('click', ()=>{
    if (!diffTable.querySelector('table')){
      toast('No diff data to export.', 'err');
      return;
    }
    const rows = [];
    const ths = Array.from(diffTable.querySelectorAll('thead th')).map(th=>th.textContent.trim());
    rows.push(ths);
    diffTable.querySelectorAll('tbody tr').forEach(tr=>{
      const tds = Array.from(tr.querySelectorAll('td')).map(td=>td.textContent.trim());
      rows.push(tds);
    });
    const csv = rows.map(r=>r.map(escapeCsv).join(',')).join('\n');
    const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'lineage_diffs.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast('Exported CSV', 'ok');
  });
}

/* Utils */
function escapeHtml(x){
  if (x == null) return '';
  return String(x).replace(/[&<>"']/g, m=>({
    '&':'&amp;',
    '<':'&lt;',
    '>':'&gt;',
    '"':'&quot;',
    "'":'&#39;'
  }[m]));
}
function escapeCsv(x){
  const s = String(x ?? '');
  if (/[",\n]/.test(s)){
    return `"${s.replace(/"/g,'""')}"`;
  }
  return s;
}
function formatCurrency(v){
  if (v == null || isNaN(Number(v))) return '—';
  return Number(v).toLocaleString(undefined,{minimumFractionDigits:2, maximumFractionDigits:2});
}

/* Boot */
(async function init(){
  await Promise.all([loadSummary(), loadPreview()]);
  toast('Lineage Investigator ready', 'ok');
})();
