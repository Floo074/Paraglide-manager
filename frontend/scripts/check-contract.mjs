// Valide les VRAIES réponses du backend contre src/api/types.ts (contrat docs/API_CONTRACT.md).
//
//   node scripts/check-contract.mjs [BASE_URL] [--live] [--ref 2026-10-11T08:30:00Z] [--out DIR]
//
// 1. Appelle chaque endpoint (health, sources, sites, beacons, airspaces, sensitive-areas, forecast/point,
//    forecast/grid pour chaque couche, POST /plans classique 15m/30m/2h/24h et custom_takeoff, GET /plans/{id},
//    /gpx, /xctsk, POST /landings/analyze), avec des contrôles sémantiques (dates ISO « Z », landing_kind,
//    tri des verdicts, liens d'export, anneau du cône fermé…).
// 2. Écrit chaque réponse JSON dans DIR et la type comme littéral objet (`const v: PlanResponse = {...}`) :
//    tsc signale les champs manquants, en trop, les null et les énumérations hors contrat.
// --live : ménage les quotas (Open-Meteo) — moins de couches de grille, horizons 30m et 2h seulement.
// Code de retour 1 si un contrôle échoue.
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FRONT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const opt = (name, def) => (args.includes(name) ? args[args.indexOf(name) + 1] : def);
const BASE = (args.find((a) => /^https?:/.test(a)) ?? "http://localhost:8000").replace(/\/$/, "");
const LIVE = args.includes("--live");
const REF = opt("--ref", "2026-10-11T08:30:00Z");
const OUT = resolve(opt("--out", join(tmpdir(), "pm-contract")));
rmSync(OUT, { recursive: true, force: true });
mkdirSync(join(OUT, "ts"), { recursive: true });

const manifest = {};
const problems = [];
const timings = [];
const check = (cond, msg) => {
  if (!cond) problems.push(msg);
};

async function call(name, method, path, { body, type, expect = 200, raw = false } = {}) {
  const t0 = Date.now();
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(180_000),
    });
  } catch (e) {
    problems.push(`${name}: exception ${e}`);
    timings.push([name, Date.now() - t0, -1]);
    return null;
  }
  timings.push([name, Date.now() - t0, res.status]);
  const text = await res.text();
  if (res.status !== expect) {
    problems.push(`${name}: HTTP ${res.status} (attendu ${expect}) ${text.slice(0, 240)}`);
    return null;
  }
  if (raw) return { type: res.headers.get("content-type") ?? "", text };
  let obj;
  try {
    obj = JSON.parse(text);
  } catch {
    problems.push(`${name}: réponse non JSON`);
    return null;
  }
  if (type) {
    writeFileSync(join(OUT, `${name}.json`), JSON.stringify(obj, null, 1));
    manifest[name] = type;
  }
  return obj;
}

const isIso = (v) => typeof v === "string" && v.includes("T") && v.endsWith("Z");
const checkIso = (where, v) => check(isIso(v), `${where}: date non ISO UTC « Z » : ${v}`);
const SOURCES = ["ffvl", "paraglidingearth", "spotair", "osm", "user", "fixture"];

function checkSite(where, s) {
  if (s.kind === "landing" || s.kind === "both") check(s.landing_kind != null, `${where}: site ${s.id} (${s.kind}) sans landing_kind`);
  else check(s.landing_kind == null, `${where}: décollage ${s.id} avec landing_kind=${s.landing_kind}`);
  check(SOURCES.includes(s.source), `${where}: source inconnue ${s.source}`);
}

function checkPlan(where, p) {
  checkIso(`${where}.target_time`, p.target_time);
  checkIso(`${where}.window.start`, p.window.start);
  checkIso(`${where}.window.end`, p.window.end);
  for (const s of [p.takeoff, p.landing, ...p.alternate_landings]) checkSite(where, s);
  const la = p.landing_analysis ?? [];
  check(la.length <= 8, `${where}: landing_analysis > 8 (${la.length})`);
  if (la.length) check(la[0].site.id === p.landing.id, `${where}: landing_analysis[0] (${la[0].site.id}) ≠ atterro du plan (${p.landing.id})`);
  for (const c of la) {
    checkSite(`${where}.landing_analysis`, c.site);
    check(c.kind === c.site.landing_kind, `${where}: candidat ${c.site.id} kind ${c.kind} ≠ site.landing_kind ${c.site.landing_kind}`);
    if (c.kind !== "official") check(c.warnings.some((w) => w.includes("Non officiel")), `${where}: candidat non officiel sans « Non officiel »`);
  }
  for (const r of p.station_readings ?? []) {
    check(["takeoff", "landing", "alternate_landing"].includes(r.site_role), `${where}: site_role ${r.site_role}`);
    check(r.weight >= 0 && r.weight <= 1, `${where}: weight hors 0..1`);
  }
  check(p.confidence >= 0 && p.confidence <= 1, `${where}: confidence hors 0..1`);
  check(p.links.gpx === `/api/plans/${p.id}/gpx`, `${where}: links.gpx ${p.links.gpx}`);
  check(p.links.xctsk === `/api/plans/${p.id}/xctsk`, `${where}: links.xctsk ${p.links.xctsk}`);
  check(p.route.coordinates.every((c) => c.length === 3), `${where}: route sans altitude`);
  const al = p.weather.takeoff.winds_aloft.map((w) => w.altitude_m);
  check(al.every((v, i) => i === 0 || al[i - 1] <= v), `${where}: winds_aloft non triés`);
}

const ANNECY = "6.05,45.70,6.40,45.95";
const log = (...a) => console.log(...a);

// ── GET simples
await call("health", "GET", "/api/health", { type: "HealthResponse" });
await call("sources", "GET", "/api/sources", { type: "SourcesResponse" });
const sites = await call("sites", "GET", `/api/sites?bbox=${ANNECY}`, { type: "SitesResponse" });
if (sites) {
  sites.sites.forEach((s) => checkSite("sites", s));
  log(`sites Annecy : ${sites.sites.length} (décos ${sites.sites.filter((s) => s.kind !== "landing").length})`);
}
await call("beacons", "GET", `/api/beacons?bbox=${ANNECY}`, { type: "BeaconsResponse" });
await call("airspaces", "GET", `/api/airspaces?bbox=${ANNECY}`, { type: "AirspaceFeatureCollection" });
await call("sensitive_areas", "GET", `/api/sensitive-areas?bbox=${ANNECY}&time=${REF}`, { type: "SensitiveAreaFeatureCollection" });
await call("forecast_point", "GET", `/api/forecast/point?lat=45.83&lon=6.22&time=${REF}`, { type: "ForecastPointResponse" });
for (const layer of LIVE ? ["wind", "thermal"] : ["wind", "thermal", "cloudbase", "ceiling", "cape", "precipitation", "useful_height"]) {
  for (const alt of layer === "wind" && !LIVE ? [10, 2000] : layer === "wind" ? [10] : [null]) {
    const q = `/api/forecast/grid?bbox=${ANNECY}&time=${REF}&layer=${layer}${alt !== null ? `&altitude_m=${alt}` : ""}`;
    const g = await call(`grid_${layer}${alt ?? ""}`, "GET", q, { type: "ForecastGridResponse" });
    if (!g) continue;
    check(g.points.length <= (LIVE ? 100 : 400), `grid ${layer}: ${g.points.length} points`);
    if (layer === "useful_height") check(g.unit === "m_agl", `grid useful_height: unit ${g.unit}`);
    if (layer === "wind") check(g.points.every((p) => p.direction_deg !== null), "grid wind: direction nulle");
    const vals = g.points.map((p) => p.value);
    if (vals.length) check(g.legend.min === Math.min(...vals) && g.legend.max === Math.max(...vals), `grid ${layer}: légende ≠ min/max`);
  }
}

// ── POST /plans
const filters = { duration_min_minutes: 15, duration_max_minutes: 120, difficulty: "intermediate", thermals: "allowed" };
const zone = { type: "bbox", min_lat: 45.7, min_lon: 6.05, max_lat: 45.95, max_lon: 6.4 };
let firstPlan = null;
for (const hz of LIVE ? ["30m", "2h"] : ["15m", "30m", "2h", "24h"]) {
  const r = await call(`plans_${hz}`, "POST", "/api/plans", { body: { zone, horizon: hz, reference_time: REF, filters, mode: "classic" }, type: "PlanResponse" });
  if (!r) continue;
  checkIso(`plans_${hz}.target_time`, r.target_time);
  check(r.horizon === hz, `plans_${hz}: horizon ${r.horizon}`);
  r.plans.forEach((p, i) => checkPlan(`plans_${hz}[${i}]`, p));
  r.rejected.forEach((x) => checkSite(`plans_${hz}.rejected`, x.site));
  check(r.plans.map((p) => p.rank).join() === r.plans.map((_, i) => i + 1).join(), `plans_${hz}: rangs non consécutifs`);
  const v = r.plans.map((p) => ({ go: 2, marginal: 1, no_go: 0 })[p.flyability]);
  check(v.every((x, i) => i === 0 || v[i - 1] >= x), `plans_${hz}: verdicts non ordonnés`);
  log(`plans ${hz} : ${r.plans.length} plans, ${r.rejected.length} écartés, cible ${r.target_time}, balises rattachées ${r.plans.reduce((n, p) => n + p.station_readings.length, 0)}`);
  firstPlan ??= r.plans[0] ?? null;
}
const pt = LIVE ? { lat: 45.8348, lon: 6.2306 } : { lat: 45.825, lon: 6.269 };
const customBody = {
  zone: { type: "circle", center: pt, radius_km: 15 },
  horizon: "2h",
  reference_time: REF,
  filters: { ...filters, difficulty: "advanced", landing_policy: "include_fields" },
  mode: "custom_takeoff",
  custom_takeoff: { ...pt, name: "Point test" },
};
const custom = await call("plans_custom", "POST", "/api/plans", { body: customBody, type: "PlanResponse" });
if (custom) {
  custom.plans.forEach((p, i) => {
    checkPlan(`plans_custom[${i}]`, p);
    check(p.takeoff.source === "user", "plans_custom: takeoff.source ≠ user");
  });
  log(`plans custom_takeoff : ${custom.plans.length} plans, ${custom.rejected.length} écartés`);
}
await call("err_custom_missing", "POST", "/api/plans", { body: { ...customBody, custom_takeoff: null }, expect: 422 });
await call("err_zone_big", "POST", "/api/plans", { body: { zone: { type: "circle", center: { lat: 45.8, lon: 6.2 }, radius_km: 200 }, horizon: "2h", filters }, expect: 422 });
await call("err_plan_404", "GET", "/api/plans/inexistant", { expect: 404 });

// ── fiche et exports
if (firstPlan) {
  const id = firstPlan.id;
  const p = await call("plan_get", "GET", `/api/plans/${id}`, { type: "FlightPlan" });
  if (p) checkPlan("plan_get", p);
  const gpx = await call("plan_gpx", "GET", `/api/plans/${id}/gpx`, { raw: true });
  if (gpx) {
    check(gpx.type.includes("application/gpx+xml"), `gpx: content-type ${gpx.type}`);
    check(/<gpx[^>]+version="1\.1"/.test(gpx.text) && gpx.text.includes("<metadata") && gpx.text.includes("<rte"), "gpx: racine 1.1 / metadata / rte manquants");
    check((gpx.text.match(/<wpt /g) ?? []).length >= 2, "gpx: moins de 2 wpt");
  }
  const x = await call("plan_xctsk", "GET", `/api/plans/${id}/xctsk`, { type: "XctskTask" });
  if (x) {
    check(x.turnpoints[0]?.type === "TAKEOFF", "xctsk: 1re balise ≠ TAKEOFF");
    check(x.turnpoints.at(-1)?.type === "ESS", "xctsk: dernière balise ≠ ESS");
  }
} else problems.push("aucun plan obtenu : GET /plans/{id}, /gpx, /xctsk non testés");

// ── analyse des atterrissages
for (const lvl of ["intermediate", "advanced", "beginner"]) {
  const a = await call(`analyze_${lvl}`, "POST", "/api/landings/analyze", {
    body: { takeoff: { ...pt, name: "Point test" }, horizon: "2h", reference_time: REF, difficulty: lvl, landing_policy: "include_fields" },
    type: "LandingAnalyzeResponse",
  });
  if (!a) continue;
  const ring = a.glide_cone.coordinates[0];
  check(a.takeoff.source === "user", "analyze: takeoff.source ≠ user");
  check(a.glide_cone.type === "Polygon" && ring.length >= 4 && ring[0].join() === ring.at(-1).join(), "analyze: cône non fermé");
  check(a.candidates.length <= 8, "analyze: plus de 8 candidats");
  a.candidates.forEach((c) => checkSite("analyze", c.site));
  log(`analyze ${lvl} : ${a.candidates.length} candidats (${a.candidates.map((c) => `${c.kind}/${c.use}`).join(", ")})`);
}
await call("analyze_default_policy", "POST", "/api/landings/analyze", {
  body: { takeoff: pt, horizon: "2h", reference_time: REF, difficulty: "intermediate" },
  type: "LandingAnalyzeResponse",
});

// ── typage des réponses contre src/api/types.ts
const files = Object.entries(manifest).map(([name, type]) => {
  const from = type === "XctskTask" ? join(FRONT, "src/utils/exports") : join(FRONT, "src/api/types");
  const f = join(OUT, "ts", `${name}.ts`);
  const json = readFileSync(join(OUT, `${name}.json`), "utf8");
  writeFileSync(f, `import type { ${type} } from ${JSON.stringify(from)};\nexport const v: ${type} = ${json};\n`);
  return f;
});
writeFileSync(
  join(OUT, "ts", "tsconfig.json"),
  JSON.stringify({ compilerOptions: { target: "ES2022", module: "ESNext", moduleResolution: "bundler", strict: true, noEmit: true, skipLibCheck: true, types: [] }, files }),
);
let typeErrors = [];
try {
  execFileSync(join(FRONT, "node_modules/.bin/tsc"), ["-p", join(OUT, "ts", "tsconfig.json")], { stdio: "pipe", encoding: "utf8" });
} catch (e) {
  const seen = new Set();
  typeErrors = `${e.stdout ?? ""}${e.stderr ?? ""}`
    .split("\n")
    .filter((l) => /error TS/.test(l))
    .map((l) => l.replace(/^.*\/ts\//, "").slice(0, 400))
    .filter((l) => !seen.has(l.replace(/\(\d+,\d+\)/, "")) && seen.add(l.replace(/\(\d+,\d+\)/, "")));
}

log("\n--- durées ---");
for (const [n, ms, st] of timings) log(`${n.padEnd(26)} ${String(st).padStart(4)} ${(ms / 1000).toFixed(2).padStart(6)} s`);
log(`\n--- typage : ${files.length} réponses, ${typeErrors.length} erreur(s) ---`);
typeErrors.forEach((l) => log(" -", l));
log(`--- ${problems.length} problème(s) sémantique(s) ---`);
problems.forEach((p) => log(" -", p));
log(`(réponses enregistrées dans ${OUT})`);
process.exit(typeErrors.length || problems.length ? 1 : 0);
