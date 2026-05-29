/* ══════════════════════════════════════════
   ZIYOU ANALYTICS — app.js
   Login · Config · Snapshots · Comparação · Insights
   ══════════════════════════════════════════ */

'use strict';

// ─────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────

const fmt = {
  currency: v =>
    'R$ ' + (v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  number:   v => (v || 0).toLocaleString('pt-BR'),
  date:     d => new Date(d).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }),
  datetime: iso => {
    try {
      return new Date(iso).toLocaleString('pt-BR', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      });
    } catch { return iso; }
  },
  pct: v => (v > 0 ? '+' : '') + v.toFixed(1) + '%',
};

function escapeHtml(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function last30Days() {
  const days = [], today = new Date();
  for (let i = 29; i >= 0; i--) {
    const d = new Date(today); d.setDate(d.getDate() - i);
    days.push(d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }));
  }
  return days;
}

async function sha256(str) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

// ─────────────────────────────────────────────
// LOADING / ERROR
// ─────────────────────────────────────────────

function setLoadingText(msg) {
  const el = document.getElementById('loadingText');
  if (el) el.textContent = msg;
}

function showLoading(v) {
  document.getElementById('loadingOverlay').style.display = v ? 'flex' : 'none';
}

function showError(msg) {
  document.getElementById('loadingOverlay').style.display = 'none';
  document.getElementById('errorOverlay').style.display   = 'flex';
  document.getElementById('errorMessage').textContent     = msg;
}

// ─────────────────────────────────────────────
// FETCH HELPERS
// ─────────────────────────────────────────────

async function fetchJSON(url) {
  const r = await fetch(url + '?_=' + Date.now());
  if (!r.ok) throw new Error(`HTTP ${r.status} — ${url}`);
  return r.json();
}

// ─────────────────────────────────────────────
// CONFIG  — carrega config.json e aplica branding
// ─────────────────────────────────────────────

async function loadConfig() {
  try { return await fetchJSON('config.json'); } catch { return {}; }
}

function applyBranding(cfg) {
  if (!cfg.client_name) return;

  const logo    = cfg.logo_text || cfg.client_name.charAt(0).toUpperCase();
  const from    = cfg.logo_gradient_from || '#ffe600';
  const to      = cfg.logo_gradient_to   || '#ff9500';
  const accent  = cfg.accent_color       || '#4f8ef7';
  const name    = cfg.client_name;

  // Sidebar
  const sLogo = document.getElementById('sidebarLogo');
  const sName = document.getElementById('sidebarClientName');
  const lLogo = document.getElementById('loadingLogo');
  const llLogo= document.getElementById('loginLogo');
  const liTit = document.getElementById('loginTitle');
  const tBar  = document.getElementById('topbarTitle');

  if (sLogo)  { sLogo.textContent = logo; sLogo.style.background = `linear-gradient(135deg,${from},${to})`; }
  if (sName)  sName.textContent = name;
  if (lLogo)  { lLogo.textContent = logo; lLogo.style.background = `linear-gradient(135deg,${from},${to})`; }
  if (llLogo) { llLogo.textContent = logo; llLogo.style.background = `linear-gradient(135deg,${from},${to})`; }
  if (liTit)  liTit.textContent = name + ' Analytics';
  if (tBar)   tBar.textContent  = name + ' Analytics';

  // Accent CSS var
  document.documentElement.style.setProperty('--accent-blue', accent);

  // Título do documento
  document.title = `${name} — Analytics Dashboard`;
}

// ─────────────────────────────────────────────
// AUTH  — login com SHA-256
// ─────────────────────────────────────────────

const AUTH_KEY = 'ziyou_auth';

function isAuthenticated(cfg) {
  if (!cfg.features?.password_protection || !cfg.password_hash) return true;
  return sessionStorage.getItem(AUTH_KEY) === cfg.password_hash;
}

async function requireLogin(cfg) {
  if (isAuthenticated(cfg)) return;

  const overlay = document.getElementById('loginOverlay');
  const input   = document.getElementById('loginInput');
  const btn     = document.getElementById('loginBtn');
  const errEl   = document.getElementById('loginError');
  const eye     = document.getElementById('loginEye');

  overlay.style.display = 'flex';

  eye.addEventListener('click', () => {
    input.type = input.type === 'password' ? 'text' : 'password';
  });

  await new Promise(resolve => {
    async function attempt() {
      const hash = await sha256(input.value.trim());
      if (hash === cfg.password_hash) {
        sessionStorage.setItem(AUTH_KEY, hash);
        overlay.style.display = 'none';
        resolve();
      } else {
        errEl.textContent = 'Senha incorreta. Tente novamente.';
        input.value = '';
        input.focus();
      }
    }

    btn.addEventListener('click', attempt);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') attempt(); });
  });
}

// ─────────────────────────────────────────────
// SNAPSHOTS  — carrega índice e histórico
// ─────────────────────────────────────────────

let _snapshots = [];

async function loadSnapshotIndex() {
  try {
    _snapshots = await fetchJSON('snapshots/index.json');
  } catch { _snapshots = []; }
  return _snapshots;
}

async function loadSnapshot(date) {
  return fetchJSON(`snapshots/${date}.json`);
}

function populateCompareSelect(snapshots) {
  const sel = document.getElementById('compareSelect');
  const sidebar = document.getElementById('sidebarHistory');
  const list    = document.getElementById('snapshotList');

  if (!snapshots.length) return;

  // Dropdown da topbar
  sel.innerHTML = '<option value="">Comparar com...</option>';
  snapshots.forEach(s => {
    const opt = document.createElement('option');
    opt.value       = s.date;
    opt.textContent = s.label;
    sel.appendChild(opt);
  });
  sel.style.display = 'block';

  // Sidebar history
  sidebar.style.display = 'block';
  list.innerHTML = snapshots.slice(0, 8).map(s => `
    <button class="snapshot-btn" data-date="${s.date}">${s.label}</button>
  `).join('');

  list.querySelectorAll('.snapshot-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      sel.value = btn.dataset.date;
      sel.dispatchEvent(new Event('change'));
      list.querySelectorAll('.snapshot-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
  });
}

// ─────────────────────────────────────────────
// COMPARISON  — delta nos KPIs
// ─────────────────────────────────────────────

function calcDelta(current, previous) {
  if (!previous || previous === 0) return null;
  return ((current - previous) / Math.abs(previous)) * 100;
}

function renderDelta(elId, current, previous) {
  const el = document.getElementById(elId);
  if (!el || previous === undefined) return;
  const delta = calcDelta(current, previous);
  if (delta === null) { el.textContent = ''; return; }
  const diff = current - previous;
  const sign = diff >= 0 ? '+' : '';
  el.textContent = `${sign}${diff.toLocaleString('pt-BR')}  (${fmt.pct(delta)})`;
  el.className   = `kpi-delta ${delta > 0 ? 'positive' : delta < 0 ? 'negative' : 'neutral'}`;
}

function showCompareBanner(label) {
  const banner = document.getElementById('compareBanner');
  const text   = document.getElementById('compareBannerText');
  if (banner) { banner.style.display = 'flex'; text.textContent = `Comparando com ${label}`; }
}

function hideCompareBanner() {
  const banner = document.getElementById('compareBanner');
  if (banner) banner.style.display = 'none';
}

// ─────────────────────────────────────────────
// HEALTH SCORE CARD
// ─────────────────────────────────────────────

const GAUGE_R   = 56;                              // raio do círculo SVG
const GAUGE_C   = 2 * Math.PI * GAUGE_R;           // circunferência ≈ 351.9
const GRAD_IDS  = { Crítico:'gaugeGradCritical', Regular:'gaugeGradRegular', Bom:'gaugeGradGood', Excelente:'gaugeGradExcellent' };

function renderHealthScore(data, prevData) {
  const hs   = data.health_score;
  const prev = prevData?.health_score;
  if (!hs) return;

  // ── Gauge SVG animation
  const arc    = document.getElementById('gaugeArc');
  const numEl  = document.getElementById('gaugeNum');
  const shadow = document.getElementById('shadowFilter');
  const badge  = document.getElementById('healthLevelBadge');

  const offset = GAUGE_C * (1 - hs.total / 100);
  const gradId = GRAD_IDS[hs.level] || 'gaugeGradCritical';

  if (arc) {
    arc.setAttribute('stroke', `url(#${gradId})`);
    arc.style.transition = 'stroke-dashoffset 1.2s cubic-bezier(0.34,1.56,0.64,1)';
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        arc.setAttribute('stroke-dashoffset', String(offset.toFixed(2)));
      });
    });
  }
  if (shadow) shadow.setAttribute('flood-color', hs.color);
  if (numEl)  numEl.textContent = hs.total;

  if (badge) {
    badge.textContent  = hs.level;
    badge.style.background = hs.color + '22';
    badge.style.color      = hs.color;
    badge.style.borderColor= hs.color + '44';
  }

  // ── Tendência vs snapshot anterior
  const trendWrap = document.getElementById('healthTrendWrap');
  const trendVal  = document.getElementById('healthTrendValue');
  if (trendVal && prev) {
    const delta = hs.total - prev.total;
    const sign  = delta >= 0 ? '+' : '';
    trendVal.textContent = `${sign}${delta} pts`;
    trendVal.className   = `health-trend-value ${delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat'}`;
    trendWrap?.style.setProperty('display', 'flex');
  } else if (trendWrap) {
    trendWrap.style.display = 'none';
  }

  // ── Barras de critério
  const bars = document.getElementById('healthBars');
  if (bars) {
    bars.innerHTML = Object.entries(hs.breakdown).map(([key, b]) => {
      const pct  = (b.score / b.max) * 100;
      const cls  = pct >= 80 ? 'great' : pct >= 50 ? 'ok' : pct >= 25 ? 'warn' : 'bad';
      const diff = prev ? (b.score - (prev.breakdown?.[key]?.score ?? b.score)) : null;
      const diffStr = diff !== null && diff !== 0
        ? `<span class="hb-diff ${diff>0?'up':'down'}">${diff>0?'+':''}${diff}</span>`
        : '';
      return `
        <div class="health-bar-row">
          <div class="hb-label">${b.label}</div>
          <div class="hb-track">
            <div class="hb-fill hb-fill--${cls}" style="width:${pct}%"></div>
          </div>
          <div class="hb-score">${b.score}<span class="hb-max">/${b.max}</span>${diffStr}</div>
        </div>`;
    }).join('');
  }

  // ── Por categoria
  const catsEl = document.getElementById('healthCats');
  if (catsEl && hs.category_scores) {
    const sorted = Object.entries(hs.category_scores)
      .sort((a, b) => b[1].score - a[1].score);
    catsEl.innerHTML = sorted.map(([cat, d]) => {
      const cls = d.score >= 60 ? 'great' : d.score >= 40 ? 'ok' : d.score >= 20 ? 'warn' : 'bad';
      return `
        <div class="health-cat-row">
          <div class="hb-label hb-label--cat">${cat}</div>
          <div class="hb-track hb-track--sm">
            <div class="hb-fill hb-fill--${cls}" style="width:${d.score}%"></div>
          </div>
          <div class="hb-score hb-score--sm">${d.score}</div>
        </div>`;
    }).join('');
  }

  // ── Ações prioritárias
  const actionsEl = document.getElementById('healthActions');
  if (actionsEl && hs.actions?.length) {
    const impactColor = { alto:'#ef4444', médio:'#ffe600', baixo:'#4f8ef7' };
    actionsEl.innerHTML = hs.actions.map((a, i) => `
      <li class="health-action-item">
        <div class="ha-num">${i + 1}</div>
        <div class="ha-body">
          <span class="ha-label">${escapeHtml(a.label)}</span>
          <span class="ha-text">${escapeHtml(a.body)}</span>
        </div>
        <span class="ha-impact" style="color:${impactColor[a.impact]||'#8888aa'};border-color:${impactColor[a.impact]||'#8888aa'}44;background:${impactColor[a.impact]||'#8888aa'}11">${a.impact}</span>
      </li>`).join('');
  }

  // ── Cor dinâmica do card (borda e glow)
  const card = document.getElementById('healthCard');
  if (card) {
    card.style.setProperty('--hs-color', hs.color);
    card.setAttribute('data-level', hs.level.toLowerCase());
  }
}

// ─────────────────────────────────────────────
// CHARTS
// ─────────────────────────────────────────────

Chart.defaults.color = '#8888aa';
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size = 11;

const BASE_OPTS = {
  responsive: true, maintainAspectRatio: false,
  animation: { duration: 500, easing: 'easeOutQuart' },
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor:'#1a1a30', borderColor:'rgba(255,255,255,0.08)', borderWidth:1,
      padding:10, titleColor:'#f0f0ff', bodyColor:'#8888aa', cornerRadius:8,
    },
  },
  scales: {
    x: { grid:{color:'rgba(255,255,255,0.04)',drawTicks:false}, border:{display:false}, ticks:{maxRotation:0,maxTicksLimit:7,color:'#44445a'} },
    y: { grid:{color:'rgba(255,255,255,0.04)',drawTicks:false}, border:{display:false}, ticks:{color:'#44445a',stepSize:1}, beginAtZero:true },
  },
};

let _charts = {};

function destroyCharts() {
  Object.values(_charts).forEach(c => c.destroy());
  _charts = {};
}

function _gradient(ctx, color, alpha1, alpha2) {
  const g = ctx.createLinearGradient(0, 0, 0, 220);
  g.addColorStop(0, color.replace(')', `,${alpha1})`).replace('rgb', 'rgba'));
  g.addColorStop(1, color.replace(')', `,${alpha2})`).replace('rgb', 'rgba'));
  return g;
}

function initVisitsChart(series) {
  const ctx = document.getElementById('visitsChart').getContext('2d');
  const g = ctx.createLinearGradient(0,0,0,220);
  g.addColorStop(0,'rgba(79,142,247,0.25)'); g.addColorStop(1,'rgba(79,142,247,0)');
  _charts.visits = new Chart(ctx, {
    type:'line',
    data:{ labels:last30Days(), datasets:[{ data:series, borderColor:'#4f8ef7', backgroundColor:g, borderWidth:2, pointRadius:0, pointHoverRadius:5, tension:0.4, fill:true }] },
    options:{ ...BASE_OPTS, plugins:{ ...BASE_OPTS.plugins, tooltip:{ ...BASE_OPTS.plugins.tooltip, callbacks:{ label:c=>` ${c.parsed.y} visita${c.parsed.y!==1?'s':''}` } } } },
  });
}

function initSalesChart(series) {
  const ctx = document.getElementById('salesChart').getContext('2d');
  const g = ctx.createLinearGradient(0,0,0,220);
  g.addColorStop(0,'rgba(34,211,160,0.2)'); g.addColorStop(1,'rgba(34,211,160,0)');
  _charts.sales = new Chart(ctx, {
    type:'bar',
    data:{ labels:last30Days(), datasets:[{ data:series, backgroundColor:g, borderColor:'#22d3a0', borderWidth:1.5, borderRadius:4, borderSkipped:false }] },
    options:{ ...BASE_OPTS, plugins:{ ...BASE_OPTS.plugins, tooltip:{ ...BASE_OPTS.plugins.tooltip, callbacks:{ label:c=>` ${c.parsed.y} venda${c.parsed.y!==1?'s':''}` } } } },
  });
}

function initRankingChart(products) {
  const sorted = [...products].sort((a,b)=>(b.visits||0)-(a.visits||0)).slice(0,5);
  const ctx = document.getElementById('rankingChart').getContext('2d');
  _charts.ranking = new Chart(ctx, {
    type:'bar',
    data:{
      labels: sorted.map(p=>p.title.replace(/\s*Ziyou\s*/i,'').split(' ').slice(0,4).join(' ')),
      datasets:[{ data:sorted.map(p=>p.visits||0), backgroundColor:['rgba(79,142,247,0.8)','rgba(79,142,247,0.6)','rgba(79,142,247,0.42)','rgba(79,142,247,0.28)','rgba(79,142,247,0.16)'], borderColor:'transparent', borderRadius:6, borderSkipped:false }],
    },
    options:{ ...BASE_OPTS, indexAxis:'y', plugins:{ ...BASE_OPTS.plugins, tooltip:{ ...BASE_OPTS.plugins.tooltip, callbacks:{ label:c=>` ${c.parsed.x} visita${c.parsed.x!==1?'s':''}` } } }, scales:{ x:{ ...BASE_OPTS.scales.x, ticks:{color:'#44445a',stepSize:1} }, y:{ grid:{display:false}, border:{display:false}, ticks:{color:'#8888aa',font:{size:11}} } } },
  });
}

function initCategoryChart(cats) {
  const entries = Object.entries(cats).filter(([,v])=>v>0);
  const allZero = !entries.length;
  const labels  = allZero ? Object.keys(cats)   : entries.map(([k])=>k);
  const values  = allZero ? Object.values(cats).map(()=>1) : entries.map(([,v])=>v);
  const ctx = document.getElementById('categoryChart').getContext('2d');
  _charts.category = new Chart(ctx, {
    type:'doughnut',
    data:{ labels, datasets:[{ data:values, backgroundColor:['#4f8ef7','#22d3a0','#a855f7','#f97316','#ffe600'], borderColor:'#13132a', borderWidth:3, hoverOffset:6 }] },
    options:{ responsive:true, maintainAspectRatio:false, cutout:'68%', animation:{duration:500}, plugins:{ legend:{ display:true, position:'bottom', labels:{boxWidth:10,boxHeight:10,borderRadius:99,padding:12,color:'#8888aa',font:{size:11}} }, tooltip:{ backgroundColor:'#1a1a30', borderColor:'rgba(255,255,255,0.08)', borderWidth:1, padding:10, titleColor:'#f0f0ff', bodyColor:'#8888aa', cornerRadius:8, callbacks:{ label:c=>allZero?` ${c.label} (sem visitas)`:` ${c.parsed} visita${c.parsed!==1?'s':''}` } } } },
  });
}

// ─────────────────────────────────────────────
// KPIs
// ─────────────────────────────────────────────

function renderKPIs(data, prev) {
  const k     = data.kpis;
  const prods = data.products || [];
  const stock = prods.reduce((s,p)=>s+(p.stock||0),0);
  const pk    = prev?.kpis;

  const set = (valId, deltaId, value, prevValue, label, cls) => {
    document.getElementById(valId).textContent  = value;
    const el = document.getElementById(deltaId);
    if (pk !== undefined && prevValue !== undefined) {
      renderDelta(deltaId, typeof value === 'string' ? 0 : 0, prevValue);
    } else {
      el.textContent = label;
      el.className   = `kpi-delta ${cls || 'neutral'}`;
    }
  };

  document.getElementById('kpi-listings').textContent = fmt.number(k.active_listings);
  document.getElementById('kpi-listings-delta').textContent = `Gold Special · ${k.active_listings} ativos`;
  if (pk) renderDelta('kpi-listings-delta', k.active_listings, pk.active_listings);

  document.getElementById('kpi-visits').textContent = fmt.number(k.total_visits);
  if (pk) {
    renderDelta('kpi-visits-delta', k.total_visits, pk.total_visits);
  } else {
    const vpl = k.active_listings ? (k.total_visits / k.active_listings).toFixed(1) : '0';
    document.getElementById('kpi-visits-delta').textContent = `~${vpl} visita(s) / anúncio`;
    document.getElementById('kpi-visits-delta').className = 'kpi-delta neutral';
  }

  document.getElementById('kpi-sales').textContent = fmt.number(k.total_sales);
  if (pk) {
    renderDelta('kpi-sales-delta', k.total_sales, pk.total_sales);
  } else {
    document.getElementById('kpi-sales-delta').textContent = k.total_sales > 0 ? `↑ ${k.total_sales} no período` : 'Nenhuma venda ainda';
    document.getElementById('kpi-sales-delta').className = k.total_sales > 0 ? 'kpi-delta positive' : 'kpi-delta neutral';
  }

  document.getElementById('kpi-revenue').textContent = fmt.currency(k.revenue);
  if (pk) {
    renderDelta('kpi-revenue-delta', k.revenue, pk.revenue);
  } else {
    document.getElementById('kpi-revenue-delta').textContent = k.revenue > 0 ? `Líquido: ${fmt.currency(data.financial?.net_revenue||0)}` : 'Receita acumulada';
    document.getElementById('kpi-revenue-delta').className = k.revenue > 0 ? 'kpi-delta positive' : 'kpi-delta neutral';
  }

  document.getElementById('kpi-ticket').textContent = k.avg_ticket > 0 ? fmt.currency(k.avg_ticket) : '—';
  if (pk) {
    renderDelta('kpi-ticket-delta', k.avg_ticket, pk.avg_ticket);
  } else {
    document.getElementById('kpi-ticket-delta').textContent = k.total_sales > 0 ? 'Ticket médio real' : 'Sem vendas no período';
    document.getElementById('kpi-ticket-delta').className = 'kpi-delta neutral';
  }

  document.getElementById('kpi-stock').textContent = fmt.number(stock);
  if (pk) {
    renderDelta('kpi-stock-delta', stock, (prev.products||[]).reduce((s,p)=>s+(p.stock||0),0));
  } else {
    document.getElementById('kpi-stock-delta').textContent = `${prods.length} SKUs ativos`;
    document.getElementById('kpi-stock-delta').className = 'kpi-delta positive';
  }
}

// ─────────────────────────────────────────────
// ACCOUNT
// ─────────────────────────────────────────────

function renderAccount(acc) {
  const nick = acc.nickname || '—';
  const uid  = acc.user_id  || '';
  document.getElementById('sidebarNickname').textContent = nick;
  document.getElementById('sidebarUserId').textContent   = uid ? `#${uid}` : '';
  document.getElementById('sidebarAvatar').textContent   = nick.charAt(0).toUpperCase();
}

// ─────────────────────────────────────────────
// TABLE
// ─────────────────────────────────────────────

let _allProducts = [];

function renderTable(products) {
  document.getElementById('productsCount').textContent =
    `${products.length} anúncio${products.length !== 1 ? 's' : ''}`;

  const slabel = s => ({ active:'Ativo', paused:'Pausado', closed:'Encerrado', under_review:'Em revisão' }[s] || s);
  const tbody = document.getElementById('productsBody');

  if (!products.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="table-empty">Nenhum anúncio encontrado</td></tr>`;
    return;
  }

  tbody.innerHTML = products.map(p => `
    <tr>
      <td><div class="product-cell">
        <a class="product-title" href="${escapeHtml(p.permalink)}" target="_blank" rel="noopener" style="color:inherit;text-decoration:none">${escapeHtml(p.title)}</a>
        <span class="product-id">${escapeHtml(p.id)}</span>
      </div></td>
      <td class="text-right">${fmt.currency(p.price)}</td>
      <td class="text-right">${fmt.number(p.stock)}</td>
      <td class="text-right">${fmt.number(p.sold)}</td>
      <td class="text-right">${fmt.number(p.visits)}</td>
      <td class="text-center"><span class="badge-status ${escapeHtml(p.status)}">${slabel(p.status)}</span></td>
    </tr>
  `).join('');
}

function setupSearch() {
  document.getElementById('productSearch').addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    renderTable(q ? _allProducts.filter(p =>
      (p.title||'').toLowerCase().includes(q) || (p.id||'').toLowerCase().includes(q)
    ) : _allProducts);
  });
}

// ─────────────────────────────────────────────
// INSIGHTS  — consome insights pré-computados ou gera no client
// ─────────────────────────────────────────────

function renderInsights(data, cfg) {
  // Prefere insights pré-computados pelo fetch_data.py (mais ricos)
  const serverInsights = data.insights || [];
  const grid = document.getElementById('insightsGrid');
  grid.innerHTML = '';

  if (serverInsights.length) {
    _renderServerInsights(serverInsights, grid, cfg);
  } else {
    _renderClientInsights(data, grid, cfg);
  }
}

function _renderServerInsights(list, grid, cfg) {
  list.forEach(ins => {
    const card = document.createElement('div');

    if (ins.type === 'ranking') {
      card.className = 'insight-card insight-card--opportunity insight-card--wide';
      card.innerHTML = `
        <div class="insight-header">
          <div class="insight-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg></div>
          <span class="insight-type">Ranking</span>
        </div>
        <p class="insight-title">${escapeHtml(ins.title)}</p>
        <div class="insight-table">
          ${(ins.items||[]).map(i=>`
            <div class="insight-row">
              <span class="insight-rank">#${i.rank}</span>
              <a href="${escapeHtml(i.permalink)}" target="_blank" rel="noopener" class="insight-item-title">${escapeHtml(i.title)}</a>
              <span class="insight-chip blue">${fmt.number(i.visits)} visitas</span>
              <span class="insight-chip gray">${i.share}% do tráfego</span>
            </div>
          `).join('')}
        </div>`;
    } else if (ins.type === 'no_visits') {
      card.className = 'insight-card insight-card--alert';
      card.innerHTML = `
        <div class="insight-header">
          <div class="insight-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg></div>
          <span class="insight-type">Alerta</span>
        </div>
        <p class="insight-title">${ins.count} produto${ins.count!==1?'s':''} sem nenhuma visita</p>
        <div class="insight-table">
          ${(ins.items||[]).map(i=>`
            <div class="insight-row">
              <a href="${escapeHtml(i.permalink)}" target="_blank" rel="noopener" class="insight-item-title">${escapeHtml(i.title)}</a>
              <span class="insight-chip gray">${fmt.number(i.stock)} un. estoque</span>
            </div>
          `).join('')}
        </div>`;
    } else if (ins.type === 'high_stock_low_demand') {
      card.className = 'insight-card insight-card--warning insight-card--wide';
      card.innerHTML = `
        <div class="insight-header">
          <div class="insight-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/></svg></div>
          <span class="insight-type">Atenção</span>
        </div>
        <p class="insight-title">${escapeHtml(ins.title)}</p>
        <div class="insight-table">
          ${(ins.items||[]).map(i=>`
            <div class="insight-row">
              <a href="${escapeHtml(i.permalink)}" target="_blank" rel="noopener" class="insight-item-title">${escapeHtml(i.title)}</a>
              <span class="insight-chip orange">${fmt.number(i.stock)} un.</span>
              <span class="insight-chip gray">${fmt.number(i.visits)} visitas</span>
              <span class="insight-chip gray">${fmt.currency(i.price)}</span>
            </div>
          `).join('')}
        </div>`;
    } else {
      // Generic insight card
      const typeMap = { zero_sales:'alert', mercadoenvios_off:'warning', traffic_concentration:'warning' };
      const typeClass = typeMap[ins.type] || 'tip';
      const typeLabel = { alert:'Alerta', warning:'Atenção', tip:'Dica', opportunity:'Oportunidade', zero_sales:'Alerta', mercadoenvios_off:'Atenção', traffic_concentration:'Atenção' }[ins.type] || 'Info';
      card.className = `insight-card insight-card--${typeClass}`;
      card.innerHTML = `
        <div class="insight-header">
          <div class="insight-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></div>
          <span class="insight-type">${typeLabel}</span>
        </div>
        <p class="insight-title">${escapeHtml(ins.title)}</p>
        ${ins.suggestion ? `<p class="insight-body">${escapeHtml(ins.suggestion)}</p>` : ''}
        ${ins.total_visits !== undefined ? `<p class="insight-body">${fmt.number(ins.total_visits)} visitas · ${ins.total_listings} anúncios · ${escapeHtml(ins.suggestion||'')}</p>` : ''}
      `;
    }

    grid.appendChild(card);
  });
}

function _renderClientInsights(data, grid, cfg) {
  // Fallback: insights gerados no cliente (quando insights[] não está no JSON)
  const { kpis = {}, products = [], account = {} } = data;
  const tv  = kpis.total_visits || 0;
  const ts  = kpis.total_sales  || 0;
  const al  = kpis.active_listings || 0;
  const sorted  = [...products].sort((a,b)=>(b.visits||0)-(a.visits||0));
  const noVisit = products.filter(p=>!(p.visits||0));

  const make = (type, title, body) => {
    const card = document.createElement('div');
    const tl = { opportunity:'Oportunidade', alert:'Alerta', tip:'Dica', warning:'Atenção' };
    card.className = `insight-card insight-card--${type}`;
    card.innerHTML = `<div class="insight-header"><div class="insight-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></div><span class="insight-type">${tl[type]||type}</span></div><p class="insight-title">${title}</p><p class="insight-body">${body}</p>`;
    grid.appendChild(card);
  };

  if (sorted[0]?.visits > 0) make('opportunity', `Produto mais visitado: ${(sorted[0].title||'').replace(/\s*Ziyou\s*/i,'')}`, `${sorted[0].visits} visitas (${Math.round((sorted[0].visits/Math.max(1,tv))*100)}% do tráfego total). Foque aqui para converter.`);
  if (noVisit.length) make('alert', `${noVisit.length} produto${noVisit.length>1?'s':''} sem visitas`, 'Revise título, fotos e preço desses anúncios para aumentar o ranqueamento orgânico.');
  if (ts === 0 && tv > 0) make('alert', 'Sem conversão no período', `${tv} visitas e nenhuma venda. Verifique precificação e qualidade das fotos dos produtos mais visitados.`);
  if (!account.mercadoenvios) make('warning', 'Mercado Envios não habilitado', 'Habilitar frete ML aumenta visibilidade no filtro "Frete grátis" e no selo Full.');
  make('tip', 'Fotos de lifestyle aumentam conversão em até 3×', 'Produtos fitness fotografados em uso real convertem muito mais do que fundo branco.');
}

// ─────────────────────────────────────────────
// PDF BUTTON
// ─────────────────────────────────────────────

function setupPdfButton(cfg) {
  const btn = document.getElementById('btnPdf');
  if (!btn) return;

  // Tenta listar relatórios disponíveis
  fetch('reports/index.json?_=' + Date.now())
    .then(r => r.ok ? r.json() : [])
    .then(reports => {
      if (!reports.length) return;
      const latest = reports[0];
      btn.href  = latest.url;
      btn.title = `PDF executivo — ${latest.label}`;
      btn.style.display = 'flex';
    })
    .catch(() => {});
}

// ─────────────────────────────────────────────
// SIDEBAR NAV
// ─────────────────────────────────────────────

function setupNav() {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
      if (window.innerWidth < 768) closeSidebar();
    });
  });
}

function setupMobileMenu() {
  document.getElementById('menuToggle').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('open');
    document.getElementById('sidebarOverlay').classList.toggle('visible');
  });
  document.getElementById('sidebarOverlay').addEventListener('click', closeSidebar);
}

function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('visible');
}

// ─────────────────────────────────────────────
// DATE LABEL
// ─────────────────────────────────────────────

function setDateLabel(meta) {
  if (!meta) return;
  try {
    const from = new Date(meta.period_from + 'T12:00:00');
    const to   = new Date(meta.period_to   + 'T12:00:00');
    document.getElementById('dateRangeLabel').textContent =
      `${from.toLocaleDateString('pt-BR',{day:'2-digit',month:'short'})} – ${to.toLocaleDateString('pt-BR',{day:'2-digit',month:'short'})}`;
  } catch { /* noop */ }
}

// ─────────────────────────────────────────────
// REFRESH
// ─────────────────────────────────────────────

function setupRefresh() {
  const btn = document.getElementById('btnRefresh');
  btn.addEventListener('click', async () => {
    btn.classList.add('spinning');
    try {
      const data = await fetchJSON('data.json');
      renderAll(data);
    } catch(e) { console.error(e); }
    finally { btn.classList.remove('spinning'); }
  });
}

// ─────────────────────────────────────────────
// RENDER ALL
// ─────────────────────────────────────────────

function renderAll(data, prev, cfg) {
  destroyCharts();
  renderHealthScore(data, prev);
  renderAccount(data.account || {});
  renderKPIs(data, prev);
  initVisitsChart(data.visits_series || new Array(30).fill(0));
  initSalesChart(data.sales_series   || new Array(30).fill(0));
  _allProducts = data.products || [];
  renderTable(_allProducts);
  initRankingChart(_allProducts);
  initCategoryChart(data.categories || {});
  renderInsights(data, cfg || {});
  setDateLabel(data.meta);
  const ts = data.meta?.fetched_at ? fmt.datetime(data.meta.fetched_at) : 'agora';
  document.getElementById('lastUpdated').textContent = `Snapshot: ${ts}`;
}

// ─────────────────────────────────────────────
// PRINT MODE  (?print=1 — para PDF via Playwright)
// ─────────────────────────────────────────────

const IS_PRINT = new URLSearchParams(location.search).has('print');
if (IS_PRINT) document.body.classList.add('print-mode');

// ─────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  showLoading(true);
  setLoadingText('Carregando configurações...');

  try {
    // 1 — Config
    const cfg = await loadConfig();
    applyBranding(cfg);

    // 2 — Login (se ativado e não é modo print)
    if (!IS_PRINT) {
      showLoading(false);
      await requireLogin(cfg);
      showLoading(true);
    }

    // 3 — Dados principais
    setLoadingText('Buscando dados do Mercado Livre...');
    const data = await fetchJSON('data.json');

    // 4 — Snapshots
    setLoadingText('Carregando histórico...');
    const snapshots = await loadSnapshotIndex();

    // 5 — Render inicial
    renderAll(data, null, cfg);
    showLoading(false);

    // 6 — UI setup
    populateCompareSelect(snapshots);
    setupNav();
    setupMobileMenu();
    setupRefresh();
    setupSearch();
    setupPdfButton(cfg);

    // 7 — Comparação de período
    const sel = document.getElementById('compareSelect');
    const clearBtn = document.getElementById('compareClear');

    sel.addEventListener('change', async () => {
      const date = sel.value;
      if (!date) {
        renderAll(data, null, cfg);
        hideCompareBanner();
        return;
      }
      try {
        const prev = await loadSnapshot(date);
        renderAll(data, prev, cfg);
        const label = snapshots.find(s=>s.date===date)?.label || date;
        showCompareBanner(label);
      } catch(e) {
        console.error('Erro ao carregar snapshot:', e);
      }
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        sel.value = '';
        renderAll(data, null, cfg);
        hideCompareBanner();
        document.querySelectorAll('.snapshot-btn').forEach(b=>b.classList.remove('active'));
      });
    }

  } catch(err) {
    console.error('[Analytics]', err);
    showError(`Não foi possível carregar o dashboard: ${err.message}`);
  }
});
