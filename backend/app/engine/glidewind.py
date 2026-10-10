"""Vent sur le plané et paramètres du plané final (cahier des charges §14, révision 5).

- Vent RENCONTRÉ (§14.1) : colonne verticale entre le point de départ et l'atterro, à l'heure où le pilote traverse
  chaque tranche. Dans les 300 m du bas : vent retenu à l'atterro À L'HEURE D'ARRIVÉE (brise de vallée, balise,
  tendance) ; dans les 100 m sous le déco : vent retenu au déco (balise comprise) ; entre les deux : interpolation
  linéaire en (u, v) ; au-dessus de l'altitude du déco : profil du modèle au déco. La colonne est linéaire par
  morceaux : la moyenne sur une tranche (au prorata de l'épaisseur, = tranches de 50 m de poids égal) est exacte.
- Par branche (contournements compris) : la hauteur à perdre est répartie au prorata des longueurs ; vent moyen de la
  tranche traversée, projeté sur le cap de la branche (w∥ arrière > 0, w⊥ travers).
- Crédit (§14.2) : vent arrière crédité en partie (c = base du niveau + bonus − malus, nul si vent faible ou prévision
  peu fiable), plafonné par niveau ; vent de face compté en entier et majoré par les rafales (g ≤ 1,2) ; travers
  toujours payé : V_sol = √(V² − w⊥²) + w∥ retenu.
- Vitesse (§14.3) : polaire simplifiée par catégorie d'aile ; vitesse ∈ [bras hauts ; V_max(niveau)] qui maximise la
  finesse sol (jamais d'accélérateur pour l'élève ; bras hauts si l'air est trop rafaleux).
- Finesse du plané = L / Σ (L_i / f_i), f_i = wing × k × ρ(V) × V_sol / V × f(kind) ; hauteur d'arrivée attendue
  (§14.4) = z0 − alt_atterro − Σ L_i / (wing × 0,90 × ρ(V) × V_sol(vent prévu à 100 %) / V).

Une seule fonction de calcul (`compute_glide`) sert partout : plan principal, secours, analyse des atterrissages,
points de décision, cône du cross, cône de finesse (vent uniforme) et décollage libre.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Protocol

from app.engine import rules
from app.engine.conditions import (
    LandingWind,
    TakeoffWind,
    dir_label,
    landing_wind,
    legal_time,
    sun_times,
    takeoff_wind,
)
from app.engine.context import DataContext, PointTimeline
from app.engine.scoring import compute_confidence, confidence_factors
from app.engine.stations import StationNowcast, landing_confidence_factor, trend_findings
from app.geo import angle_diff, bearing_deg, destination, haversine_km, wind_components, wind_from_components
from app.models import Site

if TYPE_CHECKING:  # pragma: no cover
    from app.engine.routing import GlideCheck

LEVELS = rules.LEVELS
UV4 = tuple[float, float, float, float]  # (u, v) vent retenu, (u, v) vent fusionné (sans extrapolation de tendance)


# =============================================================================================
# Prévision d'un atterro (déplacé de landings.py : utilisé aussi par la colonne de vent)
# =============================================================================================
def big_valley(ctx: DataContext, landing: Site) -> bool:
    """Atterro en grande vallée (brise × 1,3, §4.3) : méta du site, sinon relief ≥ 2000 m à moins de 10 km."""
    meta = ctx.site_meta.get(landing.id)
    if meta and meta.big_valley is not None:
        return meta.big_valley
    if landing.elevation_m >= rules.BIG_VALLEY_MAX_FLOOR_M:
        return False
    if ctx.terrain is not None:
        for brg in range(0, 360, 30):
            for r in (5.0, rules.BIG_VALLEY_RADIUS_KM):
                la, lo = destination(landing.lat, landing.lon, brg, r)
                e = ctx.terrain_at(la, lo)
                if e is not None and e >= rules.BIG_VALLEY_MIN_RELIEF_M:
                    return True
        return False
    return any(
        s.elevation_m > rules.BIG_VALLEY_FALLBACK_TAKEOFF_M
        and haversine_km(s.lat, s.lon, landing.lat, landing.lon) <= rules.BIG_VALLEY_FALLBACK_RADIUS_KM
        for s in ctx.takeoffs
    )


def timeline_for(ctx: DataContext, site: Site, fallback: PointTimeline | None = None) -> PointTimeline | None:
    """Prévision du terrain : la sienne, sinon celle du point de prévision d'atterro le plus proche, sinon
    `fallback`."""
    tl = ctx.timelines.get(site.id)
    if tl is not None:
        return tl
    others = [(haversine_km(site.lat, site.lon, t.lat, t.lon), t) for k, t in ctx.timelines.items()
              if k in ctx.landings and t.hours]  # fmt: skip
    if others:
        return min(others, key=lambda x: x[0])[1]
    return fallback


def quarter(t: datetime) -> datetime:
    """Heure arrondie au quart d'heure le plus proche (clé de cache des ETA d'une route)."""
    t = t.replace(second=0, microsecond=0)
    m = round(t.minute / 15.0) * 15
    return t.replace(minute=0) + timedelta(minutes=m)


def plouf_minutes(drop_m: float) -> float:
    """Durée d'un plané de `drop_m` mètres (§6 : 1,2 m/s + 3 min) ; sert aussi à l'heure d'arrivée d'un plané."""
    return max(0.0, drop_m) / (rules.SINK_RATE_MS["calm"] * 60.0) + rules.PLOUF_EXTRA_MIN


# =============================================================================================
# Confiance de la prévision (§8.2, §12.4) — partagée avec planner.finalize
# =============================================================================================
@dataclass(slots=True)
class ConfidenceInfo:
    raw: float
    disp: float
    beacon: float
    f_landing: float
    sig_v: float
    sig_d: float
    single_model: bool


def forecast_confidence(
    ctx: DataContext,
    tl: PointTimeline,
    t: datetime,
    tw_nc: StationNowcast | None,
    lw_nc: StationNowcast | None,
    top_landing: bool,
) -> ConfidenceInfo:
    """Confiance brute = base(horizon) × dispersion des modèles × balise du déco × balise de l'atterro."""
    model_winds = (
        tl.model_winds.get(min(tl.model_winds, key=lambda x: abs((x - t).total_seconds()))) if tl.model_winds else []
    )
    rep_to = tw_nc is not None and tw_nc.has_representative
    coherent = None if not rep_to else (True if tw_nc.coherent else (False if tw_nc.mismatch else None))
    disp, beacon, sig_v, sig_d = confidence_factors(model_winds or [], coherent)
    single_model = tl.mode == "live" and bool(tl.model_winds) and not ctx.exact_inputs and len(model_winds or []) < 2
    if single_model:  # revue (m) : en bout d'échéance, un seul modèle couvre l'heure → pas de contrôle croisé
        disp *= rules.SINGLE_MODEL_CONFIDENCE_FACTOR
    f_ldg = 1.0 if top_landing else landing_confidence_factor(ctx, lw_nc)
    raw = compute_confidence(ctx.horizon, disp, beacon, f_ldg)
    return ConfidenceInfo(raw, disp, beacon, f_ldg, sig_v, sig_d, single_model)


# =============================================================================================
# Polaire simplifiée et accélérateur (§14.3)
# =============================================================================================
def polar(wing: float) -> dict:
    return rules.WING_POLAR[rules.wing_class(wing)]


def rho(wing: float, v: float) -> float:
    """finesse(V) / finesse bras hauts, linéaire par morceaux (bras hauts → demi-barreau → à fond)."""
    p = polar(wing)
    vt, vh, rh, vm, rm = p["trim_kmh"], p["half_bar_kmh"], p["rho_half"], p["full_bar_kmh"], p["rho_full"]
    if v <= vt:
        return 1.0
    if v <= vh:
        return 1.0 + (rh - 1.0) * (v - vt) / (vh - vt)
    return rh + (rm - rh) * (min(v, vm) - vh) / (vm - vh)


def max_speed(wing: float, level: str, bar_allowed: bool = True) -> float:
    """Vitesse max comptée : bras hauts (élève, air rafaleux), demi-barreau (brevet de pilote), à fond au-delà."""
    p = polar(wing)
    vt, vh, vm = float(p["trim_kmh"]), float(p["half_bar_kmh"]), float(p["full_bar_kmh"])
    a = rules.SPEED_BAR_MAX_FRACTION[level] if bar_allowed else 0.0
    if a <= 0:
        return vt
    if a <= 0.5:
        return vt + (vh - vt) * a / 0.5
    return vh + (vm - vh) * (a - 0.5) / 0.5


def bar_label(wing: float, v: float) -> str:
    """Course d'accélérateur correspondant à la vitesse air V (texte pilote)."""
    p = polar(wing)
    vt, vh, vm = p["trim_kmh"], p["half_bar_kmh"], p["full_bar_kmh"]
    if v <= vt + 0.25:
        return "bras hauts"
    if v < vh - 1.0:
        return "un peu d'accélérateur"
    if v <= vh + 1.0:
        return "demi-barreau"
    if v < vm - 1.0:
        return "accélérateur aux trois quarts"
    return "accélérateur à fond"


# =============================================================================================
# Colonne de vent (§14.1)
# =============================================================================================
@dataclass(slots=True)
class WindColumn:
    """Vent en fonction de l'altitude, linéaire par morceaux en (u, v) (valeurs constantes au-delà des extrémités).
    Deux jeux : vent retenu (balises + tendance « jamais à la baisse ») et vent fusionné (balises, sans tendance)."""

    zs: list[float]
    vals: list[UV4]

    @classmethod
    def uniform(cls, speed: float, direction: float) -> WindColumn:
        u, v = wind_components(speed, direction)
        return cls([0.0], [(u, v, u, v)])

    def at(self, z: float) -> UV4:
        zs = self.zs
        if z <= zs[0]:
            return self.vals[0]
        if z >= zs[-1]:
            return self.vals[-1]
        i = bisect.bisect_right(zs, z)
        z0, z1 = zs[i - 1], zs[i]
        a, b = self.vals[i - 1], self.vals[i]
        f = (z - z0) / (z1 - z0) if z1 > z0 else 0.0
        return (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2]), a[3] + f * (b[3] - a[3]))

    def mean(self, z_lo: float, z_hi: float) -> UV4:
        """Moyenne exacte sur [z_lo, z_hi] (chaque mètre d'épaisseur pèse autant : temps passé à taux de chute
        constant)."""
        if z_hi < z_lo:
            z_lo, z_hi = z_hi, z_lo
        if z_hi - z_lo < 1.0:
            return self.at(0.5 * (z_lo + z_hi))
        knots = [z_lo, *[z for z in self.zs if z_lo < z < z_hi], z_hi]
        acc = [0.0, 0.0, 0.0, 0.0]
        prev = self.at(knots[0])
        for za, zb in pairwise(knots):
            cur = self.at(zb)
            w = 0.5 * (zb - za)
            for k in range(4):
                acc[k] += (prev[k] + cur[k]) * w
            prev = cur
        span = z_hi - z_lo
        return acc[0] / span, acc[1] / span, acc[2] / span, acc[3] / span


def _uv4(speed: float, direction: float, fused_speed: float | None = None) -> UV4:
    u, v = wind_components(speed, direction)
    if fused_speed is None:
        return u, v, u, v
    uf, vf = wind_components(fused_speed, direction)
    return u, v, uf, vf


def build_column(
    z_deco: float,
    z_landing: float,
    takeoff_anchor: UV4,
    landing_anchor: UV4,
    profile_points: list[tuple[float, float, float]] | None,
) -> WindColumn:
    """Colonne du §14.1 : vent d'atterro sous alt_atterro + 300 m, vent du déco dans les 100 m sous le déco,
    interpolation (u, v) entre les deux, profil modèle au-dessus du déco. Dénivelé < 400 m : les deux couches se
    partagent la tranche commune à mi-hauteur."""
    gw = rules.GLIDE_WIND
    b1 = z_landing + float(gw["breeze_layer_agl_m"])
    b2 = z_deco - float(gw["takeoff_layer_m"])
    if b1 > b2:
        b1 = b2 = max(z_landing, min(z_deco, 0.5 * (b1 + b2)))
    zs: list[float] = [b1]
    vals: list[UV4] = [landing_anchor]
    top_t = max(b2, b1 + 1.0)
    zs.append(top_t)
    vals.append(takeoff_anchor)
    if z_deco > top_t + 1e-6:
        zs.append(z_deco)
        vals.append(takeoff_anchor)
    if profile_points:
        above = [p for p in profile_points if p[0] > zs[-1] + 1.0]
        if above:
            # premier point juste au-dessus du déco : vent du profil à cette altitude (interpolé)
            z1 = zs[-1] + 1.0
            pz = [p[0] for p in profile_points]
            if z1 <= pz[0]:
                u1, v1 = profile_points[0][1], profile_points[0][2]
            else:
                i = bisect.bisect_right(pz, z1)
                za, ua, va = profile_points[i - 1]
                zb, ub, vb = profile_points[min(i, len(profile_points) - 1)]
                f = 0.0 if zb == za else (z1 - za) / (zb - za)
                u1, v1 = ua + f * (ub - ua), va + f * (vb - va)
            zs.append(z1)
            vals.append((u1, v1, u1, v1))
            for z, u, v in above:
                if z > zs[-1] + 1e-6:
                    zs.append(z)
                    vals.append((u, v, u, v))
    return WindColumn(zs, vals)


# =============================================================================================
# Crédit du vent arrière, majoration de la face (§14.2)
# =============================================================================================
@dataclass(slots=True)
class CreditParams:
    """Éléments (indépendants du niveau) qui fixent la part de vent arrière créditée sur un plané."""

    horizon_malus: float = 0.0
    beacon_confirms: bool = False
    established_breeze: bool = False
    gust_ratio: float = 1.0  # plus fort rapport rafale / moyenne (vent ≥ 10 km/h), déco et atterro
    evening: bool = False
    zero_reasons: tuple[str, ...] = ()
    gust_spread_kmh: float = 0.0  # plus fort écart rafale − moyenne, déco et atterro (accélérateur)

    def fraction(self, level: str) -> float:
        c = rules.GLIDE_TAIL_CREDIT
        if self.zero_reasons:
            return 0.0
        f = float(c["base"][level]) - self.horizon_malus
        if self.beacon_confirms:
            f += c["bonus"]["beacon_confirms"]
        if self.established_breeze:
            f += c["bonus"]["established_breeze"]
        gm = c["malus"]["gust_factor"]
        if self.gust_ratio > gm["over"]:
            f -= gm["malus"]
        if self.evening:
            f -= c["malus"]["evening_transition"]["malus"]
        lo, hi = c["bounds"]
        return max(lo, min(hi, f))

    @property
    def headwind_factor(self) -> float:
        h = rules.GLIDE_HEADWIND_GUST
        return max(1.0, min(h["max"], 1.0 + h["factor"] * (self.gust_ratio - 1.0)))

    def bar_allowed(self, level: str) -> bool:
        return (
            rules.SPEED_BAR_MAX_FRACTION[level] > 0
            and self.gust_spread_kmh <= rules.SPEED_BAR_MAX_GUST_SPREAD_KMH[level] + 1e-9
        )


def _gust_stats(winds: list[tuple[float, float]]) -> tuple[float, float]:
    """(plus fort rapport rafale / moyenne pour un vent ≥ 10 km/h, plus fort écart rafale − moyenne)."""
    gm = rules.GLIDE_TAIL_CREDIT["malus"]["gust_factor"]["min_wind_kmh"]
    ratio = max([g / v for v, g in winds if v >= gm] or [1.0])
    spread = max([max(0.0, g - v) for v, g in winds] or [0.0])
    return ratio, spread


# =============================================================================================
# Calcul du plané (§14.1-14.4)
# =============================================================================================
@dataclass(slots=True)
class GlideWind:
    """Vent et vitesses sur un plané (les finesses sont × f du kind ; la finesse attendue ne l'est pas)."""

    available: float  # L / Σ (L_i / f_i) ; 0 si une branche est infranchissable
    calm: float  # wing × k × f
    expected: float  # finesse attendue : vent prévu à 100 %, wing × 0,90 × ρ(V)
    expected_loss_m: float  # Σ L_i / finesse attendue_i (m) ; inf si une branche est infranchissable
    along_kmh: float  # composante BRUTE moyenne (pondérée par les longueurs), + = arrière
    cross_kmh: float  # travers moyen (valeur absolue)
    credit_kmh: float  # composante RETENUE moyenne (crédit partiel, face × g)
    mean_speed_kmh: float  # vent moyen rencontré (moyenne vectorielle des branches)
    mean_dir_deg: float
    air_speed_kmh: float  # vitesse air retenue (branche la plus longue)
    trim_kmh: float
    ground_speed_kmh: float  # vitesse sol (vent retenu) sur la branche la plus longue
    min_ground_kmh: float  # vitesse sol la plus faible des branches
    penetration_min_kmh: float  # minimum du niveau (§14.2)
    gust_factor: float  # g (majoration de la face)
    credit_fraction: float  # c (part du vent arrière créditée)
    bar_allowed: bool  # course d'accélérateur comptée à ce niveau dans cet air
    leg_ratios: list[float]  # finesse de calcul de chaque branche
    zero_reason: str | None = None  # pourquoi le vent arrière n'est pas crédité (prévision peu fiable)

    @property
    def penetration_ok(self) -> bool:
        return self.min_ground_kmh >= self.penetration_min_kmh - 1e-9

    @property
    def crab_deg(self) -> float:
        v = max(self.air_speed_kmh, 1.0)
        return math.degrees(math.asin(min(1.0, self.cross_kmh / v)))


def legs_of(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Branches (longueur km, cap °) d'un chemin [(lat, lon), …] ; branches de longueur nulle ignorées."""
    out: list[tuple[float, float]] = []
    for a, b in pairwise(points):
        d = haversine_km(a[0], a[1], b[0], b[1])
        if d > 1e-4:
            out.append((d, bearing_deg(a[0], a[1], b[0], b[1])))
    return out


def compute_glide(
    legs: list[tuple[float, float]],
    z0: float,
    za: float,
    column: WindColumn,
    credit: CreditParams,
    level: str,
    wing: float,
    k: float,
    factor: float = 1.0,
) -> GlideWind:
    """Finesse de calcul d'un plané (§14.1-14.3) et hauteur perdue attendue (§14.4). `legs` = branches réelles
    (contournements compris), z0 = altitude de départ, za = alt_atterro + marge (entrée de l'approche)."""
    gw = rules.GLIDE_WIND
    p = polar(wing)
    vt = float(p["trim_kmh"])
    c = credit.fraction(level)
    cap = float(rules.GLIDE_TAIL_CREDIT["cap_kmh"][level])
    g = credit.headwind_factor
    bar_ok = credit.bar_allowed(level)
    vmax = max_speed(wing, level, bar_ok)
    step = rules.SPEED_SEARCH_STEP_KMH
    eff = rules.EXPECTED_ARRIVAL["efficiency"]
    calm = wing * k * factor
    pen_min = float(rules.GLIDE_PENETRATION_MIN_KMH[level])
    total = sum(d for d, _ in legs)
    zero_reason = credit.zero_reasons[0] if credit.zero_reasons else None
    if total <= 1e-6:
        return GlideWind(
            available=calm, calm=calm, expected=wing * eff, expected_loss_m=0.0, along_kmh=0.0, cross_kmh=0.0,
            credit_kmh=0.0, mean_speed_kmh=0.0, mean_dir_deg=0.0, air_speed_kmh=vt, trim_kmh=vt, ground_speed_kmh=vt,
            min_ground_kmh=vt, penetration_min_kmh=pen_min, gust_factor=g, credit_fraction=c, bar_allowed=bar_ok,
            leg_ratios=[], zero_reason=zero_reason,
        )  # fmt: skip
    dz = z0 - za
    cum = 0.0
    inv = exp_loss = 0.0
    along = cross = cred = su = sv = 0.0
    impossible = False
    leg_ratios: list[float] = []
    min_ground = math.inf
    longest = (-1.0, vt, vt)  # (longueur, V, V_sol)
    for dist, brg in legs:
        z_hi = z0 - cum / total * dz
        cum += dist
        z_lo = z0 - cum / total * dz
        u, v, uf, vf = column.mean(z_lo, z_hi)
        s, co = math.sin(math.radians(brg)), math.cos(math.radians(brg))
        w_par = u * s + v * co
        w_perp = abs(u * co - v * s)
        w_par_f = uf * s + vf * co
        speed = math.hypot(u, v)
        w_min = min(w_par, w_par_f)  # vent arrière : jamais plus que le vent fusionné ; face : la plus forte
        if w_min > 0:
            w_ret = min(c * w_min, cap) if speed >= gw["calm_kmh"] else 0.0
        else:
            w_ret = w_min * g
        best: tuple[float, float, float] | None = None
        vv = vt
        while vv <= vmax + 1e-9:
            if vv > w_perp:
                vg = math.sqrt(vv * vv - w_perp * w_perp) + w_ret
                f = rho(wing, vv) * vg / vv
                if best is None or f > best[0] + 1e-12:
                    best = (f, vv, vg)
            vv += step
        if best is None or best[2] <= 0:
            impossible = True
            leg_ratios.append(0.0)
            min_ground = min(min_ground, 0.0 if best is None else best[2])
            v_air, vg = vt, 0.0
        else:
            fi = wing * k * best[0] * factor
            leg_ratios.append(fi)
            inv += dist / fi
            v_air, vg = best[1], best[2]
            min_ground = min(min_ground, vg)
        v_exp = math.sqrt(max(0.0, v_air * v_air - w_perp * w_perp)) + w_par if v_air > w_perp else 0.0
        if v_exp <= 0:
            exp_loss = math.inf
        elif exp_loss != math.inf:
            exp_loss += dist * 1000.0 / (wing * eff * rho(wing, v_air) * v_exp / v_air)
        along += dist * w_par
        cross += dist * w_perp
        cred += dist * w_ret
        su += dist * u
        sv += dist * v
        if dist > longest[0]:
            longest = (dist, v_air, vg)
    mean_speed, mean_dir = wind_from_components(su / total, sv / total)
    available = 0.0 if impossible or inv <= 0 else total / inv
    expected = 0.0 if exp_loss in (0.0, math.inf) else total * 1000.0 / exp_loss
    return GlideWind(
        available=available, calm=calm, expected=expected, expected_loss_m=exp_loss, along_kmh=along / total,
        cross_kmh=cross / total, credit_kmh=cred / total, mean_speed_kmh=mean_speed, mean_dir_deg=mean_dir,
        air_speed_kmh=longest[1], trim_kmh=vt, ground_speed_kmh=longest[2],
        min_ground_kmh=0.0 if min_ground == math.inf else min_ground, penetration_min_kmh=pen_min, gust_factor=g,
        credit_fraction=c, bar_allowed=bar_ok, leg_ratios=leg_ratios, zero_reason=zero_reason,
    )  # fmt: skip


def uniform_finesse(
    wing: float, level: str, k: float, speed: float, direction: float, track: float, credit: CreditParams | None = None
) -> float:
    """Finesse de calcul sol par un vent uniforme sur le cap `track` (cône de finesse, compatibilité)."""
    col = WindColumn.uniform(speed, direction)
    return compute_glide([(1.0, track)], 1000.0, 0.0, col, credit or CreditParams(), level, wing, k).available


# =============================================================================================
# Sources de vent : champ du vol (GlideField) ou vent uniforme (compatibilité, tests)
# =============================================================================================
class WindSource(Protocol):  # pragma: no cover - interface
    def column(self, landing: Site, t0: datetime | None, ta: datetime | None, z0: float) -> WindColumn: ...

    def credit(
        self, landing: Site, t0: datetime | None, ta: datetime | None, origin: tuple[float, float]
    ) -> CreditParams: ...


@dataclass(slots=True)
class UniformWind:
    """Vent uniforme (vitesse, direction) : ancienne convention « un seul vent », gardée pour les appels sans champ
    de vent (tests, cône de compatibilité). Crédit de base du niveau, sans bonus ni malus."""

    speed_kmh: float
    direction_deg: float

    def column(self, landing: Site, t0: datetime | None, ta: datetime | None, z0: float) -> WindColumn:
        return WindColumn.uniform(self.speed_kmh, self.direction_deg)

    def credit(
        self, landing: Site, t0: datetime | None, ta: datetime | None, origin: tuple[float, float]
    ) -> CreditParams:
        return CreditParams()


def as_source(wind) -> WindSource:
    if isinstance(wind, tuple | list):
        return UniformWind(float(wind[0]), float(wind[1]))
    return wind


class GlideField:
    """Vents des planés d'un vol (CDC §14.1-14.2) autour d'un décollage : vent retenu au déco à l'heure de départ,
    vent retenu à chaque atterro à l'heure d'arrivée (brise, balise, tendance), profil du modèle au déco au-dessus de
    son altitude ; fiabilité du crédit de vent arrière. Ancres et colonnes mises en cache (heures exactes : les
    appelants arrondissent les ETA au quart d'heure)."""

    def __init__(
        self,
        ctx: DataContext,
        takeoff: Site,
        tl: PointTimeline,
        start: datetime,
        tw: TakeoffWind | None = None,
        main_landing: Site | None = None,
        main_ltl: PointTimeline | None = None,
        main_big_valley: bool | None = None,
    ) -> None:
        self.ctx = ctx
        self.takeoff = takeoff
        self.tl = tl
        self.start = start
        self.main_landing = main_landing
        self.main_ltl = main_ltl
        self.main_big_valley = main_big_valley
        self._tw: dict[datetime, TakeoffWind] = {}
        if tw is not None:
            self._tw[tw.time] = tw
        self._lw: dict[tuple[str, datetime], LandingWind] = {}
        self._cols: dict[tuple, WindColumn] = {}
        self._credit: dict[tuple, CreditParams] = {}
        self._zero: tuple[str, ...] | None = None

    # --- ancres ---------------------------------------------------------------------------------
    def takeoff_wind(self, t: datetime | None) -> TakeoffWind:
        t = t or self.start
        hit = self._tw.get(t)
        if hit is None:
            hit = takeoff_wind(self.ctx, self.takeoff, self.tl, t)
            self._tw[t] = hit
        return hit

    def _is_main(self, landing: Site) -> bool:
        return self.main_landing is not None and landing.id == self.main_landing.id

    def landing_wind(self, landing: Site, t: datetime) -> LandingWind:
        key = (landing.id, t)
        hit = self._lw.get(key)
        if hit is None:
            main = self._is_main(landing)
            ltl = (self.main_ltl if main and self.main_ltl is not None
                   else timeline_for(self.ctx, landing, self.tl)) or self.tl  # fmt: skip
            bv = self.main_big_valley if main and self.main_big_valley is not None else big_valley(self.ctx, landing)
            hit = landing_wind(ltl, t, bv, self.ctx, landing, "landing" if main else "alternate_landing")
            self._lw[key] = hit
        return hit

    def _arrival(self, t0: datetime | None, ta: datetime | None, z0: float, landing: Site) -> tuple[datetime, datetime]:
        t0 = t0 or self.start
        return t0, ta or t0 + timedelta(minutes=plouf_minutes(z0 - landing.elevation_m))

    # --- colonne ----------------------------------------------------------------------------------
    def column(self, landing: Site, t0: datetime | None, ta: datetime | None, z0: float) -> WindColumn:
        t0, ta = self._arrival(t0, ta, z0, landing)
        key = (landing.id, t0, ta)
        hit = self._cols.get(key)
        if hit is not None:
            return hit
        tw = self.takeoff_wind(t0)
        lw = self.landing_wind(landing, ta)
        col = build_column(
            self.takeoff.elevation_m, landing.elevation_m,
            _uv4(tw.speed_kmh, tw.direction_deg, tw.fused_speed_kmh or tw.speed_kmh),
            _uv4(lw.speed_kmh, lw.direction_deg, lw.fused_speed_kmh or lw.speed_kmh),
            tw.hour.profile.wind_points(),
        )  # fmt: skip
        self._cols[key] = col
        return col

    # --- fiabilité du crédit ------------------------------------------------------------------------
    def zero_reasons(self) -> tuple[str, ...]:
        """Crédit nul (§14.2) : confiance faible, modèles en désaccord sur la direction, balises en désaccord avec la
        prévision, bascule du vent (tendance des balises). Évalué une fois, au départ, avec l'atterro principal."""
        if self._zero is not None:
            return self._zero
        ctx = self.ctx
        tw = self.takeoff_wind(self.start)
        lw_nc = None
        if self.main_landing is not None and self.main_landing.id != self.takeoff.id:
            ta = self.start + timedelta(minutes=plouf_minutes(self.takeoff.elevation_m
                                                              - self.main_landing.elevation_m))  # fmt: skip
            lw_nc = self.landing_wind(self.main_landing, ta).nowcast
        top = self.main_landing is not None and self.main_landing.id == self.takeoff.id
        conf = forecast_confidence(ctx, self.tl, self.start, tw.nowcast, lw_nc, top)
        out: list[str] = []
        base = rules.HORIZON_BASE_CONFIDENCE[ctx.horizon]
        if conf.raw < rules.VERDICT["go_min_confidence_ratio"] * base:
            out.append("prévision peu fiable")
        if conf.sig_d > rules.DISPERSION_DIR_SIGMA_DEG:
            out.append("modèles en désaccord sur la direction du vent")
        mism = any(nc is not None and nc.has_representative and nc.mismatch for nc in (tw.nowcast, lw_nc))
        if mism:
            out.append("balises en désaccord avec la prévision")
        shift = any(f.code == "WIND_SHIFT" for nc in (tw.nowcast, lw_nc) if nc is not None
                    for f in trend_findings(nc, ctx.horizon, tw.speed_kmh))  # fmt: skip
        if shift:
            out.append("le vent tourne aux balises")
        self._zero = tuple(out)
        return self._zero

    def _beacon_confirms(self, nc: StationNowcast | None, retained_dir: float) -> bool:
        b = rules.GLIDE_TAIL_CREDIT["bonus"]
        if nc is None or not nc.has_representative or self.ctx.horizon not in rules.NOWCAST_HORIZONS:
            return False
        for a in nc.representative:
            bd, bv = a.beacon.wind_direction_deg, a.beacon.wind_speed_kmh
            if bd is None or bv is None:
                continue
            if angle_diff(bd, retained_dir) <= b["beacon_confirms_max_dir_deg"] and (
                bv >= b["beacon_confirms_min_speed_ratio"] * a.model_speed_kmh
            ):
                return True
        return False

    def credit(
        self, landing: Site, t0: datetime | None, ta: datetime | None, origin: tuple[float, float]
    ) -> CreditParams:
        z0 = self.takeoff.elevation_m
        t0, ta = self._arrival(t0, ta, z0, landing)
        track = bearing_deg(origin[0], origin[1], landing.lat, landing.lon)
        key = (landing.id, t0, ta, round(track))
        hit = self._credit.get(key)
        if hit is not None:
            return hit
        c = rules.GLIDE_TAIL_CREDIT
        tw = self.takeoff_wind(t0)
        lw = self.landing_wind(landing, ta)
        main = self._is_main(landing)
        bv = self.main_big_valley if main and self.main_big_valley is not None else big_valley(self.ctx, landing)
        lt = legal_time(ta)
        lh = lt.hour + lt.minute / 60.0
        h0, h1 = rules.VALLEY_BREEZE_HOURS_LEGAL
        tail = lw.speed_kmh * math.cos(math.radians((lw.direction_deg + 180.0) % 360.0 - track))
        breeze = (
            bv and h0 <= lh < h1 and lw.speed_kmh >= c["bonus"]["established_breeze_min_kmh"]
            and tail >= c["bonus"]["established_breeze_min_tail_kmh"]
        )  # fmt: skip
        ev = c["malus"]["evening_transition"]
        evening = False
        if bv or not ev["big_valley_only"]:
            _, sset = sun_times(ta, landing.lat, landing.lon)
            if sset is not None:
                evening = sset + timedelta(minutes=ev["from_sunset_min"]) <= ta <= sset + timedelta(
                    minutes=ev["to_sunset_min"]
                )
        ratio, spread = _gust_stats([(tw.speed_kmh, tw.gust_kmh), (lw.speed_kmh, lw.gust_kmh)])
        beacon = self._beacon_confirms(lw.nowcast, lw.direction_deg) or self._beacon_confirms(
            tw.nowcast, tw.direction_deg
        )
        out = CreditParams(
            horizon_malus=float(c["malus"]["horizon"].get(self.ctx.horizon, 0.0)), beacon_confirms=beacon,
            established_breeze=breeze, gust_ratio=ratio, evening=evening, zero_reasons=self.zero_reasons(),
            gust_spread_kmh=spread,
        )  # fmt: skip
        self._credit[key] = out
        return out

    # --- cône de finesse (pas d'atterro désigné) -------------------------------------------------------
    def cone_wind(self, t: datetime | None = None) -> tuple[float, float]:
        """Vent moyen du profil du déco sur [alt_déco − 1000 m ; alt_déco] (§14.1, cône de finesse)."""
        tw = self.takeoff_wind(t)
        z = self.takeoff.elevation_m
        return tw.hour.profile.mean_wind(z - float(rules.GLIDE_WIND["cone_layer_m"]), z)

    def cone_credit(self, t: datetime | None = None) -> CreditParams:
        """Crédit du niveau sans bonus (§14.1) : malus d'horizon, rafales du déco, fiabilité."""
        tw = self.takeoff_wind(t)
        ratio, spread = _gust_stats([(tw.speed_kmh, tw.gust_kmh)])
        return CreditParams(
            horizon_malus=float(rules.GLIDE_TAIL_CREDIT["malus"]["horizon"].get(self.ctx.horizon, 0.0)),
            gust_ratio=ratio, zero_reasons=self.zero_reasons(), gust_spread_kmh=spread,
        )  # fmt: skip


# =============================================================================================
# Arrivée haute (§14.4) et zone de perte d'altitude
# =============================================================================================
def high_arrival_levels(height_m: float) -> dict[str, str | None]:
    """Niveau du Risk HIGH_ARRIVAL par niveau de pilote (jamais danger)."""
    h = rules.HIGH_ARRIVAL
    out: dict[str, str | None] = {}
    for lv in LEVELS:
        if height_m >= h["caution_m"][lv]:
            out[lv] = "caution"
        elif height_m >= h["info_m"]:
            out[lv] = "info"
        else:
            out[lv] = None
    return out


def zpa_bearings(wind_speed: float, wind_from: float, arrival_from: float) -> list[float]:
    """Relèvements atterro → zone de perte d'altitude, par ordre de préférence (§14.4) : au vent (d'où vient le vent)
    ± 45° du côté d'où arrive le pilote, puis en travers jusqu'à ± 90°, jamais sous le vent. Vent < 5 km/h : côté
    d'arrivée du pilote."""
    z = rules.LOSE_HEIGHT_ZONE
    if wind_speed < z["calm_kmh"]:
        return [arrival_from % 360.0] + [(arrival_from + s * o) % 360.0 for o in (30, 60, 90) for s in (1, -1)]
    side = (arrival_from - wind_from + 180.0) % 360.0 - 180.0  # côté d'arrivée par rapport au vent
    sec, fb = float(z["upwind_sector_deg"]), float(z["fallback_crosswind_deg"])
    pref = max(-sec, min(sec, side))
    sign = 1.0 if side >= 0 else -1.0
    offs = [pref]
    for o in (15.0, 30.0, 45.0, 60.0, 75.0, 90.0):
        for s in (sign, -sign):
            x = s * o
            if abs(x) <= fb + 1e-9 and all(abs(x - y) > 1e-6 for y in offs):
                offs.append(x)
    offs.sort(key=lambda x: (abs(x - pref) > sec, abs(x - pref)))
    return [(wind_from + o) % 360.0 for o in offs]


# =============================================================================================
# Textes destinés au pilote (§14.4, §14.7)
# =============================================================================================
def fr(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def au(label: str) -> str:
    """« au N », « à l'E » (secteur en notation française)."""
    return f"à l'{label}" if label[0] in "EO" else f"au {label}"


def _zone_short(name: str) -> str:
    return f"la zone « {name} »"


def wind_phrase(g: GlideCheck, level: str) -> str:
    """Le vent sur le plané en une proposition (raison GLIDE_MARGIN, §14.7)."""
    w = g.wind
    if w is None:
        return "air calme"
    d = dir_label(w.mean_dir_deg)
    if w.mean_speed_kmh < rules.GLIDE_WIND["calm_kmh"]:
        return "vent faible sur le plané"
    if w.along_kmh >= 5:
        return (f"vent du {d} ≈ {w.mean_speed_kmh:.0f} km/h dans le dos sur le plané ({fr(max(0.0, w.credit_kmh))} "
                f"comptés)")  # fmt: skip
    if w.along_kmh <= -5:
        txt = f"vent du {d} ≈ {w.mean_speed_kmh:.0f} km/h de face sur le plané"
        if w.gust_factor > 1.001:
            txt += f" ({abs(w.credit_kmh):.0f} avec les rafales)"
        if w.bar_allowed:
            txt += ", accélérateur compris"
        elif level == "beginner":
            txt += ", bras hauts (pas d'accélérateur à ton niveau)"
        else:
            txt += ", bras hauts (air trop rafaleux pour compter l'accélérateur)"
        return txt
    if w.cross_kmh >= 10:
        return f"vent de travers du {d} ≈ {w.mean_speed_kmh:.0f} km/h sur le plané (crabe ≈ {w.crab_deg:.0f}°)"
    return f"vent du {d} ≈ {w.mean_speed_kmh:.0f} km/h sur le plané ({w.along_kmh:+.0f} km/h sur la route)"


def glide_comment(
    g: GlideCheck,
    landing_name: str,
    level: str,
    wing: float,
    detour_zones: list[str] | None = None,
    high_arrival_m: float | None = None,
) -> str:
    """`FlightPlan.glide.comment` (§14.7) : une ou deux phrases selon la composante dominante."""
    w = g.wind
    calm = fr(g.calm_ratio)
    avail = fr(g.available_ratio)
    if w is None:
        return f"Posé au décollage (top landing) : finesse de calcul {calm} en air calme."
    d = dir_label(w.mean_dir_deg)
    arr = g.expected_arrival_m
    arr_txt = f"≈ {arr:.0f} m au-dessus de {landing_name}" if arr is not None and arr > 0 else f"sous {landing_name}"
    if w.mean_speed_kmh < rules.GLIDE_WIND["calm_kmh"]:
        txt = f"Vent faible sur le plané : finesse de calcul {avail} (air calme), arrivée attendue {arr_txt}."
    elif w.along_kmh >= 5:
        if w.credit_fraction <= 0 and w.zero_reason:
            counted = f"non comptés : {w.zero_reason}"
        else:
            counted = f"{fr(max(0.0, w.credit_kmh))} comptés"
        txt = f"Vent du {d} ≈ {w.mean_speed_kmh:.0f} km/h sur le plané : {w.along_kmh:.0f} km/h dans le dos ({counted})"
        if w.cross_kmh >= 3:
            txt += f", {w.cross_kmh:.0f} de travers"
        txt += f". Finesse de calcul {avail} au lieu de {calm} sans vent"
        if w.expected > 0:
            txt += f" ; finesse attendue ≈ {fr(w.expected)}"
        txt += "."
    elif w.along_kmh <= -5:
        counted = (f"{abs(w.credit_kmh):.0f} comptés avec les rafales" if w.gust_factor > 1.001
                   else "compté en entier")  # fmt: skip
        txt = (f"Vent du {d} ≈ {w.mean_speed_kmh:.0f} km/h de face sur le plané ({counted}) : finesse de calcul "
               f"{avail} au lieu de {calm} sans vent.")  # fmt: skip
        if w.air_speed_kmh > w.trim_kmh + 0.25:
            txt += (f" Accélère ({bar_label(wing, w.air_speed_kmh)}, ≈ {w.air_speed_kmh:.0f} km/h) : vitesse sol ≈ "
                    f"{w.ground_speed_kmh:.0f} km/h ; relâche l'accélérateur sous "
                    f"{rules.SPEED_BAR_RELEASE_AGL_M} m sol et dans la PTU.")  # fmt: skip
        elif level == "beginner":
            txt += " Élève : pas d'accélérateur, bras hauts."
        elif not w.bar_allowed:
            txt += " Rafales : pas d'accélérateur compté, bras hauts."
        else:
            txt += " Bras hauts : accélérer ne gagne rien à ce vent."
    elif w.cross_kmh >= 10:
        v = max(w.air_speed_kmh, 1.0)
        loss = v - math.sqrt(max(0.0, v * v - w.cross_kmh * w.cross_kmh))
        txt = (f"Vent de travers du {d} ≈ {w.mean_speed_kmh:.0f} km/h sur le plané : en crabe (≈ {w.crab_deg:.0f}°), "
               f"tu perds {loss:.0f} km/h de vitesse sol ; finesse de calcul {avail} au lieu de {calm}.")  # fmt: skip
    else:
        txt = (f"Vent du {d} ≈ {w.mean_speed_kmh:.0f} km/h sur le plané, presque sans effet "
               f"({w.along_kmh:+.0f} km/h sur la route) : finesse de calcul {avail} ({calm} sans vent), arrivée "
               f"attendue {arr_txt}.")  # fmt: skip
    if not w.penetration_ok:
        txt += (f" Pénétration insuffisante : vitesse sol {w.min_ground_kmh:.0f} km/h, minimum "
                f"{w.penetration_min_kmh:.0f} à ton niveau.")  # fmt: skip
    if high_arrival_m is not None:
        txt += f" Arrivée haute à {landing_name} (≈ {high_arrival_m:.0f} m) : perds l'altitude au vent de l'atterro."
    if detour_zones:
        txt += f" Plané allongé à {fr(g.dist_km)} km pour contourner {_zone_short(detour_zones[0])}."
    return txt


def high_arrival_detail(
    landing_name: str,
    height_m: float,
    g: GlideCheck,
    level: str,
    landing_wind_dir: float,
    landing_wind_kmh: float,
    zpa_side: str | None,
    zone_names: list[str],
) -> str:
    """Détail du Risk HIGH_ARRIVAL (§14.4) : hauteur attendue, vent, consignes de perte d'altitude et d'approche."""
    w = g.wind
    d = dir_label(w.mean_dir_deg) if w is not None else "—"
    tail = w.along_kmh if w is not None else 0.0
    where = f", {au(zpa_side)} de {landing_name}" if zpa_side else ""
    zone = f" (zone de perte d'altitude hors de {_zone_short(zone_names[0])})" if zone_names else ""
    ptu = rules.APPROACH["ptu_entry_agl_m"][level]
    txt = (f"Arrivée haute à {landing_name} : environ {height_m:.0f} m au-dessus de l'atterro avec le vent du {d} dans "
           f"le dos ({tail:.0f} km/h). Perds l'altitude au vent de l'atterro et décalé sur le côté{where}{zone}, en 8 "
           f"face au vent, jamais derrière l'atterro : tu ne reviendrais pas contre la brise.")  # fmt: skip
    if level == "beginner":
        txt += " Pas de 360 : seulement des 8 face au vent."
    else:
        txt += (f" Pas de 360 sous {rules.APPROACH['no_360_below_agl_m']} m sol ; les oreilles, si tu les maîtrises, "
                f"au-dessus de la zone de perte d'altitude, relâchées avant 150 m sol.")  # fmt: skip
    txt += f" Entre dans la PTU vers {ptu} m sol, finale face au {dir_label(landing_wind_dir)}."
    if landing_wind_kmh >= rules.APPROACH["final_gradient_wind_kmh"]:
        txt += " Gradient près du sol : garde de la vitesse en finale (bras hauts)."
    return txt


__all__ = [
    "CreditParams",
    "GlideField",
    "GlideWind",
    "UniformWind",
    "WindColumn",
    "as_source",
    "big_valley",
    "build_column",
    "compute_glide",
    "forecast_confidence",
    "glide_comment",
    "high_arrival_detail",
    "high_arrival_levels",
    "legs_of",
    "plouf_minutes",
    "quarter",
    "rho",
    "timeline_for",
    "uniform_finesse",
    "wind_phrase",
    "zpa_bearings",
]
