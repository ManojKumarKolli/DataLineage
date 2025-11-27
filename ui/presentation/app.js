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
    if (!id.startsWith('#')) return; // external
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
  const N = 80;
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

  // Reveal cards / lifts
  gsap.utils.toArray('.lift').forEach(el=>{
    gsap.to(el, {
      y:0, opacity:1, duration:.6, ease:'power2.out',
      scrollTrigger:{ trigger: el, start:'top 75%' }
    });
  });

  // Sticky steps stagger
  document.querySelectorAll('.sticky .step').forEach((el, idx)=>{
    gsap.to(el, {
      y:0, opacity:1, duration:.6, delay: idx*0.08,
      scrollTrigger:{ trigger: el.closest('.sticky'), start:'top 60%' }
    });
  });

  // Architecture sequence
  const blocks = ['#b-ui','#b-api','#b-llm','#b-sql','#b-graph','#b-data'];
  gsap.from(blocks.map(s=>document.querySelector(s)), {
    opacity:0, scale:.95, duration:.5, stagger:.08,
    scrollTrigger:{ trigger:'#arch', start:'top 60%' }
  });
  gsap.fromTo('.edge', { opacity:.15 }, {
    opacity:.9, duration:1.1, stagger:.12, ease:'power1.out',
    scrollTrigger:{ trigger:'#arch', start:'top 58%' }
  });

  // Flow on edges
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

  // ---- Metrics: cards + counters (robust) ----
  let metricsStarted = false;
  function startMetrics(){
    if (metricsStarted) return;
    metricsStarted = true;

    runCounters();  // will no-op safely if gsap missing

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

  // ScrollTrigger-based start
  ScrollTrigger.create({
    trigger: '#metrics',
    start: 'top 60%',
    onEnter: startMetrics,
    once: true
  });

  // Fallback: IntersectionObserver (in case ST fails or user lands mid-page)
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
  // Cortex Analyst pricing (per successful request)
  cortexApiPerRequest:      0.20, // API fee
  cortexComputePerRequest:  0.04, // assumed compute
  cortexQueryPerRequest:    0.03, // assumed query execution

  // MCPilot pricing (per request)
  mcApiPerRequest:          0.03, // LLM / orchestration
  mcComputePerRequest:      0.02, // compute + warehouse

  baselineRequests:         1_000_000
};

function runCounters(){
  if (!window.gsap) return;

  const {
    cortexApiPerRequest,
    cortexComputePerRequest,
    cortexQueryPerRequest,
    mcApiPerRequest,
    mcComputePerRequest,
    baselineRequests
  } = VALUE_ASSUMPTIONS;

  const cortexPerReq = cortexApiPerRequest + cortexComputePerRequest + cortexQueryPerRequest;
  const mcPerReq     = mcApiPerRequest + mcComputePerRequest;

  const cortexCost = baselineRequests * cortexPerReq;
  const mcCost     = baselineRequests * mcPerReq;
  const savings    = Math.max(0, Math.round(cortexCost - mcCost));

  // Map labels → targets
  const map = {
    'Answer Accuracy': 93,
    'Precision / Relevance': 88,
    'Human Feedback Coverage': 100,
    'Savings / 1M Requests': savings
  };

  // Push targets into counters
  document.querySelectorAll('.metric').forEach(m=>{
    const label = m.querySelector('.label')?.textContent.trim();
    if (label && map[label] != null){
      const span = m.querySelector('.counter');
      span.dataset.target = map[label];
    }
  });

  // Update flip-card back values
  const cortexEl  = document.querySelector('.cortex-cost');
  const mcEl      = document.querySelector('.mc-cost');
  const saveEl    = document.querySelector('.savings-cost');

  if (cortexEl) cortexEl.textContent = '$' + Math.round(cortexCost).toLocaleString();
  if (mcEl)     mcEl.textContent     = '$' + Math.round(mcCost).toLocaleString();
  if (saveEl)   saveEl.textContent   = '$' + Math.round(savings).toLocaleString();

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


document.addEventListener('DOMContentLoaded', () => {
  if (window.gsap) {
    runCounters();
  } else {
    // If for some reason GSAP loads after, try again shortly
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




