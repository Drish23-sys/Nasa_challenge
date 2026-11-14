/* Same maths as backend/app/scoring.py (kept in sync by backend/scripts/check_js_parity.py).
   Works in the browser (window.Scoring) and in Node (require). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Scoring = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const FACTORS = ["slope", "roughness", "temp_range", "aridity", "basaltic"];

  function cleanWeights(weights) {
    const raw = {};
    let total = 0;
    for (const f of FACTORS) {
      const v = weights && weights[f] != null ? Number(weights[f]) : 1;
      if (!isFinite(v) || v < 0) throw new Error("invalid weight for " + f);
      raw[f] = v;
      total += v;
    }
    if (total <= 0) throw new Error("at least one weight must be greater than zero");
    const out = {};
    for (const f of FACTORS) out[f] = raw[f] / total;
    return out;
  }

  function scorePair(targetFactors, candFactors, weights) {
    const w = cleanWeights(weights);
    const breakdown = {};
    let score = 0;
    for (const f of FACTORS) {
      breakdown[f] = 1 - Math.abs(targetFactors[f] - candFactors[f]);
      score += w[f] * breakdown[f];
    }
    return { score, breakdown, weights: w };
  }

  /* types: Set or array of environment types; empty means "all" */
  function rank(target, candidates, weights, types) {
    const wanted = types && (types.size !== undefined ? types.size : types.length) ? new Set(types) : null;
    const out = [];
    for (const c of candidates) {
      if (wanted && !wanted.has(c.type)) continue;
      const r = scorePair(target.factors, c.factors, weights);
      out.push({ id: c.id, name: c.name, type: c.type, lat: c.lat, lon: c.lon,
                 features: c.features || [], score: r.score, breakdown: r.breakdown });
    }
    // compare rounded scores so float noise never reorders ties (matches the Python version)
    const r9 = (x) => Math.round(x * 1e9);
    out.sort((a, b) => (r9(b.score) - r9(a.score)) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    out.forEach((x, i) => (x.rank = i + 1));
    return out;
  }

  return { FACTORS, cleanWeights, scorePair, rank };
});
