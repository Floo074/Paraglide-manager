// Parcours de bout en bout contre le VRAI backend (via le proxy /api du serveur Vite).
//
//   cd backend  && DATA_MODE=mock uv run uvicorn app.main:app --port 8014
//   cd frontend && VITE_API_PROXY_TARGET=http://localhost:8014 npx vite --port 5180 --strictPort
//   node e2e/parcours.mjs                      # bureau 1440 px
//   VIEW=mobile node e2e/parcours.mjs          # mobile 375 px
//
// Variables : BASE (http://localhost:5180), LABEL (préfixe des captures), VIEW (desktop | mobile),
// REF (heure de référence locale « AAAA-MM-JJTHH:MM », vide = maintenant), HORIZON (libellé de la puce,
// « 30 min »), POINT (décollage libre « lat,lon »), POLICY (index de la puce d'atterrissage, défaut dernière),
// SHOTS (dossier des captures de contrôle), FINAL (dossier des captures finales : planification-, plan-detail-,
// decollage-libre-{VIEW}.png, plus plan-detail-desktop-complet.png et sources-desktop.png en bureau),
// CHROMIUM (binaire Chromium ; sinon cherché sous PLAYWRIGHT_BROWSERS_PATH ou /opt/pw-browsers).
// Sortie : liste OK / FAIL, appels API (statuts, durées), erreurs console, requêtes échouées.
// Code de retour 1 si une vérification échoue ou si la console contient une erreur.
import { execSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const BASE = process.env.BASE ?? "http://localhost:5180";
const LABEL = process.env.LABEL ?? "e2e";
const VIEW = process.env.VIEW ?? "desktop";
const REF = process.env.REF ?? "";
const HORIZON = process.env.HORIZON ?? "30 min";
const [PLAT, PLON] = (process.env.POINT ?? "45.825,6.269").split(",").map(Number);
const SHOTS = process.env.SHOTS ?? "";
const FINAL = process.env.FINAL ?? "";
const SKIP_FREE = process.env.SKIP_FREE === "1";

/** playwright-core / playwright : dépendance locale, sinon installation globale de npm. */
async function loadChromium() {
  for (const spec of ["playwright-core", "playwright"]) {
    try {
      return (await import(spec)).chromium;
    } catch {
      /* suivant */
    }
  }
  const globalRoot = execSync("npm root -g", { encoding: "utf8" }).trim();
  const req = createRequire(join(globalRoot, "noop.js"));
  for (const spec of ["playwright-core", "playwright"]) {
    try {
      return req(spec).chromium;
    } catch {
      /* suivant */
    }
  }
  throw new Error("playwright introuvable : npm i -D playwright-core (ne pas lancer « playwright install » : Chromium préinstallé)");
}

function chromiumPath() {
  if (process.env.CHROMIUM) return process.env.CHROMIUM;
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/pw-browsers";
  if (!existsSync(root)) return undefined;
  const dirs = readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort().reverse();
  for (const d of dirs) {
    const p = join(root, d, "chrome-linux", "chrome");
    if (existsSync(p)) return p;
  }
  return undefined;
}

const chromium = await loadChromium();
// Relais HTTPS de l'environnement : drapeaux Chromium directs (l'option `proxy` de Playwright ferait
// passer localhost par le relais).
const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
const proxyArgs = proxy ? [`--proxy-server=${proxy}`, "--proxy-bypass-list=localhost;127.0.0.1"] : [];
const browser = await chromium.launch({ executablePath: chromiumPath(), args: ["--no-sandbox", ...proxyArgs] });
const ctxOpts =
  VIEW === "mobile"
    ? { viewport: { width: 375, height: 812 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "fr-FR", timezoneId: "Europe/Paris", acceptDownloads: true }
    : { viewport: { width: 1440, height: 900 }, locale: "fr-FR", timezoneId: "Europe/Paris", acceptDownloads: true };
const context = await browser.newContext(ctxOpts);
const page = await context.newPage();

const errors = [];
const netErrors = []; // « Failed to load resource » : journal du navigateur pour une réponse 4xx/5xx (pas une erreur JS)
const warnings = [];
const api = [];
const failures = [];
const results = [];
const t0 = new Map();
page.on("console", (m) => {
  if (m.type() === "error") (/^Failed to load resource/.test(m.text()) ? netErrors : errors).push(m.text());
  else if (m.type() === "warning") warnings.push(m.text());
});
page.on("pageerror", (e) => errors.push(`PAGEERROR ${e.message}`));
page.on("request", (r) => t0.set(r, Date.now()));
page.on("requestfailed", (r) => {
  if (r.failure()?.errorText === "net::ERR_ABORTED") return; // annulations (AbortController, changement de vue)
  failures.push(`${r.method()} ${r.url().slice(0, 120)} ${r.failure()?.errorText}`);
});
page.on("response", (r) => {
  const u = r.url();
  if (new URL(u).pathname.startsWith("/api/")) api.push({ method: r.request().method(), path: u.replace(BASE, "").slice(0, 110), status: r.status(), ms: Date.now() - (t0.get(r.request()) ?? Date.now()) });
  else if (r.status() >= 400 && !u.startsWith("data:")) failures.push(`HTTP ${r.status()} ${u.slice(0, 100)}`);
});

const ok = (name, cond, detail = "") => {
  results.push(`${cond ? "OK  " : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
  return cond;
};
const note = (name, detail) => results.push(`INFO ${name} — ${detail}`);
const shot = async (name, full = false) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${LABEL}-${VIEW}-${name}.png`, fullPage: full });
};
const clean = (s) => s.replace(/\s+/g, " ").trim();

/** Attend que les tuiles visibles du fond de carte soient chargées. */
async function waitTiles(scope = "", timeout = 25000) {
  const count = () =>
    page.evaluate((scope) => {
      const root = scope ? document.querySelector(scope) : document;
      if (!root) return { loaded: 0, pending: 0 };
      return {
        loaded: root.querySelectorAll(".leaflet-tile-pane img.leaflet-tile-loaded").length,
        pending: root.querySelectorAll(".leaflet-tile-pane img.leaflet-tile:not(.leaflet-tile-loaded)").length,
      };
    }, scope);
  const start = Date.now();
  let s = await count();
  while (Date.now() - start < timeout) {
    if (s.loaded > 0 && s.pending === 0) return s;
    await page.waitForTimeout(300);
    s = await count();
  }
  return s;
}

/** Position écran d'un point lat/lon, déduite d'une tuile chargée (z/x/y dans l'URL) ; zoom de la tuile. */
async function screenPoint(lat, lon) {
  return page.evaluate(
    ({ lat, lon }) => {
      const img = [...document.querySelectorAll(".planner__map .leaflet-tile-pane img.leaflet-tile-loaded")].find((i) => /\/(\d+)\/(\d+)\/(\d+)(\.png)?$/.test(i.src));
      if (!img) return null;
      const m = img.src.match(/\/(\d+)\/(\d+)\/(\d+)(\.png)?$/);
      const z = Number(m[1]);
      const esri = img.src.includes("arcgisonline"); // Esri : z/y/x ; OpenTopoMap / OSM : z/x/y
      const tx = Number(esri ? m[3] : m[2]);
      const ty = Number(esri ? m[2] : m[3]);
      const n = 2 ** z;
      const gx = ((lon + 180) / 360) * n * 256;
      const rad = (lat * Math.PI) / 180;
      const gy = ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * n * 256;
      const r = img.getBoundingClientRect();
      const k = r.width / 256;
      const x = r.left + (gx - tx * 256) * k;
      const y = r.top + (gy - ty * 256) * k;
      const el = document.elementFromPoint(x, y);
      const onMap = !!el?.closest(".leaflet-container") && !el?.closest(".planner__panel, .map-overlay, .map-hint, .leaflet-control");
      return { x, y, z, onMap, marker: !!el?.closest(".leaflet-marker-icon") };
    },
    { lat, lon },
  );
}

async function setSheet(target) {
  if (VIEW !== "mobile") return;
  for (let i = 0; i < 3; i++) {
    const cls = await page.locator(".planner").getAttribute("class");
    if (cls?.includes(`planner--sheet-${target}`)) return;
    await page.locator(".sheet-handle").click();
    await page.waitForTimeout(350);
  }
}

const tStart = Date.now();
const phase = async (name, fn) => {
  try {
    await fn();
  } catch (e) {
    ok(`phase ${name}`, false, String(e.message).split("\n")[0].slice(0, 200));
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/${LABEL}-${VIEW}-ERREUR-${name}.png` }).catch(() => {});
  }
};

// ───────────────────────── 1. Planification classique ─────────────────────────
let planUrl = null;
await phase("classique", async () => {
  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".leaflet-container", { timeout: 20000 });
  await setSheet("half");
  const classic = page.locator(".chips--mode label", { hasText: "Classique" });
  if (await classic.count()) await classic.click();
  await page.getByRole("button", { name: "Annecy", exact: true }).click();
  ok("zone Annecy sélectionnée", (await page.getByRole("button", { name: "Annecy", exact: true }).getAttribute("aria-pressed")) === "true");
  if (REF) {
    await page.locator("details.advanced summary").first().click();
    await page.locator("#ref-time").fill(REF);
    await page.waitForTimeout(200);
    const summary = clean(await page.locator("details.advanced summary").first().innerText());
    ok("heure de référence saisie", !/maintenant/.test(summary), summary);
    await page.locator("details.advanced summary").first().click();
  }
  await page.locator(".chips--horizon label", { hasText: HORIZON }).first().click();
  ok(`horizon ${HORIZON}`, true, clean(await page.locator("#f-horizon .field__aside").innerText()));
  const tiles0 = await waitTiles(".planner__map");
  ok("fond de carte chargé (planification)", tiles0.loaded > 0 && tiles0.pending === 0, `${tiles0.loaded} tuiles`);
  await shot("1-criteres");

  const tSearch = Date.now();
  await page.getByRole("button", { name: /^Trouver les meilleurs vols$/ }).click();
  await page.waitForSelector(".plan-card, .empty, .planner__cta [role=alert]", { timeout: 180000 });
  await page.waitForTimeout(800);
  const searchMs = Date.now() - tSearch;
  const alert = page.locator(".planner__cta [role=alert]");
  if (await alert.count()) ok("recherche sans erreur", false, clean(await alert.innerText()).slice(0, 200));
  const nCards = await page.locator(".plan-card").count();
  const nRejected = await page.locator(".rejected__list > li").count();
  ok("recherche terminée", nCards > 0 || nRejected > 0 || (await page.locator(".empty").count()) > 0, `${nCards} plan(s), ${nRejected} site(s) écarté(s), ${searchMs} ms`);
  if (nCards > 0) {
    const verdicts = await page.locator(".plan-card .verdict-chip, .plan-card [class*=badge--]").allInnerTexts();
    note("cartes de plans", verdicts.slice(0, 6).map(clean).join(" | "));
  } else {
    ok("sites écartés affichés quand aucun plan", (await page.locator("details.rejected").count()) > 0 && nRejected > 0);
    const reason = nRejected ? clean(await page.locator(".rejected__reasons li").first().innerText()) : "";
    if (nRejected) ok("raisons de rejet lisibles", reason.length > 10, reason.slice(0, 160));
  }
  const markers = await page.locator(".planner__map .leaflet-marker-icon").count();
  ok("marqueurs sur la carte", markers > 0, `${markers} marqueurs`);
  await shot("2-resultats");
  if (FINAL && nCards > 0) {
    await waitTiles(".planner__map");
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${FINAL}/planification-${VIEW}.png` });
  }

  // ───────────────────────── 2. Fiche plan ─────────────────────────
  if (nCards === 0) return;
  if (VIEW === "mobile") await setSheet("half");
  await page.locator(".plan-card__title a").first().click();
  await page.waitForSelector(".verdict", { timeout: 30000 });
  planUrl = page.url();
  ok("fiche plan ouverte", /\/plans?\//.test(planUrl), planUrl.replace(BASE, ""));
  ok("titre du plan", true, clean(await page.locator("h1").first().innerText()).slice(0, 100));
  const live = page.locator("section.live-block");
  const hasLive = (await live.count()) > 0;
  ok("bloc « Balises en direct » présent", hasLive);
  if (hasLive) {
    const txt = clean(await live.innerText());
    ok("bloc balises : contenu", txt.length > 40, txt.slice(0, 260));
    const blocks = await page.locator("section.block").evaluateAll((els) => els.map((e) => e.className));
    const idx = blocks.findIndex((c) => c.includes("live-block"));
    const nowcast = /min/.test(HORIZON);
    ok(`bloc balises placé ${nowcast ? "en tête (horizon ≤ 1 h)" : "après le verdict (horizon > 1 h)"}`, nowcast ? idx >= 0 && idx <= 1 : idx > 1, `position ${idx}`);
  }
  const bodyTxt = await page.locator("main").innerText();
  ok("aucun « NaN » / « undefined » / « null » affiché", !/\bNaN\b|\bundefined\b|\bnull\b/.test(bodyTxt), (bodyTxt.match(/.{0,40}\b(NaN|undefined|null)\b.{0,40}/) ?? [""])[0]);
  const tiles = await waitTiles(".block--map");
  ok("carte du plan : fond chargé", tiles.loaded > 0 && tiles.pending === 0, `${tiles.loaded} tuiles`);
  const paths = await page.locator(".block--map path.leaflet-interactive").count();
  ok("carte du plan : route / tracés", paths > 0, `${paths} tracés SVG`);
  const attrib = clean(await page.locator(".block--map .leaflet-control-attribution").innerText().catch(() => ""));
  ok("attribution carte", /OpenStreetMap|OpenTopoMap/.test(attrib), attrib.slice(0, 160));
  await shot("3-plan");
  if (FINAL) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${FINAL}/plan-detail-${VIEW}.png` });
    if (VIEW === "desktop") {
      // fiche complète : tous les blocs dans l'ordre (verdict, balises, créneau, vent, aérologie…)
      await page.evaluate(async () => {
        for (let y = 0; y < document.body.scrollHeight; y += 600) {
          window.scrollTo(0, y);
          await new Promise((r) => setTimeout(r, 120));
        }
        window.scrollTo(0, 0);
      });
      await waitTiles(".block--map");
      await page.waitForTimeout(600);
      await page.screenshot({ path: `${FINAL}/plan-detail-${VIEW}-complet.png`, fullPage: true });
    }
  }
  // couches de la carte du plan
  const layersBtn = page.locator(".block--map").getByRole("button", { name: "Couches de la carte" });
  await layersBtn.scrollIntoViewIfNeeded();
  await layersBtn.click();
  const panel = page.locator(".block--map .layers-menu__panel");
  const labels = await panel.locator("label.check").allInnerTexts();
  ok("menu des couches", labels.length >= 5, labels.map((l) => l.trim().split("\n")[0]).join(" | "));
  for (const name of ["Espaces aériens", "Zones sensibles (faune, parcs)", "Balises (celles du plan entourées)", "Rayons de plané vers les atterros"]) {
    const box = panel.locator("label.check", { hasText: name }).locator("input");
    if (!(await box.count())) {
      ok(`couche ${name}`, false, "absente");
      continue;
    }
    const before = await box.isChecked();
    await box.click();
    await page.waitForTimeout(600);
    await box.click();
    await page.waitForTimeout(600);
    ok(`couche ${name} (bascule)`, (await box.isChecked()) === before);
  }
  const cand = panel.locator("label.check", { hasText: "Autres atterros évalués" }).locator("input");
  if ((await cand.count()) && !(await cand.isDisabled())) {
    if (!(await cand.isChecked())) await cand.click();
    await page.waitForTimeout(500);
    ok("couche « Autres atterros évalués »", true, `${await page.locator(".block--map .leaflet-marker-icon").count()} marqueurs`);
    await cand.click();
  }
  await panel.locator("label.check", { hasText: "Satellite" }).locator("input").click();
  const ts = await waitTiles(".block--map");
  ok("fond satellite chargé", ts.loaded > 0 && ts.pending === 0, `${ts.loaded} tuiles`);
  await panel.locator("label.check", { hasText: "Relief" }).locator("input").click();
  await waitTiles(".block--map");
  await layersBtn.click();
  // analyse des atterrissages
  const la = page.getByRole("heading", { name: /Analyse des atterrissages/ });
  ok("section « Analyse des atterrissages »", (await la.count()) > 0, `${await page.locator(".lc-card").count()} fiche(s)`);
  // exports
  for (const [btn, kind] of [
    ["GPX", "gpx"],
    ["Tâche XCTrack", "xctsk"],
  ]) {
    const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 20000 }), page.getByRole("button", { name: btn }).click()]);
    const content = readFileSync(await dl.path(), "utf8");
    if (kind === "gpx") ok("export GPX téléchargé", content.includes("<gpx") && content.includes('version="1.1"') && content.includes("<rte"), `${dl.suggestedFilename()} ${content.length} o`);
    else {
      let j = null;
      try {
        j = JSON.parse(content);
      } catch {
        /* invalide */
      }
      ok("export XCTrack téléchargé", !!j && j.taskType === "CLASSIC" && j.turnpoints?.[0]?.type === "TAKEOFF" && j.turnpoints.at(-1)?.type === "ESS", `${dl.suggestedFilename()} ${j?.turnpoints?.length} balises`);
    }
  }
  // actualiser les balises (relance POST /api/plans)
  const refresh = page.getByRole("button", { name: /Actualiser les balises/ });
  if (await refresh.count()) {
    const tR = Date.now();
    await refresh.click();
    await page.waitForFunction(() => !document.body.innerText.includes("Actualisation…"), null, { timeout: 180000 });
    await page.waitForTimeout(800);
    const still = (await page.locator(".verdict").count()) > 0 || (await page.locator(".plan-card, .empty").count()) > 0;
    ok("« Actualiser les balises »", still, `${Date.now() - tR} ms → ${page.url().replace(BASE, "")}`);
  }
  // rechargement direct de l'URL (GET /api/plans/{id})
  await page.goto(planUrl, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".verdict", { timeout: 30000 });
  ok("rechargement de la fiche (GET /plans/{id})", true);
});

// ───────────────────────── 3. Décollage libre ─────────────────────────
if (!SKIP_FREE)
  await phase("libre", async () => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".leaflet-container", { timeout: 20000 });
    await setSheet("half");
    await page.locator(".tabs [role=tab]", { hasText: "Critères" }).click();
    await page.locator(".chips--mode label", { hasText: "Décollage libre" }).click();
    await page.waitForTimeout(500);
    ok("mode décollage libre", (await page.getByRole("heading", { name: /Point de décollage/ }).count()) > 0);
    ok("avertissement permanent décollage libre", /décollage libre/i.test(await page.locator(".planner__panel").innerText()));
    const pick = page.locator(".planner__panel").getByRole("button", { name: /Poser sur la carte|Touche la carte|Reposer sur la carte/ });
    if ((await pick.getAttribute("aria-pressed")) !== "true") await pick.click();
    ok("mode pose du déco armé", (await pick.getAttribute("aria-pressed")) === "true");
    await setSheet("peek");
    await waitTiles(".planner__map");
    const hint = page.locator(".map-hint");
    if (await hint.count()) {
      const fits = await hint.evaluate((el) => el.scrollWidth <= el.clientWidth + 1);
      ok("bandeau « Touche la carte… » lisible (non tronqué)", fits, clean(await hint.innerText()));
    }
    // zoom à la molette centré sur le point (le point reste sous le curseur)
    let sp = await screenPoint(PLAT, PLON);
    for (let i = 0; i < 6 && sp?.onMap && sp.z < 13; i++) {
      await page.mouse.move(sp.x, sp.y);
      await page.mouse.wheel(0, -240);
      await page.waitForTimeout(900);
      await waitTiles(".planner__map", 8000);
      sp = await screenPoint(PLAT, PLON);
    }
    ok("point de décollage visible sur la carte", !!sp?.onMap, sp ? `${Math.round(sp.x)},${Math.round(sp.y)} z${sp.z}${sp.marker ? " (sous un marqueur)" : ""}` : "aucune tuile");
    if (!sp?.onMap) return;
    await page.mouse.click(sp.x, sp.y);
    await page.waitForTimeout(600);
    await setSheet("half");
    const coords = clean(await page.locator("#f-free .field__aside").innerText().catch(() => ""));
    ok("déco posé par clic", coords.length > 0, coords || "aucun point (clic intercepté ?)");
    if (!coords) return;
    await page.getByRole("textbox", { name: /Nom/ }).fill("Point E2E").catch(() => {});
    const policies = page.locator("[aria-label='Atterrissages acceptés'] label");
    const pIdx = process.env.POLICY ? Number(process.env.POLICY) : (await policies.count()) - 1;
    await policies.nth(pIdx).click();
    const tA = Date.now();
    await page.getByRole("button", { name: /Analyser les atterrissages/ }).click();
    await page.waitForFunction(() => !document.body.innerText.includes("Analyse en cours…"), null, { timeout: 180000 });
    await page.waitForTimeout(800);
    let err = await page.locator(".planner__panel .field__error").allInnerTexts();
    if (err.some((e) => /altitude/i.test(e))) {
      // relief indisponible (MNT en panne / quota) : le pilote saisit l'altitude et relance
      ok("message « relief indisponible » compréhensible", !err.join(" ").includes("elevation_m"), err.join(" / ").slice(0, 200));
      await page.getByRole("spinbutton", { name: /Altitude/ }).fill(process.env.ALT ?? "1500");
      await page.getByRole("button", { name: /Analyser les atterrissages/ }).click();
      await page.waitForFunction(() => !document.body.innerText.includes("Analyse en cours…"), null, { timeout: 180000 });
      await page.waitForTimeout(800);
      err = await page.locator(".planner__panel .field__error").allInnerTexts();
    }
    const nLc = await page.locator(".lc-card").count();
    ok("analyse des atterrissages", nLc > 0 || err.length > 0, `${nLc} candidat(s), ${Date.now() - tA} ms${err.length ? ` — erreur : ${err.join(" / ").slice(0, 200)}` : ""}`);
    if (nLc) {
      const cone = await page.locator(".planner__map path.leaflet-interactive").count();
      ok("cône de finesse / tracés sur la carte", cone > 0, `${cone} tracés`);
      ok("fiche candidat", true, clean(await page.locator(".lc-card").first().innerText()).slice(0, 220));
      const warn = clean(await page.locator(".planner__scroll").innerText());
      ok("avertissement dans l'onglet Atterros", /Atterrissages non officiels/.test(warn));
    }
    await shot("4-libre-analyse");
    if (FINAL && nLc) {
      await waitTiles(".planner__map");
      await page.waitForTimeout(600);
      await page.screenshot({ path: `${FINAL}/decollage-libre-${VIEW}.png` });
    }
    await page.locator(".tabs [role=tab]", { hasText: "Critères" }).click();
    const tF = Date.now();
    await page.getByRole("button", { name: /Trouver les meilleurs vols depuis ce point/ }).click();
    await page.waitForSelector(".plan-card, .empty, .planner__cta [role=alert]", { timeout: 180000 });
    await page.waitForTimeout(800);
    const nF = await page.locator(".plan-card").count();
    const rj = await page.locator(".rejected__reasons li").allInnerTexts();
    const cta = await page.locator(".planner__cta [role=alert]").allInnerTexts();
    ok("recherche depuis le décollage libre", cta.length === 0, `${nF} plan(s), ${Date.now() - tF} ms${nF ? "" : ` — rejet : ${rj.slice(0, 2).map(clean).join(" / ").slice(0, 260)}`}${cta.length ? ` — erreur : ${cta.join(" ")}` : ""}`);
    await shot("5-libre-resultats");
    if (nF) {
      await page.locator(".plan-card__title a").first().click();
      await page.waitForSelector(".verdict", { timeout: 30000 });
      const txt = clean(await page.locator("main").innerText());
      ok("fiche plan décollage libre", /décollage libre/i.test(txt), clean(await page.locator("h1").first().innerText()).slice(0, 100));
      await shot("6-libre-plan");
    }
  });

// ───────────────────────── 4. Page Sources ─────────────────────────
await phase("sources", async () => {
  await page.goto(`${BASE}/sources`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".source", { timeout: 20000 });
  await page.waitForTimeout(500);
  const n = await page.locator(".source").count();
  ok("page Sources", n >= 8, `${n} sources listées`);
  if (FINAL && VIEW === "desktop") await page.screenshot({ path: `${FINAL}/sources-${VIEW}.png`, fullPage: true });
});
await browser.close();

console.log(`\n=== Parcours ${LABEL} / ${VIEW} (${Math.round((Date.now() - tStart) / 1000)} s) ===`);
console.log(results.join("\n"));
console.log(`\n--- appels API (${api.length}) ---`);
const byPath = new Map();
for (const a of api) {
  const k = `${a.method} ${a.path.split("?")[0]}`;
  const e = byPath.get(k) ?? { n: 0, max: 0, st: new Set() };
  e.n++;
  e.max = Math.max(e.max, a.ms);
  e.st.add(a.status);
  byPath.set(k, e);
}
for (const [k, e] of byPath) console.log(`${k.padEnd(48)} ×${e.n} max ${e.max} ms statuts ${[...e.st].join(",")}`);
console.log(`\n--- erreurs console JS (${errors.length}) ---\n${errors.join("\n")}`);
console.log(`--- réponses HTTP en erreur journalisées par le navigateur (${netErrors.length}) ---\n${[...new Set(netErrors)].join("\n")}`);
console.log(`--- avertissements console (${warnings.length}) ---\n${[...new Set(warnings)].slice(0, 15).join("\n")}`);
console.log(`--- requêtes échouées (${failures.length}) ---\n${[...new Set(failures)].slice(0, 20).join("\n")}`);
const failed = results.some((r) => r.startsWith("FAIL")) || errors.length > 0;
process.exit(failed ? 1 : 0);
