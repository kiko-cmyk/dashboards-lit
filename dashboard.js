(() => {
  const LIT = {
    indigo: "#323743",
    indigoSoft: "rgba(50, 55, 67, 0.18)",
    yellow: "#ebee62",
    yellowSoft: "rgba(235, 238, 98, 0.35)",
    beige: "#cfbfad",
    beigeSoft: "rgba(207, 191, 173, 0.45)",
    white: "#f8f9f2",
    muted: "#7a7367",
    border: "#e5dfd2",
  };

  if (typeof Chart !== "undefined") {
    Chart.defaults.font.family = '"Barlow", -apple-system, BlinkMacSystemFont, sans-serif';
    Chart.defaults.font.size = 12;
    Chart.defaults.color = LIT.indigo;
    Chart.defaults.borderColor = LIT.border;
  }

  const state = {
    manifest: null,
    current: null,
    previous: null,
    history: [],
    charts: {},
    period: { meta: "all", google: "all" },
    weeks: [],
  };

  function buildWeeks(month) {
    if (!month) return [{ id: "all", label: "Mes" }];
    const [y, m] = month.split("-").map(Number);
    const lastDay = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const weeks = [{ id: "all", label: "Mes" }];
    const step = 7;
    let i = 1;
    let start = 1;
    while (start <= lastDay) {
      const end = Math.min(start + step - 1, lastDay);
      const pad = (n) => String(n).padStart(2, "0");
      weeks.push({
        id: `w${i}`,
        label: `W${i} · ${pad(start)}–${pad(end)}`,
        start: `${month}-${pad(start)}`,
        end: `${month}-${pad(end)}`,
      });
      start += step;
      i += 1;
    }
    return weeks;
  }

  function filterDaily(daily, week) {
    if (!week || week.id === "all") return daily || [];
    return (daily || []).filter((d) => d.date >= week.start && d.date <= week.end);
  }

  function recomputeMetaTotals(daily) {
    const t = { spend: 0, impressions: 0, clicks: 0, reach: 0, purchases: 0, revenue: 0 };
    for (const d of daily) {
      t.spend += d.spend || 0;
      t.impressions += d.impressions || 0;
      t.clicks += d.clicks || 0;
      t.reach += d.reach || 0;
      t.purchases += d.purchases || 0;
      t.revenue += d.revenue || 0;
    }
    return {
      spend: +t.spend.toFixed(2),
      impressions: t.impressions,
      clicks: t.clicks,
      reach: t.reach,
      purchases: +t.purchases.toFixed(2),
      revenue: +t.revenue.toFixed(2),
      ctr: t.impressions ? +((t.clicks / t.impressions) * 100).toFixed(2) : 0,
      cpc: t.clicks ? +(t.spend / t.clicks).toFixed(2) : 0,
      cpm: t.impressions ? +((t.spend / t.impressions) * 1000).toFixed(2) : 0,
      cpa: t.purchases ? +(t.spend / t.purchases).toFixed(2) : 0,
      roas: t.spend ? +(t.revenue / t.spend).toFixed(2) : 0,
    };
  }

  function recomputeGoogleTotals(daily) {
    const t = { cost: 0, impressions: 0, clicks: 0, conversions: 0, revenue: 0 };
    for (const d of daily) {
      t.cost += d.cost || 0;
      t.impressions += d.impressions || 0;
      t.clicks += d.clicks || 0;
      t.conversions += d.conversions || 0;
      t.revenue += d.revenue || 0;
    }
    return {
      cost: +t.cost.toFixed(2),
      impressions: t.impressions,
      clicks: t.clicks,
      conversions: +t.conversions.toFixed(2),
      revenue: +t.revenue.toFixed(2),
      ctr: t.impressions ? +((t.clicks / t.impressions) * 100).toFixed(2) : 0,
      cpc: t.clicks ? +(t.cost / t.clicks).toFixed(2) : 0,
      cpm: t.impressions ? +((t.cost / t.impressions) * 1000).toFixed(2) : 0,
      cpa: t.conversions ? +(t.cost / t.conversions).toFixed(2) : 0,
      conv_rate: t.clicks ? +((t.conversions / t.clicks) * 100).toFixed(2) : 0,
      roas: t.cost ? +(t.revenue / t.cost).toFixed(2) : 0,
    };
  }

  function renderPeriodBar(scope) {
    const bar = document.getElementById(`${scope}-period-bar`);
    if (!bar) return;
    bar.querySelectorAll(".period-btn").forEach((b) => b.remove());
    const currentId = state.period[scope];
    for (const w of state.weeks) {
      const btn = document.createElement("button");
      btn.className = "period-btn" + (w.id === currentId ? " active" : "");
      btn.textContent = w.label;
      btn.dataset.range = w.id;
      btn.addEventListener("click", () => {
        state.period[scope] = w.id;
        if (scope === "meta") renderMeta(); else renderGoogle();
      });
      bar.appendChild(btn);
    }
  }

  function activeWeek(scope) {
    const id = state.period[scope];
    return state.weeks.find((w) => w.id === id) || state.weeks[0];
  }

  function prevWeek(scope) {
    const id = state.period[scope];
    if (!id || id === "all") return null;
    const idx = state.weeks.findIndex((w) => w.id === id);
    if (idx <= 1) return null;
    return state.weeks[idx - 1];
  }

  const fmt = {
    int: (v) => Number(v ?? 0).toLocaleString("es-ES"),
    money: (v) => Number(v ?? 0).toLocaleString("es-ES", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }),
    money2: (v) => Number(v ?? 0).toLocaleString("es-ES", { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    pct: (v) => `${Number(v ?? 0).toFixed(2)}%`,
    dec2: (v) => Number(v ?? 0).toFixed(2),
    text: (v) => (v == null ? "—" : String(v)),
  };

  function cpm(spend, impressions) {
    return impressions ? (spend / impressions) * 1000 : 0;
  }
  function convRate(conversions, clicks) {
    return clicks ? (conversions / clicks) * 100 : 0;
  }
  function shortName(name, max = 50) {
    if (!name) return "";
    return name.length > max ? name.slice(0, max - 1) + "…" : name;
  }
  function withDerived(row, { spendKey = "spend", convKey = "purchases" } = {}) {
    const r = { ...row };
    r._cpm = cpm(r[spendKey] ?? 0, r.impressions ?? 0);
    r._conv_rate = convRate(r[convKey] ?? 0, r.clicks ?? 0);
    return r;
  }

  async function loadManifest() {
    const r = await fetch(`data/manifest.json?t=${Date.now()}`);
    if (!r.ok) throw new Error("manifest not found");
    return r.json();
  }

  async function loadMonth(month) {
    const r = await fetch(`data/${month}.json?t=${Date.now()}`);
    if (!r.ok) return null;
    return r.json();
  }

  function prevMonth(month) {
    const [y, m] = month.split("-").map(Number);
    const d = new Date(Date.UTC(y, m - 2, 1));
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
  }

  function delta(curr, prev) {
    if (prev == null || prev === 0 || curr == null) return null;
    return ((curr - prev) / prev) * 100;
  }

  function kpi(label, value, fmtFn, deltaVal, invert = false) {
    const d = document.createElement("div");
    d.className = "kpi";
    let deltaHtml = "";
    if (deltaVal != null && isFinite(deltaVal)) {
      const good = invert ? deltaVal < 0 : deltaVal > 0;
      const bad = invert ? deltaVal > 0 : deltaVal < 0;
      const cls = good ? "good" : bad ? "bad" : "";
      const sign = deltaVal > 0 ? "+" : "";
      deltaHtml = `<span class="delta ${cls}">${sign}${deltaVal.toFixed(1)}%</span>`;
    }
    d.innerHTML = `<div class="kpi-label">${label}</div><div class="kpi-value">${fmtFn(value)}</div><div class="kpi-delta">${deltaHtml}</div>`;
    return d;
  }

  function renderKpis(containerId, specs, current, previous) {
    const el = document.getElementById(containerId);
    el.innerHTML = "";
    for (const [label, key, fmtFn, invert] of specs) {
      const cv = current?.[key];
      const pv = previous?.[key];
      el.appendChild(kpi(label, cv, fmtFn, delta(cv, pv), invert));
    }
  }

  function destroyChart(id) {
    if (state.charts[id]) {
      state.charts[id].destroy();
      delete state.charts[id];
    }
  }

  function renderCombo(canvasId, labels, barData, barLabel, lineData, lineLabel, opts = {}) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    state.charts[canvasId] = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            type: "bar",
            label: barLabel,
            data: barData,
            backgroundColor: LIT.indigo,
            borderRadius: 2,
            yAxisID: "y",
            order: 2,
          },
          {
            type: "line",
            label: lineLabel,
            data: lineData,
            borderColor: LIT.indigo,
            backgroundColor: LIT.yellow,
            pointBackgroundColor: LIT.yellow,
            pointBorderColor: LIT.indigo,
            pointBorderWidth: 2,
            pointRadius: 4,
            borderWidth: 2,
            yAxisID: "y1",
            tension: 0.25,
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { beginAtZero: true, position: "left", grid: { color: LIT.border } },
          y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false } },
          x: { grid: { color: LIT.border } },
        },
        plugins: {
          legend: {
            position: "bottom",
            labels: { usePointStyle: true, boxWidth: 8, padding: 16 },
          },
        },
        ...opts,
      },
    });
  }

  function renderLine(canvasId, labels, data, label, color = LIT.indigo) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    state.charts[canvasId] = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [{
          label,
          data,
          borderColor: color,
          backgroundColor: color,
          pointBackgroundColor: LIT.yellow,
          pointBorderColor: color,
          pointBorderWidth: 1.5,
          pointRadius: 3,
          borderWidth: 2,
          tension: 0.25,
          fill: false,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, grid: { color: LIT.border } },
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
        },
      },
    });
  }

  function renderBar(canvasId, labels, data, label, color = LIT.indigo) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    state.charts[canvasId] = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label,
          data,
          backgroundColor: color,
          borderRadius: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, grid: { color: LIT.border } },
          x: { grid: { display: false } },
        },
      },
    });
  }

  function renderTable(containerId, columns, rows, opts = {}) {
    const el = document.getElementById(containerId);
    el.innerHTML = "";
    if (!rows || rows.length === 0) {
      el.innerHTML = `<div class="empty">Sin datos</div>`;
      return;
    }
    const table = document.createElement("table");
    table.className = "data-table";
    const thead = document.createElement("thead");
    const trh = document.createElement("tr");
    columns.forEach((col, idx) => {
      const th = document.createElement("th");
      th.textContent = col.label;
      th.style.cursor = "pointer";
      th.addEventListener("click", () => {
        const current = table.dataset.sortIdx;
        const dir = current === String(idx) && table.dataset.sortDir === "desc" ? "asc" : "desc";
        table.dataset.sortIdx = idx;
        table.dataset.sortDir = dir;
        const sorted = [...rows].sort((a, b) => {
          const av = a[col.key];
          const bv = b[col.key];
          if (typeof av === "number" && typeof bv === "number") return dir === "desc" ? bv - av : av - bv;
          return dir === "desc" ? String(bv).localeCompare(String(av)) : String(av).localeCompare(String(bv));
        });
        drawBody(sorted);
      });
      trh.appendChild(th);
    });
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    table.appendChild(tbody);
    el.appendChild(table);

    function drawBody(list) {
      tbody.innerHTML = "";
      const limit = opts.limit ?? 200;
      for (const row of list.slice(0, limit)) {
        const tr = document.createElement("tr");
        for (const col of columns) {
          const td = document.createElement("td");
          const v = row[col.key];
          if (col.render) td.innerHTML = col.render(v, row);
          else td.textContent = col.format ? col.format(v) : fmt.text(v);
          if (col.truncate) {
            td.style.maxWidth = (col.truncate === true ? 260 : col.truncate) + "px";
            td.style.overflow = "hidden";
            td.style.textOverflow = "ellipsis";
            td.style.whiteSpace = "nowrap";
            if (v != null) td.title = String(v);
          }
          tr.appendChild(td);
        }
        tbody.appendChild(tr);
      }
    }
    drawBody(rows);
  }

  function aggregateHistory(history, section, keys, ratios = {}) {
    return history.map((h) => {
      const t = h[section]?.totals || {};
      const row = { month: h.month };
      for (const k of keys) row[k] = t[k] ?? 0;
      for (const [rk, [num, den, mult = 1]] of Object.entries(ratios)) {
        row[rk] = t[num] && t[den] ? (t[num] / t[den]) * mult : 0;
      }
      return row;
    });
  }

  // ── rendering per section ──────────────────────────────────────────────

  function renderMeta() {
    renderPeriodBar("meta");
    const m = state.current?.meta;
    const p = state.previous?.meta;
    const week = activeWeek("meta");
    const allDaily = m?.daily || [];
    const daily = filterDaily(allDaily, week);

    let currentTotals;
    let previousTotals;
    if (week.id === "all") {
      currentTotals = m?.totals;
      previousTotals = p?.totals;
    } else {
      currentTotals = recomputeMetaTotals(daily);
      const pw = prevWeek("meta");
      previousTotals = pw ? recomputeMetaTotals(filterDaily(allDaily, pw)) : null;
    }
    const enrich = (t) => {
      if (!t) return t;
      return { ...t, conv_rate: t.clicks ? (t.purchases / t.clicks) * 100 : 0 };
    };
    currentTotals = enrich(currentTotals);
    previousTotals = enrich(previousTotals);

    renderKpis("meta-kpis-perf", [
      ["Inversión", "spend", fmt.money, true],
      ["Ventas", "purchases", fmt.int, false],
      ["CPA", "cpa", fmt.money2, true],
      ["CR", "conv_rate", fmt.pct, false],
      ["ROAS", "roas", fmt.dec2, false],
    ], currentTotals, previousTotals);
    renderKpis("meta-kpis-traffic", [
      ["Impresiones", "impressions", fmt.int, false],
      ["Clics", "clicks", fmt.int, false],
      ["CTR", "ctr", fmt.pct, false],
      ["CPC", "cpc", fmt.money2, true],
      ["CPM", "cpm", fmt.money2, true],
    ], currentTotals, previousTotals);

    const dLabels = daily.map((d) => (d.date || "").slice(5));
    renderCombo(
      "meta-daily-chart",
      dLabels,
      daily.map((d) => d.purchases),
      "Ventas",
      daily.map((d) => d.cpa),
      "CPA (€)",
    );
    renderLine("meta-cpc-chart", dLabels, daily.map((d) => d.cpc), "CPC (€)", LIT.indigo);
    renderLine("meta-ctr-chart", dLabels, daily.map((d) => d.ctr), "CTR (%)", LIT.indigo);
    renderCombo(
      "meta-spend-revenue-chart",
      dLabels,
      daily.map((d) => d.spend),
      "Inversión (€)",
      daily.map((d) => d.revenue),
      "Revenue (€)",
    );

    const META_METRIC_COLS = [
      { key: "spend", label: "Inversión", format: fmt.money },
      { key: "impressions", label: "Impresiones", format: fmt.int },
      { key: "clicks", label: "Clics", format: fmt.int },
      { key: "ctr", label: "CTR", format: fmt.pct },
      { key: "cpc", label: "CPC", format: fmt.money2 },
      { key: "_cpm", label: "CPM", format: fmt.money2 },
      { key: "purchases", label: "Ventas", format: fmt.int },
      { key: "cpa", label: "CPA", format: fmt.money2 },
      { key: "_conv_rate", label: "CR", format: fmt.pct },
      { key: "roas", label: "ROAS", format: fmt.dec2 },
    ];

    const metaCampaignsRows = (m?.campaigns || []).map((r) => withDerived(r, { convKey: "purchases" }));
    renderTable("meta-campaigns",
      [{ key: "campaign", label: "Campaña", truncate: 280 }, ...META_METRIC_COLS],
      metaCampaignsRows);

    const metaAdsetsRows = (m?.adsets || []).map((r) => withDerived(r, { convKey: "purchases" }));
    renderTable("meta-adsets", [
      { key: "adset", label: "Ad Set", truncate: 240 },
      { key: "campaign", label: "Campaña", truncate: 200 },
      ...META_METRIC_COLS,
    ], metaAdsetsRows);

    const platformsAll = (m?.platforms || []).map((r) => withDerived(r, { convKey: "purchases" }));
    const mainPlatforms = new Set(["facebook", "instagram"]);
    const platformsMain = platformsAll.filter((r) => mainPlatforms.has(r.platform));
    const platformsRest = platformsAll.filter((r) => !mainPlatforms.has(r.platform));
    const platformCols = [{ key: "platform", label: "Plataforma" }, ...META_METRIC_COLS];
    renderTable("meta-platforms", platformCols, platformsMain);
    renderTable("meta-platforms-rest", platformCols, platformsRest);
    const moreBtn = document.getElementById("meta-platforms-more");
    const restContainer = document.getElementById("meta-platforms-rest-wrap");
    if (moreBtn && restContainer) {
      if (platformsRest.length) {
        moreBtn.style.display = "";
        moreBtn.textContent = `Ver más (${platformsRest.length})`;
        restContainer.style.display = "none";
        moreBtn.onclick = () => {
          const hidden = restContainer.style.display === "none";
          restContainer.style.display = hidden ? "block" : "none";
          moreBtn.textContent = hidden ? "Ocultar" : `Ver más (${platformsRest.length})`;
        };
      } else {
        moreBtn.style.display = "none";
        restContainer.style.display = "none";
      }
    }

    const metaCreativesRows = (m?.creatives || []).map((r) => withDerived({ ...r, _short: shortName(r.ad_name) }, { convKey: "purchases" }));
    renderTable("meta-creatives", [
      {
        key: "thumbnail_url", label: "", render: (v) =>
          v ? `<img src="${v}" style="width:44px;height:44px;object-fit:cover;border-radius:3px" loading="lazy">` : ""
      },
      { key: "_short", label: "Anuncio", truncate: 220 },
      { key: "adsets", label: "Ad Set", format: (v) => (v || []).join(", "), truncate: 200 },
      ...META_METRIC_COLS,
    ], metaCreativesRows, { limit: 80 });

    const hist = aggregateHistory(
      state.history, "meta",
      ["spend", "impressions", "clicks", "purchases", "revenue"],
      {
        ctr: ["clicks", "impressions", 100],
        cpc: ["spend", "clicks"],
        cpm: ["spend", "impressions", 1000],
        cpa: ["spend", "purchases"],
        conv_rate: ["purchases", "clicks", 100],
        roas: ["revenue", "spend"],
      }
    );
    renderTable("meta-history", [
      { key: "month", label: "Mes" },
      { key: "spend", label: "Inversión", format: fmt.money },
      { key: "impressions", label: "Impresiones", format: fmt.int },
      { key: "clicks", label: "Clics", format: fmt.int },
      { key: "ctr", label: "CTR", format: (v) => `${v.toFixed(2)}%` },
      { key: "cpc", label: "CPC", format: fmt.money2 },
      { key: "cpm", label: "CPM", format: fmt.money2 },
      { key: "purchases", label: "Ventas", format: fmt.int },
      { key: "cpa", label: "CPA", format: fmt.money2 },
      { key: "conv_rate", label: "CR", format: (v) => `${v.toFixed(2)}%` },
      { key: "roas", label: "ROAS", format: fmt.dec2 },
    ], hist);
  }

  function renderGoogle() {
    renderPeriodBar("google");
    const g = state.current?.google;
    const p = state.previous?.google;
    const week = activeWeek("google");
    const allDaily = g?.daily || [];
    const daily = filterDaily(allDaily, week);

    let currentTotals;
    let previousTotals;
    if (week.id === "all") {
      currentTotals = g?.totals;
      previousTotals = p?.totals;
    } else {
      currentTotals = recomputeGoogleTotals(daily);
      const pw = prevWeek("google");
      previousTotals = pw ? recomputeGoogleTotals(filterDaily(allDaily, pw)) : null;
    }

    renderKpis("google-kpis-perf", [
      ["Inversión", "cost", fmt.money, true],
      ["Conversiones", "conversions", fmt.dec2, false],
      ["CPA", "cpa", fmt.money2, true],
      ["CR", "conv_rate", fmt.pct, false],
      ["ROAS", "roas", fmt.dec2, false],
    ], currentTotals, previousTotals);
    renderKpis("google-kpis-traffic", [
      ["Impresiones", "impressions", fmt.int, false],
      ["Clics", "clicks", fmt.int, false],
      ["CTR", "ctr", fmt.pct, false],
      ["CPC", "cpc", fmt.money2, true],
      ["CPM", "cpm", fmt.money2, true],
    ], currentTotals, previousTotals);

    const dLabels = daily.map((d) => (d.date || "").slice(5));
    renderCombo(
      "google-daily-chart",
      dLabels,
      daily.map((d) => d.conversions),
      "Conversiones",
      daily.map((d) => d.cpa),
      "CPA (€)",
    );
    renderLine("google-cpc-chart", dLabels, daily.map((d) => d.cpc), "CPC (€)", LIT.indigo);
    renderLine("google-ctr-chart", dLabels, daily.map((d) => d.ctr), "CTR (%)", LIT.indigo);
    renderCombo(
      "google-spend-revenue-chart",
      dLabels,
      daily.map((d) => d.cost),
      "Inversión (€)",
      daily.map((d) => d.revenue),
      "Revenue (€)",
    );

    const gender = g?.gender || [];
    renderBar("google-gender-chart",
      gender.map((x) => x.gender),
      gender.map((x) => x.conversions),
      "Conversiones");

    const age = g?.age || [];
    renderBar("google-age-chart",
      age.map((x) => x.age_range),
      age.map((x) => x.conversions),
      "Conversiones",
      LIT.beige);

    const GOOGLE_METRIC_COLS = [
      { key: "cost", label: "Inversión", format: fmt.money },
      { key: "impressions", label: "Impresiones", format: fmt.int },
      { key: "clicks", label: "Clics", format: fmt.int },
      { key: "ctr", label: "CTR", format: fmt.pct },
      { key: "cpc", label: "CPC", format: fmt.money2 },
      { key: "_cpm", label: "CPM", format: fmt.money2 },
      { key: "conversions", label: "Conv.", format: fmt.dec2 },
      { key: "cpa", label: "CPA", format: fmt.money2 },
      { key: "conv_rate", label: "CR", format: fmt.pct },
      { key: "roas", label: "ROAS", format: fmt.dec2 },
    ];

    const googleCampaignsRows = (g?.campaigns || []).map((r) => withDerived(r, { spendKey: "cost", convKey: "conversions" }));
    renderTable("google-campaigns", [
      { key: "campaign", label: "Campaña", truncate: 240 },
      { key: "type", label: "Tipo" },
      { key: "status", label: "Estado" },
      ...GOOGLE_METRIC_COLS,
    ], googleCampaignsRows);

    const googleAdGroupsRows = (g?.ad_groups || []).map((r) => withDerived(r, { spendKey: "cost", convKey: "conversions" }));
    renderTable("google-adgroups", [
      { key: "ad_group", label: "Ad Group", truncate: 240 },
      { key: "campaign", label: "Campaña", truncate: 200 },
      { key: "status", label: "Estado" },
      ...GOOGLE_METRIC_COLS,
    ], googleAdGroupsRows);

    const googleKeywordsRows = (g?.keywords || []).map((r) => withDerived({ ...r, cpc: r.avg_cpc, conv_rate: convRate(r.conversions, r.clicks), roas: r.cost ? ((r.revenue || 0) / r.cost) : 0 }, { spendKey: "cost", convKey: "conversions" }));
    renderTable("google-keywords", [
      { key: "keyword", label: "Keyword", truncate: 220 },
      { key: "match_type", label: "Match" },
      { key: "campaign", label: "Campaña", truncate: 200 },
      ...GOOGLE_METRIC_COLS,
    ], googleKeywordsRows, { limit: 100 });

    const hist = aggregateHistory(
      state.history, "google",
      ["cost", "impressions", "clicks", "conversions", "revenue"],
      {
        ctr: ["clicks", "impressions", 100],
        cpc: ["cost", "clicks"],
        cpm: ["cost", "impressions", 1000],
        cpa: ["cost", "conversions"],
        conv_rate: ["conversions", "clicks", 100],
        roas: ["revenue", "cost"],
      }
    );
    renderTable("google-history", [
      { key: "month", label: "Mes" },
      { key: "cost", label: "Inversión", format: fmt.money },
      { key: "impressions", label: "Impresiones", format: fmt.int },
      { key: "clicks", label: "Clics", format: fmt.int },
      { key: "ctr", label: "CTR", format: (v) => `${v.toFixed(2)}%` },
      { key: "cpc", label: "CPC", format: fmt.money2 },
      { key: "cpm", label: "CPM", format: fmt.money2 },
      { key: "conversions", label: "Conv.", format: fmt.dec2 },
      { key: "cpa", label: "CPA", format: fmt.money2 },
      { key: "conv_rate", label: "CR", format: (v) => `${v.toFixed(2)}%` },
      { key: "roas", label: "ROAS", format: fmt.dec2 },
    ], hist);
  }

  function renderKlaviyo() {
    const k = state.current?.klaviyo;
    const p = state.previous?.klaviyo;
    const shopifyRev = state.current?.shopify?.totals?.revenue || 0;
    const kt = k?.totals || {};
    const ktWithPct = { ...kt };
    ktWithPct.email_pct_of_revenue = shopifyRev ? (kt.revenue_total / shopifyRev) * 100 : 0;
    const pt = p?.totals || {};
    const prevShopRev = state.previous?.shopify?.totals?.revenue || 0;
    const ptWithPct = { ...pt };
    ptWithPct.email_pct_of_revenue = prevShopRev ? (pt.revenue_total / prevShopRev) * 100 : 0;

    renderKpis("klaviyo-kpis", [
      ["Revenue total", "revenue_total", fmt.money, false],
      ["Revenue flows", "revenue_flows", fmt.money, false],
      ["Revenue campaigns", "revenue_campaigns", fmt.money, false],
      ["Sends", "sends", fmt.int, false],
      ["Open rate", "open_rate", fmt.pct, false],
      ["Click rate", "click_rate", fmt.pct, false],
      ["Unsub rate", "unsub_rate", fmt.pct, true],
      ["% Shopify rev.", "email_pct_of_revenue", fmt.pct, false],
    ], ktWithPct, ptWithPct);

    const daily = k?.daily || [];
    renderCombo(
      "klaviyo-daily-chart",
      daily.map((d) => d.date),
      daily.map((d) => d.revenue),
      "Revenue (€)",
      daily.map((d) => d.open_rate),
      "Open rate (%)",
    );

    renderTable("klaviyo-flows", [
      { key: "name", label: "Flow" },
      { key: "status", label: "Estado" },
      { key: "sends", label: "Sends", format: fmt.int },
      { key: "open_rate", label: "Open rate", format: fmt.pct },
      { key: "click_rate", label: "Click rate", format: fmt.pct },
      { key: "unsub_rate", label: "Unsub", format: fmt.pct },
      { key: "revenue", label: "Revenue", format: fmt.money },
    ], k?.flows);

    renderTable("klaviyo-campaigns", [
      { key: "send_time", label: "Fecha", format: (v) => (v || "").slice(0, 10) },
      { key: "name", label: "Campaña" },
      { key: "sends", label: "Sends", format: fmt.int },
      { key: "open_rate", label: "Open", format: fmt.pct },
      { key: "click_rate", label: "Click", format: fmt.pct },
      { key: "unsub_rate", label: "Unsub", format: fmt.pct },
      { key: "revenue", label: "Revenue", format: fmt.money },
    ], k?.campaigns);

    const hist = aggregateHistory(
      state.history, "klaviyo",
      ["revenue_total", "revenue_flows", "revenue_campaigns", "sends", "opens", "clicks", "unsubs"],
      { open_rate: ["opens", "sends", 100], click_rate: ["clicks", "sends", 100], unsub_rate: ["unsubs", "sends", 100] }
    );
    renderTable("klaviyo-history", [
      { key: "month", label: "Mes" },
      { key: "revenue_total", label: "Revenue", format: fmt.money },
      { key: "revenue_flows", label: "Flows", format: fmt.money },
      { key: "revenue_campaigns", label: "Campaigns", format: fmt.money },
      { key: "sends", label: "Sends", format: fmt.int },
      { key: "open_rate", label: "Open rate", format: (v) => `${v.toFixed(2)}%` },
      { key: "click_rate", label: "Click rate", format: (v) => `${v.toFixed(2)}%` },
      { key: "unsub_rate", label: "Unsub", format: (v) => `${v.toFixed(2)}%` },
    ], hist);
  }

  function renderShopify() {
    const s = state.current?.shopify;
    const p = state.previous?.shopify;
    renderKpis("shopify-kpis", [
      ["Revenue", "revenue", fmt.money, false],
      ["Orders", "orders", fmt.int, false],
      ["AOV", "aov", fmt.money2, false],
      ["New customers", "new_customers", fmt.int, false],
      ["Returning", "returning_customers", fmt.int, false],
      ["Subscripción %", "subscription_pct", fmt.pct, false],
      ["Recurrentes %", "returning_pct", fmt.pct, false],
      ["Refund rate", "refund_rate", fmt.pct, true],
    ], s?.totals, p?.totals);

    const daily = s?.daily || [];
    renderCombo(
      "shopify-daily-chart",
      daily.map((d) => d.date),
      daily.map((d) => d.orders),
      "Orders",
      daily.map((d) => d.aov),
      "AOV (€)",
    );

    const nvr = s?.breakdowns?.new_vs_returning || [];
    renderBar("shopify-newret-chart",
      nvr.map((x) => x.bucket),
      nvr.map((x) => x.orders),
      "Orders");

    const svo = s?.breakdowns?.subscription_vs_onetime || [];
    renderBar("shopify-subs-chart",
      svo.map((x) => x.bucket),
      svo.map((x) => x.revenue),
      "Revenue",
      LIT.yellow);

    renderTable("shopify-products", [
      { key: "title", label: "Producto" },
      { key: "orders", label: "Orders", format: fmt.int },
      { key: "units", label: "Unidades", format: fmt.int },
      { key: "revenue", label: "Revenue", format: fmt.money },
    ], s?.products, { limit: 30 });

    const hist = aggregateHistory(
      state.history, "shopify",
      ["revenue", "orders", "refunds", "net_revenue", "new_customers", "returning_customers", "subscription_orders", "onetime_orders"],
      { aov: ["revenue", "orders"], returning_pct: ["returning_customers", "orders", 100], subscription_pct: ["subscription_orders", "orders", 100] }
    );
    renderTable("shopify-history", [
      { key: "month", label: "Mes" },
      { key: "revenue", label: "Revenue", format: fmt.money },
      { key: "orders", label: "Orders", format: fmt.int },
      { key: "aov", label: "AOV", format: fmt.money2 },
      { key: "new_customers", label: "Nuevos", format: fmt.int },
      { key: "returning_customers", label: "Recurrentes", format: fmt.int },
      { key: "returning_pct", label: "Recurrentes %", format: (v) => `${v.toFixed(2)}%` },
      { key: "subscription_pct", label: "Subs %", format: (v) => `${v.toFixed(2)}%` },
      { key: "refunds", label: "Refunds", format: fmt.money },
    ], hist);
  }

  // ── NEW: OS Leadership (cross-channel roll-up) ─────────────────────────

  function computeOsTotals(monthData) {
    if (!monthData) return null;
    const s = monthData.shopify?.totals || {};
    const w = monthData.wholesale?.totals || {};
    const a = monthData.affiliates?.totals || {};
    const m = monthData.meta?.totals || {};
    const g = monthData.google?.totals || {};

    const d2cRevenue = s.revenue || 0;
    const wholesaleRevenue = w.revenue || 0;
    const affiliatesRevenue = a.revenue || 0;
    const totalRevenue = d2cRevenue + wholesaleRevenue + affiliatesRevenue;

    const d2cOrders = s.orders || 0;
    const wholesaleOrders = w.orders || 0;
    const affiliatesOrders = a.orders || 0;
    const totalOrders = d2cOrders + wholesaleOrders + affiliatesOrders;

    const metaSpend = m.spend || 0;
    const googleSpend = g.cost || 0;
    const paidSpend = metaSpend + googleSpend;
    const metaRevenue = m.revenue || 0;
    const googleRevenue = g.revenue || 0;
    const paidRevenue = metaRevenue + googleRevenue;

    const newCustomers = s.new_customers || 0;
    return {
      d2c_revenue: +d2cRevenue.toFixed(2),
      wholesale_revenue: +wholesaleRevenue.toFixed(2),
      affiliates_revenue: +affiliatesRevenue.toFixed(2),
      total_revenue: +totalRevenue.toFixed(2),
      d2c_orders: d2cOrders,
      wholesale_orders: wholesaleOrders,
      affiliates_orders: affiliatesOrders,
      total_orders: totalOrders,
      paid_spend: +paidSpend.toFixed(2),
      meta_spend: +metaSpend.toFixed(2),
      google_spend: +googleSpend.toFixed(2),
      paid_revenue: +paidRevenue.toFixed(2),
      blended_roas: paidSpend ? +(paidRevenue / paidSpend).toFixed(2) : 0,
      blended_cac: newCustomers ? +(paidSpend / newCustomers).toFixed(2) : 0,
      d2c_share: totalRevenue ? +((d2cRevenue / totalRevenue) * 100).toFixed(2) : 0,
      wholesale_share: totalRevenue ? +((wholesaleRevenue / totalRevenue) * 100).toFixed(2) : 0,
      affiliates_share: totalRevenue ? +((affiliatesRevenue / totalRevenue) * 100).toFixed(2) : 0,
      subscription_orders: s.subscription_orders || 0,
      subscription_revenue: s.subscription_revenue || 0,
      subscription_pct: s.subscription_pct || 0,
      new_customers: newCustomers,
      returning_pct: s.returning_pct || 0,
      refund_rate: s.refund_rate || 0,
    };
  }

  function renderOsLeadership() {
    const current = computeOsTotals(state.current);
    const previous = computeOsTotals(state.previous);

    renderKpis("os-kpis-revenue", [
      ["Revenue total", "total_revenue", fmt.money, false],
      ["D2C (Shopify)", "d2c_revenue", fmt.money, false],
      ["Wholesale", "wholesale_revenue", fmt.money, false],
      ["Afiliados", "affiliates_revenue", fmt.money, false],
      ["Orders total", "total_orders", fmt.int, false],
    ], current, previous);
    renderKpis("os-kpis-marketing", [
      ["Paid spend", "paid_spend", fmt.money, true],
      ["Paid revenue", "paid_revenue", fmt.money, false],
      ["Blended ROAS", "blended_roas", fmt.dec2, false],
      ["Blended CAC", "blended_cac", fmt.money2, true],
      ["% D2C del total", "d2c_share", fmt.pct, false],
    ], current, previous);
    renderKpis("os-kpis-subs", [
      ["Subs orders", "subscription_orders", fmt.int, false],
      ["Subs revenue", "subscription_revenue", fmt.money, false],
      ["% Subs", "subscription_pct", fmt.pct, false],
      ["New customers", "new_customers", fmt.int, false],
      ["Refund rate", "refund_rate", fmt.pct, true],
    ], current, previous);

    // Historical stacked: revenue by channel per month
    const hist = state.history.map((h) => {
      const t = computeOsTotals(h);
      return { month: h.month, ...t };
    }).sort((a, b) => a.month.localeCompare(b.month));

    destroyChart("os-revenue-mix-chart");
    const mixCtx = document.getElementById("os-revenue-mix-chart");
    if (mixCtx) {
      state.charts["os-revenue-mix-chart"] = new Chart(mixCtx, {
        type: "bar",
        data: {
          labels: hist.map((h) => h.month),
          datasets: [
            { label: "D2C", data: hist.map((h) => h.d2c_revenue), backgroundColor: LIT.indigo },
            { label: "Wholesale", data: hist.map((h) => h.wholesale_revenue), backgroundColor: LIT.beige },
            { label: "Afiliados", data: hist.map((h) => h.affiliates_revenue), backgroundColor: LIT.yellow },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, padding: 16 } } },
          scales: {
            x: { stacked: true, grid: { display: false } },
            y: { stacked: true, beginAtZero: true, grid: { color: LIT.border } },
          },
        },
      });
    }

    // Current month channel share donut
    destroyChart("os-channel-share-chart");
    const shareCtx = document.getElementById("os-channel-share-chart");
    if (shareCtx && current) {
      state.charts["os-channel-share-chart"] = new Chart(shareCtx, {
        type: "doughnut",
        data: {
          labels: ["D2C", "Wholesale", "Afiliados"],
          datasets: [{
            data: [current.d2c_revenue, current.wholesale_revenue, current.affiliates_revenue],
            backgroundColor: [LIT.indigo, LIT.beige, LIT.yellow],
            borderColor: LIT.white,
            borderWidth: 3,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, padding: 16 } } },
        },
      });
    }

    // ROAS per platform history
    const roasMeta = state.history.map((h) => ({ month: h.month, roas: h.meta?.totals?.roas || 0 }));
    const roasGoogle = state.history.map((h) => ({ month: h.month, roas: h.google?.totals?.roas || 0 }));
    destroyChart("os-roas-chart");
    const roasCtx = document.getElementById("os-roas-chart");
    if (roasCtx) {
      state.charts["os-roas-chart"] = new Chart(roasCtx, {
        type: "line",
        data: {
          labels: state.history.map((h) => h.month),
          datasets: [
            { label: "Meta ROAS", data: roasMeta.map((x) => x.roas), borderColor: LIT.indigo, backgroundColor: LIT.indigo, tension: 0.25, borderWidth: 2, pointRadius: 3 },
            { label: "Google ROAS", data: roasGoogle.map((x) => x.roas), borderColor: LIT.beige, backgroundColor: LIT.beige, tension: 0.25, borderWidth: 2, pointRadius: 3 },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, padding: 16 } } },
          scales: {
            y: { beginAtZero: true, grid: { color: LIT.border } },
            x: { grid: { display: false } },
          },
        },
      });
    }

    renderTable("os-history", [
      { key: "month", label: "Mes" },
      { key: "total_revenue", label: "Revenue total", format: fmt.money },
      { key: "d2c_revenue", label: "D2C", format: fmt.money },
      { key: "wholesale_revenue", label: "Wholesale", format: fmt.money },
      { key: "affiliates_revenue", label: "Afiliados", format: fmt.money },
      { key: "paid_spend", label: "Paid spend", format: fmt.money },
      { key: "blended_roas", label: "Blended ROAS", format: fmt.dec2 },
      { key: "blended_cac", label: "Blended CAC", format: fmt.money2 },
      { key: "d2c_share", label: "% D2C", format: (v) => `${v.toFixed(1)}%` },
    ], hist);
  }

  // ── NEW: Wholesale ──────────────────────────────────────────────────────

  function renderWholesale() {
    const w = state.current?.wholesale;
    const p = state.previous?.wholesale;
    renderKpis("wholesale-kpis", [
      ["Orders", "orders", fmt.int, false],
      ["Revenue", "revenue", fmt.money, false],
      ["AOV", "aov", fmt.money2, false],
      ["Pagado %", "paid_pct", fmt.pct, false],
      ["Cuentas únicas", "accounts", fmt.int, false],
    ], w?.totals, p?.totals);

    const daily = w?.daily || [];
    renderCombo(
      "wholesale-daily-chart",
      daily.map((d) => (d.date || "").slice(5)),
      daily.map((d) => d.orders),
      "Pedidos",
      daily.map((d) => d.revenue),
      "Revenue (€)",
    );

    const pipeline = w?.pipeline || [];
    renderBar(
      "wholesale-pipeline-chart",
      pipeline.map((s) => s.stage),
      pipeline.map((s) => s.count),
      "Leads",
      LIT.indigo,
    );

    // Paid vs pending donut
    destroyChart("wholesale-paid-chart");
    const paidCtx = document.getElementById("wholesale-paid-chart");
    if (paidCtx && w?.totals) {
      state.charts["wholesale-paid-chart"] = new Chart(paidCtx, {
        type: "doughnut",
        data: {
          labels: ["Pagado", "Pendiente"],
          datasets: [{
            data: [w.totals.paid || 0, w.totals.pending || 0],
            backgroundColor: [LIT.indigo, LIT.yellow],
            borderColor: LIT.white,
            borderWidth: 3,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, padding: 16 } } },
        },
      });
    }

    renderTable("wholesale-accounts", [
      { key: "account", label: "Cuenta", truncate: 320 },
      { key: "orders", label: "Orders", format: fmt.int },
      { key: "revenue", label: "Revenue", format: fmt.money },
    ], w?.top_accounts, { limit: 50 });

    const hist = aggregateHistory(
      state.history, "wholesale",
      ["orders", "revenue", "paid", "pending", "accounts"],
      { aov: ["revenue", "orders"], paid_pct: ["paid", "revenue", 100] },
    );
    renderTable("wholesale-history", [
      { key: "month", label: "Mes" },
      { key: "orders", label: "Orders", format: fmt.int },
      { key: "revenue", label: "Revenue", format: fmt.money },
      { key: "aov", label: "AOV", format: fmt.money2 },
      { key: "paid", label: "Pagado", format: fmt.money },
      { key: "pending", label: "Pendiente", format: fmt.money },
      { key: "paid_pct", label: "Pagado %", format: (v) => `${v.toFixed(1)}%` },
      { key: "accounts", label: "Cuentas", format: fmt.int },
    ], hist);
  }

  // ── NEW: Affiliates ─────────────────────────────────────────────────────

  function renderAffiliates() {
    const a = state.current?.affiliates;
    const p = state.previous?.affiliates;
    renderKpis("affiliates-kpis", [
      ["Revenue", "revenue", fmt.money, false],
      ["Orders", "orders", fmt.int, false],
      ["Afiliados activos", "active_affiliates", fmt.int, false],
      ["Total afiliados", "total_affiliates", fmt.int, false],
      ["Comisión %", "commission_rate", fmt.pct, true],
    ], a?.totals, p?.totals);

    const daily = a?.daily || [];
    renderCombo(
      "affiliates-daily-chart",
      daily.map((d) => (d.date || "").slice(5)),
      daily.map((d) => d.revenue),
      "Revenue (€)",
      daily.map((d) => d.commission),
      "Comisiones (€)",
    );

    renderTable("affiliates-top", [
      { key: "name", label: "Afiliado", truncate: 200 },
      { key: "ref_code", label: "Código", truncate: 160 },
      { key: "orders", label: "Orders", format: fmt.int },
      { key: "revenue", label: "Revenue", format: fmt.money },
      { key: "commission", label: "Comisión", format: fmt.money2 },
    ], a?.top_affiliates, { limit: 50 });

    const hist = aggregateHistory(
      state.history, "affiliates",
      ["orders", "revenue", "commission", "active_affiliates", "total_affiliates", "new_affiliates"],
      { aov: ["revenue", "orders"], commission_rate: ["commission", "revenue", 100] },
    );
    renderTable("affiliates-history", [
      { key: "month", label: "Mes" },
      { key: "orders", label: "Orders", format: fmt.int },
      { key: "revenue", label: "Revenue", format: fmt.money },
      { key: "aov", label: "AOV", format: fmt.money2 },
      { key: "commission", label: "Comisión", format: fmt.money },
      { key: "commission_rate", label: "Com %", format: (v) => `${v.toFixed(2)}%` },
      { key: "active_affiliates", label: "Activos", format: fmt.int },
      { key: "new_affiliates", label: "Nuevos", format: fmt.int },
    ], hist);
  }

  function renderAll() {
    renderOsLeadership();
    renderMeta();
    renderGoogle();
    renderKlaviyo();
    renderShopify();
    renderWholesale();
    renderAffiliates();
    document.getElementById("generated-at").textContent = state.current?.generated_at?.slice(0, 16).replace("T", " ") ?? "—";
  }

  async function selectMonth(month) {
    const label = document.getElementById("month-label");
    if (label) label.textContent = month;
    state.weeks = buildWeeks(month);
    state.period.meta = "all";
    state.period.google = "all";
    const [curr, prev] = await Promise.all([loadMonth(month), loadMonth(prevMonth(month))]);
    state.current = curr;
    state.previous = prev;
    renderAll();
  }

  function switchTab(name) {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    document.querySelectorAll(".section").forEach((s) => s.classList.toggle("active", s.dataset.section === name));
  }

  async function init() {
    try {
      state.manifest = await loadManifest();
    } catch (e) {
      document.body.innerHTML = `<div style="padding:40px;font-family:system-ui">No se pudo cargar <code>data/manifest.json</code>. Ejecuta <code>python extract.py</code> primero.</div>`;
      return;
    }
    const months = state.manifest.months || [];
    if (!months.length) {
      document.body.innerHTML = `<div style="padding:40px;font-family:system-ui">Sin datos en <code>data/</code>.</div>`;
      return;
    }

    const sel = document.getElementById("month-select");
    months.slice().reverse().forEach((m) => {
      const o = document.createElement("option");
      o.value = m;
      o.textContent = m;
      sel.appendChild(o);
    });
    sel.value = months[months.length - 1];
    sel.addEventListener("change", () => selectMonth(sel.value));

    document.querySelectorAll(".tab").forEach((t) => {
      t.addEventListener("click", () => switchTab(t.dataset.tab));
    });

    state.history = [];
    for (const m of months) {
      const data = await loadMonth(m);
      if (data) state.history.push(data);
    }
    state.history.sort((a, b) => a.month.localeCompare(b.month));

    await selectMonth(sel.value);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
