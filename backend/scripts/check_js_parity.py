#!/usr/bin/env python3
"""Checks that frontend/scoring.js and backend/app/scoring.py rank identically.

  python backend/scripts/check_js_parity.py        (needs Node.js)
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import scoring  # noqa: E402

data = json.loads((ROOT / "data" / "sites.json").read_text())
cases = [
    None,
    {"slope": 10, "roughness": 0, "temp_range": 0, "aridity": 0, "basaltic": 0},
    {"slope": 1, "roughness": 2, "temp_range": 8, "aridity": 3, "basaltic": 0},
]
js = f"""
const S = require({json.dumps(str(ROOT / 'frontend' / 'scoring.js'))});
const d = {json.dumps(data)};
const cases = {json.dumps(cases)};
const out = [];
for (const t of d.targets) for (const w of cases)
  out.push(S.rank(t, d.candidates, w, null).map(r => [r.id, r.score]));
console.log(JSON.stringify(out));
"""
js_out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)

i, bad = 0, 0
for t in data["targets"]:
    for w in cases:
        py = [(r["id"], r["score"]) for r in scoring.rank(t, data["candidates"], w)]
        for (pid, ps), (jid, jsx) in zip(py, js_out[i]):
            if pid != jid or abs(ps - jsx) > 1e-9:
                bad += 1
                print("MISMATCH", t["id"], w, pid, ps, jid, jsx)
        i += 1
print("parity OK" if not bad else f"{bad} mismatches")
sys.exit(1 if bad else 0)
