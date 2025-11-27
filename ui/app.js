const qs = (s, el=document)=>el.querySelector(s);
const qsa = (s, el=document)=>Array.from(el.querySelectorAll(s));

const chat = qs('#chat');
const promptEl = qs('#prompt');
const sendBtn = qs('#sendBtn');
const typing = qs('#typing');
const statusDot = qs('#statusDot');
const statusText = qs('#statusText');
const activeTabChip = qs('#activeTabChip');

const paneSQL = qs('#pane-sql');
const paneGraph = qs('#pane-graph');
const paneTables = qs('#pane-tables');

const sqlCode = qs('#sqlCode');
const copySql = qs('#copySql');
const sqlSummary = qs('#sqlSummary');
const sqlTable = qs('#sqlTable');

const modelSel = qs('#modelSel');
const modelActive = qs('#modelActive');

const graphCode = qs('#graphCode');
const copyCypher = qs('#copyCypher');
const cypherArea = qs('#cypher');
const runVizBtn = qs('#runViz');
const graphTable = qs('#graphTable');
const graphMount = qs('#graphMount');

const refreshTablesBtn = qs('#refreshTables');
const tablesGrid = qs('#tablesGrid');

let activeTab = 'sql'; // 'sql' | 'graph' | 'tables'
let lastSQL = '';

/* ---- UI helpers ---- */
function toast(msg, type='ok'){ 
  const box = qs('#toasts');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(()=>{ el.style.opacity=0; setTimeout(()=>el.remove(), 400) }, 3200);
}

function addMsg(role, text){
  const wrap = document.createElement('div');
  wrap.className = 'msg';
  const avatar = document.createElement('div');
  avatar.className = `avatar ${role==='user'?'user':''}`;
  const bubble = document.createElement('div');
  bubble.className = `bubble ${role==='ai'?'ai':''}`;
  bubble.innerHTML = text.replace(/\n/g,'<br/>');
  wrap.append(avatar, bubble);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
}

function setBusy(b){
  if (b){ typing.classList.remove('hide'); statusDot.classList.remove('idle'); statusDot.classList.add('busy'); statusText.textContent = 'Thinking…'; }
  else { typing.classList.add('hide'); statusDot.classList.remove('busy'); statusDot.classList.add('idle'); statusText.textContent = 'Ready'; }
}

/* ---- Tabs ---- */
qsa('.tab').forEach(btn=>{
  btn.addEventListener('click', ()=>{
    qsa('.tab').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    activeTab = btn.dataset.tab;
    activeTabChip.textContent = btn.textContent;
    paneSQL.classList.toggle('hide', activeTab!=='sql');
    paneGraph.classList.toggle('hide', activeTab!=='graph');
    paneTables.classList.toggle('hide', activeTab!=='tables');
    if (activeTab==='tables') loadTables();
  });
});

/* ---- Quick prompts ---- */
qsa('.qpills button').forEach(b=>{
  b.addEventListener('click', ()=>{ promptEl.value = b.dataset.fill; promptEl.focus(); });
});

/* ---- Model ---- */
async function loadConfig(){
  try{
    const r = await fetch('/config'); const j = await r.json();
    modelActive.textContent = `model: ${j.llm_model||'—'}`;
    const allow = [
      "anthropic.claude-3-5-sonnet-20241022-v2:0",
      "us.anthropic.claude-sonnet-4-20250514-v1:0",
      "amazon.nova-pro-v1:0",
      "amazon.nova-lite-v1:0",
      "amazon.nova-micro-v1:0",
      "amazon.titan-text-lite-v1",
      "amazon.titan-text-express-v1",
      "anthropic.claude-3-haiku-20240307-v1:0",
      "anthropic.claude-3-5-sonnet-20240620-v1:0",
      "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
      "us.anthropic.claude-3-5-haiku-20241022-v1:0",
      "cohere.command-r-v1:0",
      "cohere.command-r-plus-v1:0",
      "meta.llama3-8b-instruct-v1:0",
      "meta.llama3-70b-instruct-v1:0",
      "us.meta.llama3-2-1b-instruct-v1:0",
      "us.meta.llama3-2-3b-instruct-v1:0",
      "us.meta.llama3-3-70b-instruct-v1:0",
      "mistral.mistral-7b-instruct-v0:2",
      "mistral.mixtral-8x7b-instruct-v0:1",
      "mistral.mistral-large-2402-v1:0",
      "mistral.mistral-small-2402-v1:0",
      "us.mistral.pixtral-large-2502-v1:0",
    ];
    modelSel.innerHTML = allow.map(m=>`<option ${j.llm_model===m?'selected':''}>${m}</option>`).join('');
  }catch{ /* ignore */ }
}
qs('#healthBtn').addEventListener('click', async ()=>{
  try{ const r = await fetch('/health'); const j = await r.json(); toast(`OK • DB: ${j.db} • SQLite: ${j.sqlite}`, 'ok'); }
  catch{ toast('Health check failed', 'err'); }
});
modelSel.addEventListener('change', async ()=>{
  try{
    const r = await fetch('/config/model',{ method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({model: modelSel.value})});
    const j = await r.json();
    if (j.ok){ modelActive.textContent = `model: ${j.llm_model}`; toast('Model updated'); }
    else toast('Model update failed','err');
  }catch{ toast('Model update failed','err'); }
});

/* ---- Sending ---- */
sendBtn.addEventListener('click', send);
promptEl.addEventListener('keydown', e=>{
  if (e.key==='Enter' && !e.shiftKey){ e.preventDefault(); send(); }
});
function autoGrow(){
  promptEl.style.height='auto';
  promptEl.style.height = Math.min(promptEl.scrollHeight, 160)+'px';
}
promptEl.addEventListener('input', autoGrow);

async function send(){
  const q = (promptEl.value||'').trim();
  if (!q) return;
  addMsg('user', q);
  promptEl.value=''; autoGrow();
  setBusy(true);

  try{
    if (activeTab==='graph'){
      // GraphRAG endpoint returns: { cypher, columns, rows, graph, source }
      const r = await fetch(`/ask?q=${encodeURIComponent(q)}&include_graph=true`);
      if (!r.ok){
        const txt = await r.text();
        throw new Error(txt || 'GraphRAG error');
      }
      const j = await r.json();

      // Render Cypher into Graph pane ONLY
      setCypherCode(j.cypher || '/* no cypher */');

      // Fill the custom viz textarea so user can tweak & re-run
      if (j.cypher) cypherArea.value = j.cypher;

      // Render GraphRAG results table
      renderTable(graphTable, j.columns||[], j.rows||[]);

      // Render visualization
      renderGraph(j.graph || {nodes:[], links:[]});

      addMsg('ai', `<strong>GraphRAG</strong><span class="small">Rows: ${(j.rows||[]).length} • source: ${j.source||'llm'}</span>`);
    }else{
      // SQL endpoint returns: { sql, columns, rows, summary, source }
      const r = await fetch(`/ask-sql?q=${encodeURIComponent(q)}`);
      if (!r.ok){
        const txt = await r.text();
        throw new Error(txt || 'SQL error');
      }
      const j = await r.json();
      lastSQL = j.sql || '';
      showSQL(lastSQL);
      showSummary(j.summary, j.source);
      renderTable(sqlTable, j.columns||[], j.rows||[]);
      addMsg('ai', `<strong>SQL</strong><span class="small">${j.summary || ''}</span>`);
    }
  }catch(err){
    console.error(err);
    toast('Request failed', 'err');
    addMsg('ai', `⚠️ <em>${String(err).slice(0,200)}</em>`);
  }finally{
    setBusy(false);
  }
}

/* ---- SQL Pane rendering ---- */
function showSQL(sql){
  sqlCode.textContent = (sql||'').trim();
  if (window.hljs) hljs.highlightElement(sqlCode);
}
copySql.addEventListener('click', ()=>{
  if (!sqlCode.textContent) return;
  navigator.clipboard.writeText(sqlCode.textContent);
  copySql.textContent='Copied!';
  setTimeout(()=>copySql.textContent='Copy SQL', 1200);
});
function showSummary(s, source){
  sqlSummary.textContent = s + (source ? `  •  source: ${source}` : '');
}

/* ---- GraphRAG code block ---- */
function setCypherCode(cy){
  graphCode.textContent = (cy||'').trim();
  if (window.hljs) hljs.highlightElement(graphCode);
}
copyCypher.addEventListener('click', ()=>{
  if (!graphCode.textContent) return;
  navigator.clipboard.writeText(graphCode.textContent);
  copyCypher.textContent='Copied!';
  setTimeout(()=>copyCypher.textContent='Copy Cypher', 1200);
});

/* ---- Generic table renderer ---- */
function renderTable(containerEl, cols, rows){
  if (!containerEl) return;
  if (!cols.length){
    containerEl.innerHTML = '<div class="summary">No columns.</div>';
    return;
  }
  let html = '<table><thead><tr>';
  cols.forEach(c=> html += `<th>${escapeHtml(c)}</th>`);
  html += '</tr></thead><tbody>';
  rows.forEach(r=>{
    html += '<tr>' + r.map(v=>`<td>${v===null?'':escapeHtml(v)}</td>`).join('') + '</tr>';
  });
  html += '</tbody></table>';
  containerEl.innerHTML = html;
}
function escapeHtml(x){
  return String(x).replace(/[&<>"']/g, m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
}

/* ---- Graph Viz ---- */
runVizBtn.addEventListener('click', async ()=>{
  try{
    const body = { cypher: cypherArea.value, params: {} };
    const r = await fetch('/viz', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (!r.ok){ throw new Error(await r.text()); }
    const j = await r.json();
    renderGraph(j);
    toast('Graph rendered');
  }catch(e){ toast('Graph render failed','err'); }
});

let sim; // d3 force sim
function renderGraph(g){
  graphMount.innerHTML='';
  const width = graphMount.clientWidth || 700;
  const height = graphMount.clientHeight || 420;

  const svg = d3.select(graphMount).append('svg')
    .attr('width', width).attr('height', height)
    .style('border-radius','12px');

  const container = svg.append('g');

  const zoom = d3.zoom().on('zoom', (e)=> container.attr('transform', e.transform));
  svg.call(zoom);
  svg.call(zoom.transform, d3.zoomIdentity.translate(width/2, height/2).scale(0.9));

  const link = container.append('g')
    .attr('stroke', '#2b3750').attr('stroke-opacity', 0.9)
    .selectAll('line')
    .data(g.links||[])
    .enter().append('line')
    .attr('stroke-width', 1.2);

  const nodesData = (g.nodes||[]).map(n=>({ ...n }));

  const node = container.append('g')
    .selectAll('circle')
    .data(nodesData)
    .enter().append('circle')
    .attr('r', 8)
    .attr('fill', d=> colorFor(d.label))
    .attr('stroke', '#0b1220')
    .attr('stroke-width', 1.4)
    .call(drag(sim));

  const label = container.append('g')
    .selectAll('text')
    .data(nodesData)
    .enter().append('text')
    .text(d=> (d.props && (d.props.full_name || d.props.account_id || d.props.symbol)) || d.label)
    .attr('font-size','11px').attr('fill','#cfe6ff').attr('dy','-0.9em');

  node.append('title').text(d => {
    const props = d.props || {};
    const lines = Object.entries(props).map(([k,v])=>`${k}: ${v}`);
    return `${d.label}\n${lines.join('\n')}`;
  });

  sim = d3.forceSimulation(nodesData)
    .force('link', d3.forceLink(g.links||[]).id(d=>d.id).distance(70).strength(0.12))
    .force('charge', d3.forceManyBody().strength(-180))
    .force('center', d3.forceCenter(0,0))
    .on('tick', ticked);

  function ticked(){
    link
      .attr('x1', d=> d.source.x)
      .attr('y1', d=> d.source.y)
      .attr('x2', d=> d.target.x)
      .attr('y2', d=> d.target.y);
    node
      .attr('cx', d=> d.x)
      .attr('cy', d=> d.y);
    label
      .attr('x', d=> d.x)
      .attr('y', d=> d.y);
  }

  function drag(sim){
    function dragstarted(event){
      if (!event.active) sim.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
    }
    function dragged(event){
      event.subject.fx = event.x;
      event.subject.fy = event.y;
    }
    function dragended(event){
      if (!event.active) sim.alphaTarget(0);
      event.subject.fx = null;
      event.subject.fy = null;
    }
    return d3.drag().on('start',dragstarted).on('drag',dragged).on('end',dragended);
  }

  function colorFor(lbl){
    const map = {
      Customer: '#4cc9f0',
      Account: '#b5179e',
      Transaction: '#f59e0b',
      SecurityPosition: '#22c55e',
      TimeDeposit: '#ef4444',
    };
    return map[lbl] || '#94a3b8';
  }
}

/* ---- Tables preview ---- */
async function loadTables(){
  tablesGrid.innerHTML = '<div class="card"><small>Loading…</small></div>';
  try{
    const r = await fetch('/tables/preview?limit=5');
    const j = await r.json();
    const html = j.map(t=>{
      let head = t.columns.map(c=>`<th>${c}</th>`).join('');
      let body = (t.rows||[]).map(row=>`<tr>${row.map(v=>`<td>${escapeHtml(v)}</td>`).join('')}</tr>`).join('');
      if (!body) body = `<tr><td colspan="${t.columns.length}"><em>No rows</em></td></tr>`;
      return `
        <div class="card">
          <h4>${t.table}</h4>
          <small>${t.columns.length} column(s)</small>
          <div class="tablewrap" style="margin-top:8px;">
            <table>
              <thead><tr>${head}</tr></thead>
              <tbody>${body}</tbody>
            </table>
          </div>
        </div>
      `;
    }).join('');
    tablesGrid.innerHTML = html;
  }catch{
    tablesGrid.innerHTML = '<div class="card"><small>Failed to load tables.</small></div>';
  }
}

/* ---- Boot ---- */
(async function init(){
  await loadConfig();
  loadTables();
  addMsg('ai', 'Hi! I’m your data copilot. Ask a question or pick a quick prompt to begin.');
})();
