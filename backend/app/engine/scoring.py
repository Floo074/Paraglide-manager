"""Score pondéré non compensatoire, confiance et verdict (cahier des charges §8.2, §9)."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from app.engine import rules
from app.engine.findings import Finding, ratio_subscore
from app.meteo.ensemble import circular_std_deg
from app.models import Risk, ScoreItem

CRITERION_LABEL_FR = {
    "takeoff_wind": "Vent au décollage",
    "wind_aloft": "Vent en altitude",
    "landing": "Atterrissage et finesse",
    "thermal_match": "Thermiques vs préférence",
    "duration_match": "Adéquation de la durée",
    "convective_stability": "Stabilité convective",
    "data_confidence": "Confiance des données",
    "site_fit": "Adéquation du site",
    "airspace": "Espaces aériens (informatif)",
}
# Code de risque utilisé pour expliquer un critère faible quand aucun risque ne l'explique déjà (I2)
CRITERION_RISK_CODE = {
    "takeoff_wind": "TAKEOFF_WIND",
    "wind_aloft": "STRONG_WIND_ALOFT",
    "landing": "LANDING_WIND",
    "thermal_match": "WEAK_THERMALS",
    "duration_match": "WEAK_THERMALS",
    "convective_stability": "OVERDEVELOPMENT",
    "data_confidence": "LOW_CONFIDENCE",
    "site_fit": "SITE_LEVEL",
    "airspace": "AIRSPACE",
}


def glide_subscore(r: float) -> float:
    pts = rules.GLIDE_RATIO_SUBSCORE
    if r <= pts[0][0]:
        return pts[0][1]
    for (r0, s0), (r1, s1) in zip(pts, pts[1:], strict=False):
        if r <= r1:
            return s0 + (s1 - s0) * (r - r0) / (r1 - r0)
    return 0.0


def linear(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    if x1 == x0:
        return y1
    t = max(0.0, min(1.0, (x - x0) / (x1 - x0)))
    return y0 + t * (y1 - y0)


def confidence_factors(
    model_winds: list[tuple[str, float, float]], nowcast_coherent: bool | None
) -> tuple[float, float, float, float]:
    """(facteur dispersion, facteur balises, σ vitesse, σ direction)."""
    disp = 1.0
    sig_v = sig_d = 0.0
    if len(model_winds) >= 2:
        speeds = [v for _, v, _ in model_winds]
        dirs = [d for _, v, d in model_winds if v >= rules.CALM_WIND_KMH]
        sig_v = statistics.pstdev(speeds)
        lo, hi = rules.DISPERSION_SPEED_SIGMA_KMH
        if sig_v > lo:
            disp = 1.0 - (1.0 - rules.DISPERSION_SPEED_FACTOR_AT_MAX) * (sig_v - lo) / (hi - lo)
            disp = max(0.35, disp)
        if len(dirs) >= 2:
            sig_d = circular_std_deg(dirs)
            if sig_d > rules.DISPERSION_DIR_SIGMA_DEG:
                disp *= rules.DISPERSION_DIR_FACTOR
    beacon = 1.0
    if nowcast_coherent is True:
        beacon = rules.BEACON_COHERENT_FACTOR
    elif nowcast_coherent is False:
        beacon = rules.BEACON_CONTRADICTORY_FACTOR
    return disp, beacon, sig_v, sig_d


def compute_confidence(horizon: str, disp: float, beacon: float) -> float:
    base = rules.HORIZON_BASE_CONFIDENCE[horizon]
    conf = base * disp * beacon
    return round(min(conf, rules.CONFIDENCE_MAX, base * 1.1), 3)


@dataclass
class ScoreResult:
    score: float
    items: list[ScoreItem]
    subscores: dict[str, float]
    weakest_safety: str


def thermal_match_subscore(pref: str, vario: float, thermal_used: bool, level: str) -> tuple[float, str]:
    thr = rules.THERMAL_MAX_MS[level]
    if pref == "required":
        lo = rules.THERMAL_IDEAL_MIN_MS
        hi = max(lo, thr - 0.5)
        if lo <= vario <= hi:
            return 100.0, f"vario {vario:.1f} m/s idéal pour ton niveau"
        if vario < lo:
            return linear(vario, rules.REQUIRED_THERMAL_MIN_MS, 40, lo, 100), f"thermiques un peu faibles ({vario:.1f} m/s)"
        return linear(vario, hi, 100, thr, 40), f"thermiques forts pour ton niveau ({vario:.1f} m/s)"
    if pref == "avoid":
        if vario <= 0.5:
            return 100.0, "air calme, conforme à ta préférence"
        return linear(vario, 0.5, 100, rules.AVOID_THERMAL_MAX_MS, 50), f"quelques thermiques ({vario:.1f} m/s)"
    # allowed
    if vario < rules.THERMAL_USABLE_MIN_MS:
        return rules.ALLOWED_NO_THERMAL_SUBSCORE, "pas de thermique exploitable (neutre)"
    s = min(100.0, ratio_subscore(vario / thr) + (10 if thermal_used else 0))
    return s, f"thermiques {vario:.1f} m/s ({'exploités' if thermal_used else 'non nécessaires'})"


def duration_subscore(est: float, dmin: float, dmax: float) -> tuple[float, str]:
    if dmin <= est <= dmax:
        return 100.0, f"{est:.0f} min dans la plage demandée ({dmin:.0f}-{dmax:.0f} min)"
    ref = dmin if est < dmin else dmax
    dev = abs(est - ref) / max(ref, 1.0)
    return max(0.0, 100.0 - dev * 200.0), f"{est:.0f} min pour {dmin:.0f}-{dmax:.0f} min demandées"


def aggregate_score(
    level: str,
    findings: list[Finding],
    extra: dict[str, tuple[float, str]],
) -> ScoreResult:
    """Sous-scores = min des constats de chaque critère (seuils du niveau) + critères calculés à part."""
    subs: dict[str, float] = {}
    comments: dict[str, str] = {}
    for f in findings:
        if f.criterion is None:
            continue
        s = f.subscore(level)
        if s is None:
            continue
        if f.criterion not in subs or s < subs[f.criterion]:
            subs[f.criterion] = s
            comments[f.criterion] = f.title
    for crit, (s, c) in extra.items():
        if crit not in subs or s < subs[crit]:
            subs[crit] = s
            comments[crit] = c
    items: list[ScoreItem] = []
    total = wsum = 0.0
    for crit, w in rules.WEIGHTS.items():
        s = subs.get(crit, 100.0)
        subs[crit] = s
        items.append(
            ScoreItem(criterion=crit, score=round(s, 1), weight=float(w), comment=comments.get(crit, "RAS"))
        )
        total += w * s
        wsum += w
    if "airspace" in extra:
        s, c = extra["airspace"]
        items.append(ScoreItem(criterion="airspace", score=round(s, 1), weight=0.0, comment=c))
    score = total / wsum if wsum else 0.0
    safety = {c: subs[c] for c in rules.SAFETY_CRITERIA}
    weakest = min(safety, key=lambda c: safety[c])
    score = min(score, rules.SAFETY_CAP_OFFSET + safety[weakest])
    return ScoreResult(round(score, 1), items, subs, weakest)


def verdict(
    score: ScoreResult,
    risks: list[Risk],
    blocking_cautions: bool,
    conf_raw: float,
    horizon: str,
) -> str:
    if any(r.level == "danger" for r in risks):
        return "no_go"
    if score.score < rules.VERDICT["nogo_max_score"]:
        return "no_go"
    base = rules.HORIZON_BASE_CONFIDENCE[horizon]
    safety_ok = all(score.subscores[c] >= rules.VERDICT["go_min_safety_subscore"] for c in rules.SAFETY_CRITERIA)
    conf_ok = conf_raw >= rules.VERDICT["go_min_confidence_ratio"] * base - 1e-9
    if score.score >= rules.VERDICT["go_min_score"] and safety_ok and conf_ok and not blocking_cautions:
        return "go"
    return "marginal"


def round_conf(x: float) -> float:
    return math.floor(x * 100 + 0.5) / 100
