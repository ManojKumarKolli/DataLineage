// ---------- Progress ----------
const progress = document.querySelector('#progress span');
function updateProgress(){
  const scrollTop = window.scrollY || document.documentElement.scrollTop;
  const docH = document.documentElement.scrollHeight - document.documentElement.clientHeight;
  const pct = Math.max(0, Math.min(1, scrollTop / (docH || 1)));
  progress.style.width = (pct * 100).toFixed(1) + '%';
}
addEventListener('scroll', updateProgress);
updateProgress();

// ---------- Smooth hash nav ----------
document.querySelectorAll('.quicknav a').forEach(a=>{
  a.addEventListener('click', (e)=>{
    const id = a.getAttribute('href');
    if (!id || !id.startsWith('#')) return; // external link
    e.preventDefault();
    const el = document.querySelector(id);
    if (el) el.scrollIntoView({ behavior:'smooth' });
  });
});

// ---------- Floating Canvas Particles ----------
(function particles(){
  const c = document.getElementById('bgfx');
  const ctx = c.getContext('2d');
  let W, H, dots = [];
  const N = 90;
  function resize(){
    W = c.width = innerWidth * devicePixelRatio;
    H = c.height = innerHeight * devicePixelRatio;
    c.style.width = innerWidth + 'px';
    c.style.height = innerHeight + 'px';
    dots = [...Array(N)].map(()=>({
      x: Math.random()*W, y: Math.random()*H,
      vx: (Math.random()-.5)*0.25*devicePixelRatio,
      vy: (Math.random()-.5)*0.25*devicePixelRatio,
      r: (Math.random()*2+0.6) * devicePixelRatio
    }));
  }
  resize(); addEventListener('resize', resize);
  function step(){
    ctx.clearRect(0,0,W,H);
    ctx.globalAlpha = .6;
    for (const d of dots){
      d.x += d.vx; d.y += d.vy;
      if (d.x<0||d.x>W) d.vx*=-1;
      if (d.y<0||d.y>H) d.vy*=-1;
      ctx.beginPath();
      ctx.arc(d.x, d.y, d.r, 0, Math.PI*2);
      ctx.fillStyle = 'rgba(140,180,255,.55)';
      ctx.fill();
    }
    requestAnimationFrame(step);
  }
  step();
})();

// ---------- Magnetic buttons ----------
document.querySelectorAll('.magnet').forEach(btn=>{
  const strength = 18;
  btn.addEventListener('mousemove', (e)=>{
    const rect = btn.getBoundingClientRect();
    const x = e.clientX - rect.left - rect.width/2;
    const y = e.clientY - rect.top - rect.height/2;
    btn.style.transform = `translate(${x/strength}px, ${y/strength}px)`;
  });
  btn.addEventListener('mouseleave', ()=> btn.style.transform = 'translate(0,0)');
});

// ---------- Keyboard slide nav ----------
const slides = Array.from(document.querySelectorAll('.slide'));
function currentSlideIndex(){
  const mid = scrollY + innerHeight/2;
  let idx=0, min=Infinity;
  slides.forEach((s,i)=>{
    const r = s.getBoundingClientRect();
    const m = r.top + scrollY + r.height/2;
    const d = Math.abs(m-mid);
    if (d<min){ min=d; idx=i; }
  });
  return idx;
}
function gotoSlide(i){
  const t = slides[Math.max(0, Math.min(slides.length-1, i))];
  t && t.scrollIntoView({ behavior:'smooth', block:'start' });
}
addEventListener('keydown', (e)=>{
  const i = currentSlideIndex();
  if (e.key==='ArrowDown' || e.key==='PageDown' || e.key===' ') gotoSlide(i+1);
  if (e.key==='ArrowUp' || e.key==='PageUp' || (e.shiftKey && e.key===' ')) gotoSlide(i-1);
});

// ---------- GSAP animations ----------
addEventListener('load', ()=>{
  if (!window.gsap || !window.ScrollTrigger) return;
  gsap.registerPlugin(ScrollTrigger);

  // Hero title + subtitle
  gsap.from('.hero .title', {
    y: 20,
    opacity: 0,
    duration: 0.7,
    ease: 'power2.out'
  });
  gsap.from('.hero .subtitle', {
    y: 14,
    opacity: 0,
    duration: 0.7,
    delay: 0.1,
    ease: 'power2.out'
  });
  gsap.from('.hero .cta-row', {
    y: 14,
    opacity: 0,
    duration: 0.7,
    delay: 0.2,
    ease: 'power2.out'
  });

  // Reveal any .lift cards, but skip workflow steps (they have their own animation)
  gsap.utils.toArray('.lift').forEach(el=>{
    if (el.closest('.workflow-rail')) return;
    gsap.to(el, {
      y:0,
      opacity:1,
      duration:.6,
      ease:'power2.out',
      scrollTrigger:{ trigger: el, start:'top 80%' }
    });
  });

  // Problem cards hover pop
  gsap.utils.toArray('.problem-card').forEach(el=>{
    el.addEventListener('mouseenter', ()=>{
      gsap.to(el, { scale: 1.02, duration: 0.2, ease: 'power1.out' });
    });
    el.addEventListener('mouseleave', ()=>{
      gsap.to(el, { scale: 1.0, duration: 0.2, ease: 'power1.out' });
    });
  });

  // Workflow rail subtle entrance (no flicker)
  const wf = document.querySelector('.workflow-rail');
  if (wf){
    gsap.from(wf.children, {
      y: 24,
      opacity: 0,
      duration: 0.6,
      ease: 'power2.out',
      stagger: 0.08,
      scrollTrigger: {
        trigger: wf,
        start: 'top 70%',
        toggleActions: 'play none none none'
      }
    });
  }

  // Architecture blocks — Semantic
  const semBlocks = ['#sem-client','#sem-api','#sem-llm','#sem-sql','#sem-data'];
  gsap.from(semBlocks.map(s=>document.querySelector(s)), {
    opacity:0,
    scale:.95,
    duration:.5,
    stagger:.08,
    scrollTrigger:{ trigger:'#arch-semantic', start:'top 65%' }
  });
  gsap.fromTo('.edge-sem', { opacity:.05 }, {
    opacity:.9,
    duration:1.1,
    stagger:.12,
    ease:'power1.out',
    scrollTrigger:{ trigger:'#arch-semantic', start:'top 65%' }
  });

  // Architecture blocks — Lineage
  const linBlocks = ['#lin-client','#lin-api','#lin-llm','#lin-lineage','#lin-data','#lin-lineagedb'];
  gsap.from(linBlocks.map(s=>document.querySelector(s)), {
    opacity:0,
    scale:.95,
    duration:.5,
    stagger:.08,
    scrollTrigger:{ trigger:'#arch-lineage', start:'top 65%' }
  });
  gsap.fromTo('.edge-lin', { opacity:.05 }, {
    opacity:.9,
    duration:1.1,
    stagger:.12,
    ease:'power1.out',
    scrollTrigger:{ trigger:'#arch-lineage', start:'top 65%' }
  });

  // Flow on edges (both diagrams)
  gsap.to('.edge', {
    strokeDasharray:'4 14',
    strokeDashoffset:14,
    duration:1.2,
    ease:'none',
    repeat:-1
  });

  // Hero blobs slow float
  gsap.to('.hero .blob.one', { y:12, x:8, repeat:-1, yoyo:true, duration:3.0, ease:'sine.inOut' });
  gsap.to('.hero .blob.two', { y:-10, x:-6, repeat:-1, yoyo:true, duration:2.6, ease:'sine.inOut' });

  // ---- Metrics: cards + counters ----
  let metricsStarted = false;
  function startMetrics(){
    if (metricsStarted) return;
    metricsStarted = true;

    runCounters();

    gsap.from('#metrics .metric', {
      y:24,
      opacity:0,
      duration:.6,
      ease:'power2.out',
      stagger:.08
    });

    const savingsCard = document.querySelector('#metrics .metric.savings');
    if (savingsCard){
      gsap.to(savingsCard, {
        boxShadow:'0 0 40px rgba(34,197,94,0.4)',
        duration:1.6,
        repeat:-1,
        yoyo:true,
        ease:'sine.inOut'
      });
    }
  }

  ScrollTrigger.create({
    trigger: '#metrics',
    start: 'top 60%',
    onEnter: startMetrics,
    once: true
  });

  // Fallback: IntersectionObserver
  const metricsEl = document.querySelector('#metrics');
  if (metricsEl && 'IntersectionObserver' in window){
    const obs = new IntersectionObserver((entries)=>{
      entries.forEach(e=>{
        if (e.isIntersecting){
          startMetrics();
          obs.disconnect();
        }
      });
    }, { threshold:0.4 });
    obs.observe(metricsEl);
  }
});

// ---------- Value Metrics (configurable) ----------
const VALUE_ASSUMPTIONS = {
  // Warehouse-native copilot pricing (illustrative, per successful request)
  cortexPerRequest:        0.20, // blended query + compute

  // DataGuard Copilot pricing (illustrative, per request)
  mcPerRequest:            0.05, // LLM + light warehouse

  baselineRequests:        1_000_000
};

function runCounters(){
  if (!window.gsap) return;

  const {
    cortexPerRequest,
    mcPerRequest,
    baselineRequests
  } = VALUE_ASSUMPTIONS;

  const cortexCost = baselineRequests * cortexPerRequest;
  const mcCost     = baselineRequests * mcPerRequest;
  const savings    = Math.max(0, Math.round(cortexCost - mcCost));

  // Map labels → targets
  const map = {
    'Answer Accuracy': 93,
    'Precision / Relevance': 88,
    'INC Reduction Potential': 40,
    'Savings / 1M Requests': savings
  };

  // Push targets into counters
  document.querySelectorAll('.metric').forEach(m=>{
    const label = m.querySelector('.label')?.textContent.trim();
    if (label && Object.prototype.hasOwnProperty.call(map, label)){
      const span = m.querySelector('.counter');
      if (span) span.dataset.target = map[label];
    }
  });

  // Update flip-card back values & pricing note
  const cortexEl  = document.querySelector('.cortex-cost');
  const mcEl      = document.querySelector('.mc-cost');
  const saveEl    = document.querySelector('.savings-cost');

  if (cortexEl) cortexEl.textContent = '$' + Math.round(cortexCost).toLocaleString();
  if (mcEl)     mcEl.textContent     = '$' + Math.round(mcCost).toLocaleString();
  if (saveEl)   saveEl.textContent   = '$' + Math.round(savings).toLocaleString();

  const pReqs   = document.querySelector('.price-requests');
  const pCortex = document.querySelector('.price-cortex-req');
  const pMc     = document.querySelector('.price-mc-req');
  const pCTotal = document.querySelector('.price-cortex-total');
  const pMTotal = document.querySelector('.price-mc-total');
  const pS      = document.querySelector('.price-savings-total');

  if (pReqs)   pReqs.textContent   = baselineRequests.toLocaleString();
  if (pCortex) pCortex.textContent = `$${cortexPerRequest.toFixed(2)}`;
  if (pMc)     pMc.textContent     = `$${mcPerRequest.toFixed(2)}`;
  if (pCTotal) pCTotal.textContent = '$' + Math.round(cortexCost).toLocaleString();
  if (pMTotal) pMTotal.textContent = '$' + Math.round(mcCost).toLocaleString();
  if (pS)      pS.textContent      = '$' + Math.round(savings).toLocaleString();

  // Animate counters
  document.querySelectorAll('.counter').forEach(el=>{
    const target = parseFloat(el.dataset.target || '0');
    const suffix = el.dataset.suffix || '';
    const prefix = el.dataset.prefix || '';
    const dur = 1.2 + Math.random() * 0.6;

    const obj = { v: 0 };
    gsap.to(obj, {
      v: target,
      duration: dur,
      ease:'power2.out',
      onUpdate: ()=>{
        const num = Math.round(obj.v);
        el.textContent = prefix + num.toLocaleString() + suffix;
      }
    });
  });
}

// Try to start counters if GSAP already loaded
document.addEventListener('DOMContentLoaded', () => {
  if (window.gsap) {
    runCounters();
  } else {
    setTimeout(() => { window.gsap && runCounters(); }, 300);
  }
});

// ---------- Cost card flip ----------
document.addEventListener('click', (e)=>{
  const card = e.target.closest('#cost-card');
  if (card){
    card.classList.toggle('flipped');
  }
});
