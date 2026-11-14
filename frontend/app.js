/* Earth Analog Finder - reference frontend.
   Plain JS + Leaflet + Chart.js so it runs from any static host. Feel free to port to React:
   the only things you need are scoring.js (same maths as the backend) and data/sites.json. */
(function () {
  "use strict";
  const cfg = window.APP_CONFIG || {};
  const API = (cfg.API_BASE || "").replace(/\/$/, "");
  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (x) => Math.round(x * 100);

  const state = { data: null, targetId: null, weights: {}, types: new Set(), selectedId: null, compare: [], results: [] };
  let map, markers, radar;

  // green (good) -> amber -> red (poor), by similarity 0..1
  function scoreColor(s) {
    if (s >= 0.8) return "#46c98b";
    if (s >= 0.65) return "#e6c04f";
    return "#e5675d";
  }
  const target = () => state.data.targets.find((t) => t.id === state.targetId);
  const cand = (id) => state.data.candidates.find((c) => c.id === id);
  const factorLabel = (f) => (state.data.meta.factors[f] || {}).label || f;

  async function loadData() {
    const r = await fetch(cfg.DATA_URL || "data/sites.json");
    if (!r.ok) throw new Error("Could not load " + (cfg.DATA_URL || "data/sites.json"));
    return r.json();
  }

  // ---------------------------------------------------------------- map
  function initMap() {
    map = L.map("map", { worldCopyJump: true, minZoom: 2 }).setView([22, 10], 2);
    const gibs = L.tileLayer(
      "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg",
      { maxZoom: 8, attribution: "Imagery: NASA GIBS (Blue Marble)" });
    const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      { maxZoom: 18, attribution: "&copy; OpenStreetMap contributors" });
    gibs.addTo(map);
    L.control.layers({ "Satellite (NASA GIBS)": gibs, "Streets (OpenStreetMap)": osm }, null, { position: "topright" }).addTo(map);
    markers = L.layerGroup().addTo(map);
  }

  function renderMarkers() {
    markers.clearLayers();
    state.results.forEach((r) => {
      const selected = r.id === state.selectedId;
      const m = L.circleMarker([r.lat, r.lon], {
        radius: selected ? 12 : Math.max(6, 12 - r.rank * 0.4),
        color: selected ? "#ffffff" : "#0b1020", weight: selected ? 3 : 1.5,
        fillColor: scoreColor(r.score), fillOpacity: 0.95,
      });
      m.bindTooltip(`#${r.rank} ${esc(r.name)} - ${pct(r.score)}%`);
      m.on("click", () => selectSite(r.id));
      markers.addLayer(m);
    });
  }

  // ---------------------------------------------------------------- sidebar
  function renderTargets() {
    $("#targets").innerHTML = state.data.targets.map((t) => `
      <button class="target" type="button" data-id="${esc(t.id)}" aria-pressed="${t.id === state.targetId}">
        <b>${esc(t.name)}<span class="body-tag ${esc(t.body)}">${esc(t.body)}</span></b>
        <small>${esc(t.blurb || "")}</small>
      </button>`).join("");
    $("#targets").querySelectorAll(".target").forEach((b) =>
      b.addEventListener("click", () => { state.targetId = b.dataset.id; state.selectedId = null; state.compare = []; update(); }));
  }

  function renderSliders() {
    $("#sliders").innerHTML = Scoring.FACTORS.map((f) => `
      <div class="slider-row" title="${esc((state.data.meta.factors[f] || {}).desc || "")}">
        <label for="w_${f}">${esc(factorLabel(f))}</label><output id="o_${f}">${state.weights[f]}</output>
        <input id="w_${f}" type="range" min="0" max="10" step="1" value="${state.weights[f]}" data-f="${f}">
      </div>`).join("");
    $("#sliders").querySelectorAll("input").forEach((i) =>
      i.addEventListener("input", () => {
        state.weights[i.dataset.f] = Number(i.value);
        $("#o_" + i.dataset.f).textContent = i.value;
        if (Scoring.FACTORS.every((f) => state.weights[f] === 0)) return; // need at least one non-zero weight
        update();
      }));
  }

  function renderChips() {
    const types = [...new Set(state.data.candidates.map((c) => c.type))].sort();
    $("#typeChips").innerHTML = types.map((t) =>
      `<button type="button" class="chip" data-t="${esc(t)}" aria-pressed="${state.types.has(t)}">${esc(t)}</button>`).join("");
    $("#typeChips").querySelectorAll(".chip").forEach((b) =>
      b.addEventListener("click", () => {
        state.types.has(b.dataset.t) ? state.types.delete(b.dataset.t) : state.types.add(b.dataset.t);
        b.setAttribute("aria-pressed", state.types.has(b.dataset.t));
        update();
      }));
  }

  function renderResults() {
    const list = $("#results");
    if (!state.results.length) { list.innerHTML = `<li class="hint">No sites match these filters.</li>`; return; }
    list.innerHTML = state.results.map((r) => `
      <li class="result ${r.id === state.selectedId ? "active" : ""}" data-id="${esc(r.id)}">
        <span class="rk">${r.rank}</span>
        <span class="nm">${esc(r.name)}<small>${esc(r.type)}</small></span>
        <span class="score" style="background:${scoreColor(r.score)}">${pct(r.score)}%</span>
        <input type="checkbox" class="cmp" aria-label="Compare ${esc(r.name)}" ${state.compare.includes(r.id) ? "checked" : ""}>
      </li>`).join("");
    list.querySelectorAll(".result").forEach((li) => {
      li.addEventListener("click", (e) => { if (!e.target.classList.contains("cmp")) selectSite(li.dataset.id); });
      li.querySelector(".cmp").addEventListener("change", (e) => toggleCompare(li.dataset.id, e.target.checked));
    });
  }

  // ---------------------------------------------------------------- detail
  function selectSite(id) { state.selectedId = id; renderResults(); renderMarkers(); renderDetail(); }

  function renderDetail() {
    const box = $("#detail");
    if (radar) { radar.destroy(); radar = null; }
    const r = state.results.find((x) => x.id === state.selectedId);
    if (!r) {
      const top = state.results[0];
      box.innerHTML = `<p class="placeholder">${top
        ? `Best match for <b>${esc(target().name)}</b>: <b>${esc(top.name)}</b> (${pct(top.score)}%).<br>Click a site on the map or in the list to see why.`
        : "Choose a target to begin."}</p>`;
      return;
    }
    const c = cand(r.id), t = target();
    const est = (obj, f) => (obj.confidence && obj.confidence[f] === "estimated") ? `<span class="est" title="Estimated, not measured">est.</span>` : "";
    box.innerHTML = `
      <h3>${esc(c.name)}</h3>
      <div class="sub">${esc(c.type)} analog for ${esc(t.name)}</div>
      <div class="big-score" style="color:${scoreColor(r.score)}">${pct(r.score)}%</div>
      <div class="tag">overall similarity (weighted)</div>
      <div>${(c.features || []).map((f) => `<span class="feat">${esc(f.replace(/_/g, " "))}</span>`).join("")}</div>
      ${c.image_url ? `<img class="site-img" src="${esc(c.image_url)}" alt="${esc(c.name)}"><div class="credit">${esc(c.image_credit || "")}</div>` : ""}
      <p class="why">${esc(c.why || "")}</p>
      <canvas id="radar" aria-label="Radar chart comparing target and site"></canvas>
      <div>${Scoring.FACTORS.map((f) => `
        <div class="bar-row"><span>${esc(factorLabel(f))}${est(c, f)}${est(t, f)}</span>
          <span class="bar"><i style="width:${pct(r.breakdown[f])}%;background:${scoreColor(r.breakdown[f])}"></i></span>
          <span>${pct(r.breakdown[f])}%</span></div>`).join("")}</div>
      <div class="callout"><b>Where the analogy breaks down.</b> ${esc(c.breaks_down || "")}
        Earth cannot reproduce reduced gravity, vacuum or a thin atmosphere, or the radiation environment.</div>
      <button class="btn" id="explainBtn" type="button">Explain this match (AI)</button>
      <div class="explain-box" id="explainOut" hidden></div>`;
    $("#explainBtn").addEventListener("click", explain);
    if (window.Chart) {
      radar = new Chart($("#radar"), {
        type: "radar",
        data: {
          labels: Scoring.FACTORS.map(factorLabel),
          datasets: [
            { label: t.name, data: Scoring.FACTORS.map((f) => t.factors[f]), borderColor: "#f0b35a", backgroundColor: "rgba(240,179,90,.18)" },
            { label: c.name, data: Scoring.FACTORS.map((f) => c.factors[f]), borderColor: "#6fd3ff", backgroundColor: "rgba(111,211,255,.18)" },
          ],
        },
        options: { scales: { r: { min: 0, max: 1, ticks: { display: false }, grid: { color: "#26325a" }, angleLines: { color: "#26325a" }, pointLabels: { color: "#9aa6c9" } } },
                   plugins: { legend: { labels: { color: "#e8ecf8" } } } },
      });
    }
  }

  async function explain() {
    const btn = $("#explainBtn"), out = $("#explainOut");
    btn.disabled = true; out.hidden = false;
    out.textContent = "Asking the AI... (the first request can take ~30 s if the free server is waking up)";
    try {
      const r = await fetch(`${API}/api/explain`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_id: state.targetId, candidate_id: state.selectedId, weights: state.weights }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      out.innerHTML = `<p>${esc(j.explanation)}</p><div class="tag">${j.source === "ai" ? "AI-generated (" + esc(j.model) + ") from the data shown here" : "Template text (AI not available)"}</div>`;
    } catch (e) {
      out.textContent = "The explanation service is not reachable right now. The scores and charts above still work.";
    } finally { btn.disabled = false; }
  }

  // ---------------------------------------------------------------- compare
  function toggleCompare(id, on) {
    state.compare = state.compare.filter((x) => x !== id);
    if (on) state.compare.push(id);
    if (state.compare.length > 2) state.compare = state.compare.slice(-2);
    renderResults(); renderCompare();
  }

  function renderCompare() {
    const box = $("#compare");
    if (state.compare.length !== 2) { box.hidden = true; return; }
    const [a, b] = state.compare.map((id) => state.results.find((r) => r.id === id));
    if (!a || !b) { box.hidden = true; return; }
    const ca = cand(a.id), cb = cand(b.id), t = target();
    $("#compareBody").innerHTML = `<table>
      <tr><th>Factor</th><th>${esc(t.name)}</th><th>${esc(ca.name)}</th><th>${esc(cb.name)}</th></tr>
      ${Scoring.FACTORS.map((f) => `<tr><td>${esc(factorLabel(f))}</td><td class="num">${pct(t.factors[f])}</td>
        <td class="num">${pct(ca.factors[f])} <span class="tag">(${pct(a.breakdown[f])}% match)</span></td>
        <td class="num">${pct(cb.factors[f])} <span class="tag">(${pct(b.breakdown[f])}% match)</span></td></tr>`).join("")}
      <tr><th>Overall</th><th></th><th>${pct(a.score)}%</th><th>${pct(b.score)}%</th></tr>
      <tr><td>Where it breaks down</td><td></td><td>${esc(ca.breaks_down || "")}</td><td>${esc(cb.breaks_down || "")}</td></tr>
    </table>`;
    box.hidden = false;
  }

  // ---------------------------------------------------------------- update loop
  function update() {
    state.results = Scoring.rank(target(), state.data.candidates, state.weights, state.types);
    if (state.selectedId && !state.results.some((r) => r.id === state.selectedId)) state.selectedId = null;
    renderTargets(); renderResults(); renderMarkers(); renderDetail(); renderCompare();
  }

  async function init() {
    try { state.data = await loadData(); }
    catch (e) { $("#detail").innerHTML = `<p class="placeholder">${esc(e.message)}</p>`; return; }
    Scoring.FACTORS.forEach((f) => (state.weights[f] = 5));
    state.targetId = state.data.targets[0].id;
    $("#mockBadge").hidden = !/mock|placeholder/i.test(state.data.meta.version || "");
    $("#assumption").textContent = state.data.meta.assumption || "";
    $("#resetWeights").addEventListener("click", () => { Scoring.FACTORS.forEach((f) => (state.weights[f] = 5)); renderSliders(); update(); });
    $("#closeCompare").addEventListener("click", () => { state.compare = []; renderResults(); renderCompare(); });
    initMap(); renderSliders(); renderChips(); update();
  }
  init();
})();
