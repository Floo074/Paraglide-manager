"""Balises rattachées aux sites d'un plan : rattachement, poids, fusion modèle + balise, tendance (CDC §12.1-12.3).

Vocabulaire :
- rôle : « takeoff » (déco, évalué au DÉBUT du créneau), « landing » / « alternate_landing » (atterro principal / de
  secours, évalués à l'heure d'ARRIVÉE estimée = début du créneau + durée du vol) ;
- Δt : minutes entre `reference_time` (instant de la mesure) et l'instant évalué → poids nominal
  `rules.beacon_weight_by_minutes(Δt)` ;
- fusion : `v = v_modèle(instant évalué) + W × (v_balise − v_modèle(maintenant))`, W = poids de la meilleure balise
  représentative, écart = moyenne des écarts pondérée par les poids ;
- tendance (horizons ≤ 1 h, hausse > 5 km/h/h) : `v_ext = v_balise + min(15, r × min(Δt, 60) / 60)`, jamais à la
  baisse ; le verdict utilise max(v_fusion, v_ext).

Le rattachement (distance, altitude, nom, fraîcheur, suspicion) ne dépend pas de l'instant évalué : il est calculé
une fois par (rôle, site) et mis en cache dans le contexte ; seul le poids nominal dépend de Δt.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from app.engine import rules
from app.engine.findings import Finding
from app.geo import haversine_km, signed_angle_diff
from app.models import Beacon, Site

if TYPE_CHECKING:  # pragma: no cover
    from app.engine.context import DataContext, PointTimeline

ROLE_LABEL = {"takeoff": "déco", "landing": "atterro", "alternate_landing": "atterro de secours"}
_SITE_STOPWORDS = {
    "atterrissage", "atterro", "attero", "officiel", "officielle", "decollage", "deco", "sommet", "balise", "pioupiou",
    "landing", "takeoff", "site", "nord", "sud", "est", "ouest", "mont", "pointe", "plage", "club", "village", "haut",
    "haute", "bas", "basse", "grand", "grande", "petit", "petite", "saint", "sainte", "les", "des", "sur", "sous",
    "chalet", "parapente", "vol", "libre", "terrain", "zone", "the", "col",
}  # fmt: skip
STALE_MIN = float(rules.BEACON_FRESHNESS_MIN["stale"])
DIR_MIN_WIND_KMH = float(rules.TREND_1H["rotation"]["min_wind_kmh"])  # 8 km/h : direction corrigée au-delà


# =============================================================================================
# Noms : bonus / mauvais rôle
# =============================================================================================
def _norm(text: str) -> str:
    s = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def name_has_keyword(name: str, keywords) -> bool:
    """Mot-clé en début de mot (« atterro » ⊂ « atterros ») ; mots de 4 lettres ou moins : mot entier (« col »,
    « top », « déco »), pour ne pas prendre « Colombier » ou « Nicolas » pour un col."""
    n = _norm(name)
    for kw in keywords:
        k = _norm(kw)
        tail = r"(?![a-z])" if len(k) <= 4 else ""
        if re.search(r"(?<![a-z])" + re.escape(k) + tail, n):
            return True
    return False


def site_name_tokens(site_name: str) -> list[str]:
    toks = re.split(r"[^a-z]+", _norm(site_name))
    return [t for t in toks if len(t) >= 4 and t not in _SITE_STOPWORDS]


def name_mentions_site(beacon_name: str, site_name: str) -> bool:
    n = _norm(beacon_name)
    return any(re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", n) for t in site_name_tokens(site_name))


# =============================================================================================
# Rattachement d'une balise à un site
# =============================================================================================
@dataclass(slots=True)
class Attachment:
    beacon: Beacon
    role: str
    site: Site
    distance_km: float
    age_min: float
    elevation_m: float | None  # altitude retenue (source ou MNT), None si inconnue
    elevation_source: str  # source | dem | unknown
    name_bonus: bool
    attached: bool = False  # dans les limites de rattachement (§12.1)
    reason: str | None = None  # pourquoi non rattachée / non représentative
    f_distance: float = 0.0
    f_altitude: float = 1.0
    f_unknown: float = 1.0
    f_fresh: float = 0.0
    synoptic: bool = False  # 300-600 m au-dessus/au-dessous du déco : composante synoptique seulement
    stale: bool = False
    suspect: bool = False
    outlier: bool = False
    representative: bool = False
    model_speed_kmh: float = 0.0  # vent modèle « maintenant » comparable à la balise
    model_dir_deg: float = 0.0
    dv: float = 0.0  # balise − modèle (maintenant)
    dd: float = 0.0
    dd_valid: bool = False

    @property
    def alt_diff_m(self) -> float | None:
        return None if self.elevation_m is None else self.elevation_m - self.site.elevation_m

    @property
    def factor(self) -> float:
        """f_distance × f_altitude × f_alt_inconnue × f_fraîcheur (× 0,3 si isolée)."""
        f = self.f_distance * self.f_altitude * self.f_unknown * self.f_fresh
        return f * (rules.BEACON_OUTLIER["factor"] if self.outlier else 1.0)

    def weight(self, w_nominal: float) -> float:
        return round(w_nominal * self.factor, 3) if self.representative else 0.0


def km(x: float) -> str:
    """Distance en km, virgule décimale (texte destiné au pilote)."""
    return f"{x:.1f}".replace(".", ",")


def _linear(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    if x <= x0:
        return y0
    if x >= x1:
        return y1
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def freshness_factor(age_min: float) -> float:
    fr = rules.BEACON_FRESHNESS_MIN
    if age_min > fr["stale"]:
        return 0.0
    return _linear(age_min, fr["full_weight"], 1.0, fr["stale"], fr["factor_at_stale"])


def beacon_elevation(ctx: DataContext, b: Beacon) -> tuple[float | None, str]:
    """Altitude de la balise : celle de la source, sinon le MNT au point (ctx.beacon_dem_m), sinon inconnue."""
    if b.elevation_m is not None:
        return float(b.elevation_m), "source"
    dem = ctx.beacon_dem_m.get(b.id)
    if dem is not None:
        return float(dem), "dem"
    return None, "unknown"


def _same_valley(ctx: DataContext, b: Beacon, b_elev: float, site: Site) -> bool:
    """Aucun point du MNT entre la balise et l'atterro au-dessus de max(alt balise, alt atterro) + 100 m."""
    if not ctx.terrain_is_real:
        return True
    d = haversine_km(b.lat, b.lon, site.lat, site.lon)
    n = int(d / 0.2)
    if n < 2:
        return True
    top = max(b_elev, site.elevation_m) + rules.LANDING_BEACON_ATTACH["same_valley_relief_margin_m"]
    above = 0
    for i in range(1, n):
        f = i / n
        z = ctx.terrain_at(b.lat + (site.lat - b.lat) * f, b.lon + (site.lon - b.lon) * f)
        if z is not None and z > top:
            above += 1
            if above >= 2:  # deux points consécutifs : on évite un artefact d'interpolation du MNT
                return False
        else:
            above = 0
    return True


def _attach_takeoff(at: Attachment) -> None:
    p = rules.TAKEOFF_BEACON_ATTACH
    d, b = at.distance_km, at.beacon
    dist = p["distance_km"]
    max_d = dist["max"]
    if at.elevation_source == "unknown":
        max_d = min(max_d, rules.UNKNOWN_BEACON_ALTITUDE["no_dem_takeoff_max_distance_km"])
    if d > max_d:
        at.reason = f"à {km(d)} km du déco" + (" (altitude inconnue : 2 km au plus)" if at.elevation_source == "unknown" else "")
        return
    full = p["name_bonus"]["full_distance_km"] if at.name_bonus else dist["full"]
    at.f_distance = _linear(d, full, 1.0, dist["max"], dist["factor_at_max"])
    dz = at.alt_diff_m
    wrong = name_has_keyword(b.name, p["wrong_role"]["keywords"])
    if wrong and (dz is None or abs(dz) > p["wrong_role"]["max_alt_diff_m"]):
        at.reason = "balise d'atterrissage (nom), pas au niveau du déco"
        return
    alt = p["alt_diff_m"]
    if dz is None:
        at.f_altitude = 1.0
        at.f_unknown = rules.UNKNOWN_BEACON_ALTITUDE["no_dem_factor"]
    else:
        adz = abs(dz)
        if adz > alt["synoptic_max"]:
            at.reason = f"{adz:.0f} m {'plus haut' if dz > 0 else 'plus bas'} que le déco : ne sert qu'au vent de crête"
            return
        if adz <= alt["reduced"]:
            at.f_altitude = _linear(adz, alt["full"], 1.0, alt["reduced"], alt["factor_at_reduced"])
        else:
            at.f_altitude = alt["factor_synoptic"]
            at.synoptic = True
        at.f_unknown = rules.UNKNOWN_BEACON_ALTITUDE["dem_factor"] if at.elevation_source == "dem" else 1.0
    at.attached = True


def _attach_landing(ctx: DataContext, at: Attachment) -> None:
    p = rules.LANDING_BEACON_ATTACH
    d, b = at.distance_km, at.beacon
    dist, bonus = p["distance_km"], p["name_bonus"]
    full = bonus["full_distance_km"] if at.name_bonus else dist["full"]
    max_d = bonus["max_distance_km"] if at.name_bonus else dist["max"]
    if d > max_d:
        at.reason = f"à {km(d)} km de l'atterro"
        return
    at.f_distance = _linear(d, full, 1.0, max_d, dist["factor_at_max"])
    dz = at.alt_diff_m
    wrong = name_has_keyword(b.name, p["wrong_role"]["keywords"])
    if wrong and (dz is None or abs(dz) > p["wrong_role"]["max_alt_diff_m"]):
        at.reason = "balise de déco ou de sommet (nom) : ne voit pas la brise de vallée"
        return
    if dz is None:
        nd = rules.UNKNOWN_BEACON_ALTITUDE["no_dem_landing"]
        at.f_altitude = 1.0
        at.f_unknown = rules.UNKNOWN_BEACON_ALTITUDE["no_dem_factor"]
        if (nd["requires_name_bonus"] and not at.name_bonus) or d > nd["max_distance_km"]:
            at.attached = True
            at.reason = "altitude inconnue, sans nom d'atterro ou trop loin pour être sûre de voir la brise"
            return
    else:
        adz = abs(dz)
        max_dz = bonus["max_alt_diff_m"] if at.name_bonus else p["alt_diff_m"]["max"]
        if adz > max_dz:
            at.reason = f"{adz:.0f} m {'plus haut' if dz > 0 else 'plus bas'} que l'atterro : ne voit pas la brise de vallée"
            return
        at.f_altitude = _linear(adz, p["alt_diff_m"]["full"], 1.0, max_dz, p["alt_diff_m"]["factor_at_max"])
        at.f_unknown = rules.UNKNOWN_BEACON_ALTITUDE["dem_factor"] if at.elevation_source == "dem" else 1.0
        if not _same_valley(ctx, b, at.elevation_m or 0.0, at.site):
            at.reason = "relief entre la balise et l'atterro : autre vallée"
            return
    at.attached = True


def attach(ctx: DataContext, b: Beacon, site: Site, role: str) -> Attachment:
    elev, src = beacon_elevation(ctx, b)
    kws = rules.TAKEOFF_BEACON_ATTACH if role == "takeoff" else rules.LANDING_BEACON_ATTACH
    bonus = name_has_keyword(b.name, kws["name_bonus"]["keywords"]) or name_mentions_site(b.name, site.name)
    age = ctx.beacon_ages_min.get(b.id, 0.0)
    at = Attachment(beacon=b, role=role, site=site, distance_km=haversine_km(site.lat, site.lon, b.lat, b.lon),
                    age_min=age, elevation_m=elev, elevation_source=src, name_bonus=bonus)  # fmt: skip
    if role == "takeoff":
        _attach_takeoff(at)
    else:
        _attach_landing(ctx, at)
    at.stale = b.stale or age > STALE_MIN or b.wind_speed_kmh is None
    at.f_fresh = 0.0 if at.stale else freshness_factor(age)
    return at


# =============================================================================================
# Modèle « maintenant » comparable à la balise, suspicion, représentativité
# =============================================================================================
def breeze_factor(t: datetime, big_valley: bool) -> float:
    """Facteur de brise de vallée (§4.3) à l'heure t (heure légale)."""
    if not big_valley:
        return 1.0
    from app.engine.conditions import legal_time

    lt = legal_time(t)
    lh = lt.hour + lt.minute / 60.0
    h0, h1 = rules.VALLEY_BREEZE_HOURS_LEGAL
    if h0 <= lh < h1:
        return rules.VALLEY_BREEZE_AFTERNOON_FACTOR
    if any(r0 <= lh < r1 for r0, r1 in rules.VALLEY_BREEZE_RAMP_HOURS_LEGAL):
        return rules.VALLEY_BREEZE_RAMP_FACTOR
    return 1.0


def _model_now(ctx: DataContext, at: Attachment, tl: PointTimeline, big_valley: bool) -> tuple[float, float]:
    a = tl.at(ctx.reference_time)
    if at.role == "takeoff":
        if at.elevation_m is not None and abs(at.elevation_m - at.site.elevation_m) > 50:
            return a.profile.wind(at.elevation_m)  # même altitude que la balise (synoptique si 300-600 m)
        from app.engine.conditions import model_takeoff_wind

        v, d, _ = model_takeoff_wind(a, at.site.elevation_m)
        return v, d
    return a.wind_speed_kmh * breeze_factor(ctx.reference_time, big_valley), a.wind_direction_deg


def site_attachments(
    ctx: DataContext, site: Site, role: str, tl: PointTimeline, big_valley: bool = False
) -> list[Attachment]:
    """Balises rattachées à un site (représentatives ou non), triées par facteur décroissant puis distance.
    Mis en cache par (rôle, site) : indépendant de l'instant évalué."""
    key = (role, site.id, big_valley)
    cached = ctx.station_cache.get(key)
    if cached is not None:
        return cached
    out: list[Attachment] = []
    for b in ctx.beacons:
        if abs(b.lat - site.lat) > 0.1 or abs(b.lon - site.lon) > 0.15:
            continue
        at = attach(ctx, b, site, role)
        if not at.attached:
            continue
        if not at.stale and b.wind_speed_kmh is not None:
            at.model_speed_kmh, at.model_dir_deg = _model_now(ctx, at, tl, big_valley)
            at.dv = b.wind_speed_kmh - at.model_speed_kmh
            if b.wind_direction_deg is not None and b.wind_speed_kmh >= DIR_MIN_WIND_KMH and at.model_speed_kmh >= DIR_MIN_WIND_KMH:
                at.dd = signed_angle_diff(b.wind_direction_deg, at.model_dir_deg)
                at.dd_valid = True
            gust0 = b.wind_gust_kmh in (None, 0.0) or (b.wind_gust_kmh or 0.0) <= 0.5
            at.suspect = b.wind_speed_kmh <= 0.5 and gust0 and at.model_speed_kmh >= rules.BEACON_SUSPECT_MODEL_MIN_KMH
        at.representative = (
            at.reason is None and not at.stale and not at.suspect and at.f_distance * at.f_altitude * at.f_unknown * at.f_fresh
            >= rules.BEACON_REPRESENTATIVE_MIN_FACTOR - 1e-9
        )
        if not at.representative and at.reason is None:
            if at.stale:
                at.reason = "périmée" if b.wind_speed_kmh is not None else "aucune mesure transmise"
            elif at.suspect:
                at.reason = f"suspecte : 0 km/h alors que le modèle donne {at.model_speed_kmh:.0f} km/h (anémomètre bloqué ou balise abritée)"
            else:
                at.reason = "trop éloignée, trop décalée en altitude ou trop ancienne pour corriger la prévision"
        out.append(at)
    rep = [a for a in out if a.representative]
    if len(rep) >= 2:
        med = statistics.median(a.beacon.wind_speed_kmh or 0.0 for a in rep)
        for a in rep:
            if abs((a.beacon.wind_speed_kmh or 0.0) - med) > rules.BEACON_OUTLIER["deviation_kmh"]:
                a.outlier = True
    out.sort(key=lambda a: (not a.representative, -a.factor, a.distance_km))
    ctx.station_cache[key] = out
    return out


def nearest_unattached(ctx: DataContext, site: Site, role: str, exclude: set[str]) -> Attachment | None:
    """Balise la plus proche non rattachée (pour dire pourquoi il n'y a pas de balise représentative)."""
    best: Attachment | None = None
    for b in ctx.beacons:
        if b.id in exclude:
            continue
        d = haversine_km(site.lat, site.lon, b.lat, b.lon)
        if d > rules.BEACON_SEARCH_RADIUS_KM or (best is not None and d >= best.distance_km):
            continue
        best = attach(ctx, b, site, role)
    return best


# =============================================================================================
# Tendance (§12.2)
# =============================================================================================
@dataclass(slots=True)
class TrendEval:
    attachment: Attachment
    rate_kmh_h: float
    v0: float
    v_now: float
    gust_now: float
    direction_change_deg: float
    gust_max_kmh: float | None
    window_min: float
    v_ext: float | None = None
    g_ext: float | None = None


def usable_trend(b: Beacon) -> bool:
    t = b.trend
    return t is not None and t.window_min >= rules.TREND_1H["min_window_min"] and t.samples >= rules.TREND_1H["min_samples"]


def eval_trend(at: Attachment, horizon: str, dt_min: float) -> TrendEval | None:
    b = at.beacon
    if not usable_trend(b) or at.stale or b.wind_speed_kmh is None:
        return None
    t = b.trend
    assert t is not None
    r = t.speed_change_kmh * 60.0 / t.window_min
    v = b.wind_speed_kmh
    g = b.wind_gust_kmh if b.wind_gust_kmh is not None else v
    te = TrendEval(at, r, v - t.speed_change_kmh, v, g, t.direction_change_deg, t.gust_max_kmh, t.window_min)
    tr = rules.TREND_1H
    if horizon in tr["extrapolate_horizons"] and r > tr["wind_increase_kmh_per_h"]["caution"]:
        inc = min(float(tr["extrapolate_cap_kmh"]), r * min(max(dt_min, 0.0), tr["extrapolate_max_minutes"]) / 60.0)
        if inc > 0 or tr["extrapolate_down"]:
            te.v_ext = v + inc
            te.g_ext = g + inc
    return te


def trend_label(b: Beacon) -> str:
    """« +10 km/h en 1 h », « stable »… ; « tendance indisponible » si l'historique est insuffisant."""
    if not usable_trend(b):
        return "tendance indisponible"
    t = b.trend
    assert t is not None
    r = t.speed_change_kmh * 60.0 / t.window_min
    win = "1 h" if abs(t.window_min - 60) <= 10 else f"{t.window_min:.0f} min"
    parts = []
    if abs(t.speed_change_kmh) < 3 and abs(r) <= rules.TREND_1H["wind_increase_kmh_per_h"]["caution"]:
        parts.append("stable")
    else:
        parts.append(f"{t.speed_change_kmh:+.0f} km/h en {win}")
    if abs(t.direction_change_deg) >= rules.TREND_1H["rotation"]["caution_deg"]:
        sens = "horaire" if t.direction_change_deg > 0 else "antihoraire"
        parts.append(f"rotation de {abs(t.direction_change_deg):.0f}° ({sens})")
    return ", ".join(parts)


# =============================================================================================
# Fusion à un instant donné
# =============================================================================================
@dataclass(slots=True)
class StationNowcast:
    role: str
    site: Site
    eval_time: datetime
    dt_min: float
    w_nominal: float
    attachments: list[Attachment]
    representative: list[Attachment] = field(default_factory=list)
    speed_bias_kmh: float = 0.0  # moyenne pondérée des écarts balise − modèle (maintenant)
    dir_bias_deg: float = 0.0
    dir_valid: bool = False
    weight: float = 0.0  # poids de fusion W (meilleure balise représentative)
    beacon_gust_kmh: float | None = None  # rafale balise 10 min (représentatives)
    mismatch: bool = False
    coherent: bool = False
    trend: TrendEval | None = None
    details: list[str] = field(default_factory=list)
    nearest_text: str = ""  # sans balise représentative : « la plus proche, X, est à 4,2 km … »

    @property
    def has_representative(self) -> bool:
        return bool(self.representative)

    @property
    def beacon_ids(self) -> list[str]:
        return [a.beacon.id for a in self.representative]

    def weight_of(self, at: Attachment) -> float:
        return at.weight(self.w_nominal)


def nowcast_active(ctx: DataContext) -> bool:
    return ctx.horizon in rules.NOWCAST_HORIZONS


def station_nowcast(
    ctx: DataContext, site: Site, role: str, tl: PointTimeline, t: datetime, big_valley: bool = False
) -> StationNowcast | None:
    """Nowcast d'un site à l'instant t (None hors horizons de nowcasting ou sans balise rattachée)."""
    if not nowcast_active(ctx):
        return None
    atts = site_attachments(ctx, site, role, tl, big_valley)
    dt = max(0.0, (t - ctx.reference_time).total_seconds() / 60.0)
    w_nom = rules.beacon_weight_by_minutes(dt)
    nc = StationNowcast(role=role, site=site, eval_time=t, dt_min=dt, w_nominal=w_nom, attachments=atts)
    rep = [a for a in atts if a.representative and a.weight(w_nom) > 0]
    nc.representative = rep
    if not rep:
        key = ("nearest", role, site.id)
        if key not in ctx.station_cache:
            ctx.station_cache[key] = nearest_reading_text(ctx, nc, site, role)
        nc.nearest_text = ctx.station_cache[key]
        return nc
    ws = [a.weight(w_nom) for a in rep]
    sw = sum(ws)
    nc.weight = max(ws)
    dv = sum(w * a.dv for w, a in zip(ws, rep, strict=True)) / sw
    nc.speed_bias_kmh = max(-rules.NOWCAST_MAX_SPEED_BIAS_KMH, min(rules.NOWCAST_MAX_SPEED_BIAS_KMH, dv))
    dir_rep = [(w, a) for w, a in zip(ws, rep, strict=True) if a.dd_valid]
    if dir_rep:
        dd = sum(w * a.dd for w, a in dir_rep) / sum(w for w, _ in dir_rep)
        nc.dir_bias_deg = max(-rules.NOWCAST_MAX_DIR_BIAS_DEG, min(rules.NOWCAST_MAX_DIR_BIAS_DEG, dd))
        nc.dir_valid = True
    gust_src = [a for a in rep if not a.synoptic and a.beacon.wind_gust_kmh is not None]
    if gust_src:
        nc.beacon_gust_kmh = max(a.beacon.wind_gust_kmh or 0.0 for a in gust_src)
    if role == "takeoff":
        nc.mismatch = abs(nc.speed_bias_kmh) > rules.BEACON_CONTRADICTION_KMH or abs(nc.dir_bias_deg) > rules.BEACON_CONTRADICTION_DEG
        nc.coherent = abs(nc.speed_bias_kmh) < rules.BEACON_COHERENT_KMH and abs(nc.dir_bias_deg) < rules.BEACON_COHERENT_DEG
    else:  # §12.4 : contradictoire si écart > 10 km/h ou > 45° (vent ≥ 8 km/h) ; cohérente sinon
        nc.mismatch = abs(nc.speed_bias_kmh) > rules.BEACON_CONTRADICTION_KMH or (
            nc.dir_valid and abs(nc.dir_bias_deg) > rules.BEACON_CONTRADICTION_DEG
        )
        nc.coherent = not nc.mismatch
    trends = [eval_trend(a, ctx.horizon, dt) for a in rep]
    trends = [x for x in trends if x is not None]
    if trends:
        # la tendance la plus défavorable (taux de hausse le plus fort), parmi les balises représentatives
        nc.trend = max(trends, key=lambda x: (x.rate_kmh_h, x.attachment.factor))
    for a in rep:
        b = a.beacon
        nc.details.append(
            f"{b.name} : {b.wind_speed_kmh:.0f} km/h ({b.wind_gust_kmh or 0:.0f} en rafales) du "
            f"{_dir(b.wind_direction_deg)} contre {a.model_speed_kmh:.0f} km/h du {_dir(a.model_dir_deg)} prévus"
        )
    return nc


def fuse(
    nc: StationNowcast | None, model_v: float, model_d: float, model_g: float, horizon: str
) -> tuple[float, float, float, float, float]:
    """(v_fusion, direction, rafale retenue, v_retenu, rafale retenue avec extrapolation)."""
    if nc is None or not nc.has_representative:
        return model_v, model_d, model_g, model_v, model_g
    v = max(0.0, model_v + nc.weight * nc.speed_bias_kmh)
    d = model_d
    if nc.dir_valid and model_v >= DIR_MIN_WIND_KMH:
        d = (model_d + nc.weight * nc.dir_bias_deg) % 360.0
    g = max(v, model_g * (v / model_v) if model_v > 1 else v * rules.GUST_FACTOR_DEFAULT)
    if nc.beacon_gust_kmh is not None and horizon in rules.BEACON_GUST_HORIZONS:
        g = max(g, nc.beacon_gust_kmh)
    v_ret, g_ret = v, g
    if nc.trend is not None and nc.trend.v_ext is not None:
        v_ret = max(v, nc.trend.v_ext)
        g_ret = max(g, nc.trend.g_ext or 0.0, v_ret)
    return v, d, g, v_ret, g_ret


# =============================================================================================
# Constats de tendance (§12.2) et absence de balise (§12.3)
# =============================================================================================
def trend_findings(nc: StationNowcast | None, horizon: str, v_retained: float, ridge: bool = False) -> list[Finding]:
    if nc is None or nc.trend is None:
        return []
    te = nc.trend
    b = te.attachment.beacon
    landing = nc.role != "takeoff"
    where = "à l'atterro" if landing else "au déco"
    tr, imp = rules.TREND_1H, rules.TREND_IMPACT
    if landing:
        wind_thr, gust_thr, gust_code = rules.LANDING_WIND_MAX_KMH, rules.LANDING_GUST_MAX_KMH, "LANDING_WIND"
    else:
        wind_thr = rules.RIDGE["max_kmh"] if ridge else rules.TAKEOFF_WIND_MAX_KMH
        gust_thr = rules.RIDGE_GUST_MAX_KMH if ridge else rules.TAKEOFF_GUST_MAX_KMH
        gust_code = "TAKEOFF_GUSTS"
    out: list[Finding] = []
    win = "1 h" if abs(te.window_min - 60) <= 10 else f"{te.window_min:.0f} min"
    head = f"{b.name} : {te.v_now:.0f} km/h (raf. {te.gust_now:.0f}), {te.v_now - te.v0:+.0f} km/h en {win}"
    # hausse du vent moyen
    inc = tr["wind_increase_kmh_per_h"]
    if te.rate_kmh_h > inc["danger"] and horizon in imp["wind_increase_high"]:
        lvl = imp["wind_increase_high"][horizon]
        out.append(Finding("WIND_INCREASING", f"Le vent forcit {where}",
                           f"{head} : hausse de {te.rate_kmh_h:.0f} km/h/h, changement de régime (front de rafales, orage, "
                           f"percée de foehn ou brise anormalement forte).", level_risk={lv: lvl for lv in rules.LEVELS}))  # fmt: skip
    elif te.rate_kmh_h > inc["caution"] and horizon in imp["wind_increase"]:
        lvl = imp["wind_increase"][horizon]
        v_eval = max(v_retained, te.v_ext or 0.0)
        risk = {}
        for lv in rules.LEVELS:
            if lvl == "caution":
                risk[lv] = "caution" if v_eval >= tr["caution_min_ratio_to_threshold"] * wind_thr[lv] else "info"
            else:
                risk[lv] = lvl
        when = f" vers {_hm(nc.eval_time)}" + (" (ton arrivée)" if landing else " (début du créneau)")
        ext = f" Environ {te.v_ext:.0f} km/h (raf. {te.g_ext:.0f}) attendus{when}." if te.v_ext is not None else ""
        advice = " Pose-toi tôt, sans t'éloigner de l'atterro." if landing else " Décolle tôt dans le créneau ou renonce."
        out.append(Finding("WIND_INCREASING", f"Le vent forcit {where}",
                           f"{head}, le vent forcit.{ext}{advice}", level_risk=risk))  # fmt: skip
    # rotation / bascule
    dc = abs(te.direction_change_deg)
    rv, ro = tr["reversal"], tr["rotation"]
    if dc >= rv["deg"] and te.v0 >= rv["min_wind_kmh"] and te.v_now >= rv["min_wind_kmh"] and horizon in imp["reversal"]:
        lvl = imp["reversal"][horizon]
        risk = {lv: (rv["level"][lv] if lvl == "by_level" else lvl) for lv in rules.LEVELS}
        out.append(Finding("WIND_SHIFT", "Le vent tourne",
                           f"{b.name} : bascule du vent de {dc:.0f}° en {te.window_min:.0f} min {where} (bascule de brise, "
                           "convergence ou front d'orage).", level_risk=risk))  # fmt: skip
    elif dc >= ro["caution_deg"] and te.v0 >= ro["min_wind_kmh"] and te.v_now >= ro["min_wind_kmh"] and horizon in imp["rotation"]:
        lvl = imp["rotation"][horizon]
        out.append(Finding("WIND_SHIFT", "Le vent tourne", f"{b.name} : le vent a tourné de {dc:.0f}° en {te.window_min:.0f} min {where}.",
                           level_risk={lv: lvl for lv in rules.LEVELS}))  # fmt: skip
    # rafale max de l'heure
    gm = te.gust_max_kmh
    if gm is not None:
        over = tr["gust_max_over_threshold_kmh"]
        risk: dict[str, str | None] = {}
        for lv in rules.LEVELS:
            if gm > gust_thr[lv] + over["danger"] and horizon in imp["gust_max_high"]:
                risk[lv] = imp["gust_max_high"][horizon]
            elif gm > gust_thr[lv] + over["caution"] and horizon in imp["gust_max"]:
                risk[lv] = imp["gust_max"][horizon]
            else:
                risk[lv] = None
        if any(risk.values()):
            title = "Rafales à l'atterrissage" if landing else "Rafales au déco"
            out.append(Finding(gust_code, title, f"{b.name} : rafale max de {gm:.0f} km/h sur la dernière heure {where}.",
                               level_risk=risk))  # fmt: skip
    return out


def nearest_reading_text(ctx: DataContext, nc: StationNowcast | None, site: Site, role: str) -> str:
    """« (la plus proche, Pioupiou X, est à 4,2 km et 230 m plus haut) » ou « (aucune balise à moins de 15 km) »."""
    cand = None
    if nc is not None and nc.attachments:
        cand = min(nc.attachments, key=lambda a: a.distance_km)
    if cand is None:
        cand = nearest_unattached(ctx, site, role, set())
    if cand is None:
        return f"aucune balise à moins de {rules.BEACON_SEARCH_RADIUS_KM:.0f} km"
    dz = cand.alt_diff_m
    alt = ""
    if dz is not None and abs(dz) >= 30:
        alt = f" et {abs(dz):.0f} m plus {'haut' if dz > 0 else 'bas'}"
    why = f" : {cand.reason}" if cand.reason and not cand.reason.startswith("à ") else ""
    return f"la plus proche, {cand.beacon.name}, est à {km(cand.distance_km)} km{alt}{why}"


def no_landing_beacon_finding(
    ctx: DataContext, nc: StationNowcast | None, landing: Site, arrival: datetime, v_model: float
) -> Finding | None:
    """NO_LANDING_BEACON (§12.3) : caution NON bloquante (arrivée 12-18 h légales, horizons ≤ 1 h) ou info."""
    p = rules.NO_LANDING_BEACON
    if ctx.horizon not in p["level"] or (nc is not None and nc.has_representative):
        return None
    from app.engine.conditions import legal_time

    lvl = p["level"][ctx.horizon]
    h0, h1 = p["caution_legal_hours"]
    if lvl == "caution" and not (h0 <= legal_time(arrival).hour < h1):
        lvl = "info"
    near = nc.nearest_text if nc is not None and nc.nearest_text else nearest_reading_text(ctx, nc, landing, "landing")
    detail = (
        f"Pas de balise représentative à l'atterro ({near}). "
        f"Vent d'arrivée estimé par le modèle seul : environ {v_model:.0f} km/h, brise comprise. En vol, regarde la manche "
        "à air, les drapeaux et la surface du lac, ou demande le vent par radio à un pilote posé."
    )
    return Finding("NO_LANDING_BEACON", "Pas de balise à l'atterro", detail, caution=lvl == "caution", info=lvl == "info",
                   blocks_go=False)  # fmt: skip


def landing_band_start(ctx: DataContext, nc: StationNowcast | None) -> float | None:
    """Bande marginale de l'atterro dès 72 % quand aucune balise n'est représentative (horizons ≤ 1 h)."""
    f = rules.NO_LANDING_BEACON["landing_marginal_band_factor"].get(ctx.horizon)
    if f is None or (nc is not None and nc.has_representative):
        return None
    return rules.MARGINAL_BAND * f


def landing_confidence_factor(ctx: DataContext, nc: StationNowcast | None) -> float:
    if nc is not None and nc.has_representative:
        c = rules.LANDING_BEACON_CONFIDENCE_FACTOR
        return c["contradictory"] if nc.mismatch else c["coherent"]
    return rules.NO_LANDING_BEACON["confidence_factor"].get(ctx.horizon, 1.0)


# =============================================================================================
# Lectures publiées (StationReading)
# =============================================================================================
def _dir(deg: float | None) -> str:
    from app.engine.conditions import dir_label

    return "—" if deg is None else dir_label(deg)


def _hm(t: datetime) -> str:
    from app.engine.conditions import fmt_hm

    return fmt_hm(t)


def coherence_text(at: Attachment) -> str:
    if at.stale or at.beacon.wind_speed_kmh is None:
        return ""
    parts = []
    if abs(at.dv) < rules.BEACON_COHERENT_KMH and (not at.dd_valid or abs(at.dd) < rules.BEACON_COHERENT_DEG):
        return "conforme à la prévision"
    if at.dv >= rules.BEACON_COHERENT_KMH:
        parts.append(f"plus fort que prévu ({at.dv:+.0f} km/h)")
    elif at.dv <= -rules.BEACON_COHERENT_KMH:
        parts.append(f"plus faible que prévu ({at.dv:+.0f} km/h)")
    if at.dd_valid and abs(at.dd) >= rules.BEACON_COHERENT_DEG:
        parts.append(f"direction décalée de {abs(at.dd):.0f}° par rapport au modèle")
    return ", ".join(parts) if parts else "conforme à la prévision"


def reading_comment(at: Attachment, weight: float) -> str:
    b = at.beacon
    age = f"il y a {at.age_min:.0f} min"
    if b.wind_speed_kmh is None:
        head = f"{b.name} : aucune mesure transmise"
    else:
        gust = f", rafales {b.wind_gust_kmh:.0f}" if b.wind_gust_kmh is not None else ""
        head = f"{b.name} : {b.wind_speed_kmh:.0f} km/h {_dir(b.wind_direction_deg)}{gust}, {age}"
    if at.stale:
        mute = f"muette depuis {at.age_min:.0f} min" if b.wind_speed_kmh is not None else "balise muette"
        return f"{head} — {mute} : ignorée (comptée comme absente)."
    tail: list[str] = []
    if at.representative:
        tail.append(coherence_text(at))
        tl = trend_label(b)
        tail.append(tl if tl != "tendance indisponible" else "tendance indisponible")
        if at.outlier:
            tail.append("possiblement abritée ou trop exposée (écart à la médiane des balises > 10 km/h)")
        if at.synoptic:
            tail.append("balise décalée en altitude : seule la composante synoptique est corrigée")
    else:
        tail.append(f"non représentative : {at.reason}" if at.reason else "non représentative")
    if at.elevation_source == "dem":
        tail.append("altitude estimée (MNT)")
    elif at.elevation_source == "unknown":
        tail.append("altitude inconnue")
    if at.representative:
        tail.append(f"poids {weight * 100:.0f} % dans la correction")
    return f"{head} — " + " ; ".join(x for x in tail if x) + "."


__all__ = [
    "Attachment",
    "StationNowcast",
    "TrendEval",
    "attach",
    "beacon_elevation",
    "breeze_factor",
    "fuse",
    "landing_band_start",
    "landing_confidence_factor",
    "name_has_keyword",
    "name_mentions_site",
    "no_landing_beacon_finding",
    "reading_comment",
    "site_attachments",
    "station_nowcast",
    "trend_findings",
    "trend_label",
]
