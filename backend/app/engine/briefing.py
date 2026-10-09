"""Textes destinés au pilote : titre, résumé, briefing (ordre §7.1 du cahier des charges), checklist."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.engine import rules
from app.engine.conditions import dir_label, fmt_hm
from app.engine.stations import Attachment, coherence_text, trend_label
from app.meteo.thermals import thermal_quality_label

if TYPE_CHECKING:  # pragma: no cover
    from app.engine.planner import Candidate

TYPE_LABEL = {
    "plouf": "plouf",
    "restitution": "vol de restitution",
    "local_thermal": "local thermique",
    "ridge": "soaring",
    "xc": "cross",
}
XC_SHAPE_LABEL = {"out_and_return": "aller-retour", "triangle": "triangle plat", "fai_triangle": "triangle FAI"}
VERDICT_LABEL = {"go": "GO", "marginal": "MARGINAL", "no_go": "NO-GO"}


def duration_label(minutes: float) -> str:
    m = int(round(minutes))
    if m < 60:
        return f"{m} min"
    h, r = divmod(m, 60)
    return f"{h}h{r:02d}" if r else f"{h}h"


def round_alt(x: float, horizon: str) -> int:
    step = 100 if horizon in ("24h", "48h", "12h") else 50
    return int(round(x / step) * step)


def title(c: Candidate) -> str:
    kind = TYPE_LABEL.get(c.variant, c.variant)
    if c.variant == "xc" and c.route.xc_subtype:
        kind = f"cross {XC_SHAPE_LABEL[c.route.xc_subtype]} {c.route.distance_km:.0f} km"
    return f"{c.takeoff.name} → {c.landing.name} · {kind} {duration_label(c.duration_min)}"


def summary(c: Candidate) -> str:
    tw = c.takeoff_wind
    wind = (
        "vent nul au déco"
        if tw.angle.calm
        else f"vent {dir_label(tw.direction_deg)} {tw.speed_kmh:.0f} km/h (rafales {tw.gust_kmh:.0f})"
    )
    kind = TYPE_LABEL.get(c.variant, c.variant)
    if c.variant == "xc" and c.route.xc_subtype:
        kind = f"cross en {XC_SHAPE_LABEL[c.route.xc_subtype]} de {c.route.distance_km:.0f} km"
    s = f"{kind.capitalize()} de {duration_label(c.duration_min)} depuis {c.takeoff.name}, {wind}"
    if c.vario >= rules.THERMAL_USABLE_MIN_MS and c.variant in ("local_thermal", "xc"):
        s += f", thermiques {c.vario:.1f} m/s jusqu'à {round_alt(c.max_alt, c.horizon)} m"
    s += "."
    if c.duration_note:
        s += " " + c.duration_note
    return s


def briefing(c: Candidate) -> list[str]:
    out: list[str] = []
    lvl = rules.LEVEL_LABEL_FR[c.difficulty]
    v = VERDICT_LABEL[c.flyability]
    line = f"{v} pour {lvl} — confiance {c.confidence * 100:.0f} %"
    why = [r.title for r in c.risks if r.level == "caution" and r.code != "MOCK_DATA"]
    if c.flyability == "marginal" and why:
        line += f" (vigilance : {', '.join(dict.fromkeys(why[:3]))})"
    if c.mock:
        line += ". ⚠ DONNÉES SYNTHÉTIQUES (démo hors-ligne) : ne pas utiliser pour décider d'un vol"
    out.append(line + ". L'analyse sur place prime toujours.")
    # §12.5 : horizons ≤ 1 h, la lecture des balises (déco + atterro) vient juste après le verdict
    short = c.horizon in rules.NOWCAST_WINDOW_START_MIN
    if short:
        out.append(beacons_line(c))

    # 2. créneau
    end_reason = c.landing_cap_reason or "fin de la fenêtre de vol"
    out.append(
        f"Créneau : décoller entre {fmt_hm(c.window_start)} et {fmt_hm(c.window_end)} (heure légale), "
        f"être posé avant {fmt_hm(c.latest_landing)} ({end_reason}). Coucher du soleil à {fmt_hm(c.sunset)}."
        if c.sunset
        else f"Créneau : décoller entre {fmt_hm(c.window_start)} et {fmt_hm(c.window_end)} (heure légale)."
    )
    # 3. situation générale
    a = c.takeoff_wind.hour
    v3, d3 = a.profile.wind(3000)
    v15, d15 = a.profile.wind(1500)
    sky = "ciel dégagé" if a.cloud_cover_pct < 20 else ("ciel partiellement nuageux" if a.cloud_cover_pct < 70 else "ciel très nuageux")
    stab = "masse d'air stable" if a.cape_j_kg < 300 else ("masse d'air instable" if a.cape_j_kg >= 800 else "instabilité modérée")
    out.append(
        f"Situation : flux de {dir_label(d3)} {v3:.0f} km/h à 3000 m ({dir_label(d15)} {v15:.0f} km/h à 1500 m), "
        f"{sky} ({a.cloud_cover_pct:.0f} %), {stab} (CAPE {a.cape_j_kg:.0f} J/kg)."
    )
    # 4. vent
    tw = c.takeoff_wind
    wind_to = "nul (< 5 km/h)" if tw.angle.calm else f"{dir_label(tw.direction_deg)} {tw.speed_kmh:.0f} km/h, rafales {tw.gust_kmh:.0f}"
    aloft = ", ".join(
        f"{z} m : {dir_label(a.profile.wind(z)[1])} {a.profile.wind(z)[0]:.0f}" for z in (1500, 2000, 3000) if z > c.takeoff.elevation_m - 200
    )
    lw = c.landing_wind
    breeze = " (brise de vallée incluse ×{:.2f})".format(lw.breeze_factor) if lw.breeze_factor > 1 else ""
    out.append(
        f"Vent : au déco {wind_to} ; en altitude {aloft} km/h ; à l'atterro vers {fmt_hm(lw.time)} "
        f"{dir_label(lw.direction_deg)} {lw.speed_kmh:.0f} km/h, rafales {lw.gust_kmh:.0f}{breeze}."
    )
    if not short and c.horizon in rules.NOWCAST_HORIZONS:
        out.append(beacons_line(c))
    # 5. aérologie
    cw = c.convection
    if cw.start and cw.end:
        thermo = (
            f"Aérologie : thermiques de {fmt_hm(cw.start)} à {fmt_hm(cw.end)} (pic vers {fmt_hm(cw.peak) if cw.peak else '—'}), "
            f"vario moyen {c.vario:.1f} m/s ({thermal_quality_label(c.vario)}), plafond utile {round_alt(c.usable, c.horizon)} m"
        )
    else:
        thermo = f"Aérologie : pas de convection exploitable prévue (vario {c.vario:.1f} m/s)"
    if a.cloud_base_m is not None:
        thermo += f", base des cumulus {round_alt(a.cloud_base_m, c.horizon)} m"
    elif cw.start:
        thermo += ", thermiques bleus (pas de cumulus)"
    thermo += f", risque de surdéveloppement {dict(low='faible', moderate='modéré', high='élevé')[cw.overdevelopment_risk]}"
    if cw.overdevelopment_time and cw.overdevelopment_risk != "low":
        thermo += f" (vers {fmt_hm(cw.overdevelopment_time)})"
    out.append(thermo + ".")
    # 6. décollage
    tech = "gonflage face voile conseillé" if tw.speed_kmh >= 12 else "gonflage dos voile possible"
    orient = ", ".join(c.takeoff.orientations) or "orientation inconnue"
    deco = f"Décollage : {c.takeoff.name} ({c.takeoff.elevation_m:.0f} m, orienté {orient}), {tech}."
    if c.takeoff.restrictions:
        deco += f" Consigne du site : {c.takeoff.restrictions}"
    out.append(deco)
    # 7. itinéraire
    tps = [w for w in c.route.waypoints if w.type in ("turnpoint", "thermal_trigger")]
    if tps:
        legs = " → ".join(
            f"{w.name}" + (f" (~{fmt_hm(c.window_start_eta(w.eta_min))})" if w.eta_min is not None else "") for w in tps
        )
        out.append(f"Itinéraire : {c.takeoff.name} → {legs} → {c.landing.name} ({c.route.distance_km:.1f} km).")
    for dp in c.route.decision_points[:4]:
        out.append(f"Point de décision : {dp}")
    for note in c.route.notes:
        out.append(note)
    # 8. atterrissage
    approach = (
        f"approche face au vent ({dir_label(lw.direction_deg)}), PTU côté {dir_label((lw.direction_deg + 180) % 360)}"
        if lw.speed_kmh >= rules.CALM_WIND_KMH
        else "vent faible : approche dans l'axe du terrain, PTU côté déco"
    )
    land = f"Atterrissage : {c.landing.name} ({c.landing.elevation_m:.0f} m), {approach}"
    if c.alternates:
        land += " ; secours : " + ", ".join(a_.name for a_ in c.alternates[:3])
    land += "."
    if c.landing.restrictions:
        land += f" Consigne : {c.landing.restrictions}"
    out.append(land)
    # 9. espaces aériens et zones sensibles
    near = [w for w in c.airspaces if w.min_distance_km <= 5.0]
    if near:
        out.append(
            "Espaces aériens : "
            + " ; ".join(
                f"{w.name} (classe {w.airspace_class}, {w.floor_m:.0f}-{w.ceiling_m:.0f} m) à {w.min_distance_km:.1f} km"
                + (" — TRAVERSÉ" if w.intersects_route else "")
                for w in near[:4]
            )
            + f". Plafond retenu {c.max_alt:.0f} m (FL115 ≈ {rules.FL115_M_STANDARD:.0f} m). Vérifier NOTAM / SUP AIP / AZBA."
        )
    else:
        out.append(f"Espaces aériens : rien à moins de 5 km de la route ; plafond retenu {c.max_alt:.0f} m. Vérifier NOTAM.")
    for r in c.risks:
        if r.code in ("SENSITIVE_AREA", "NATIONAL_PARK"):
            out.append(f"Zone sensible : {r.detail}")
    # 10. risques du jour
    specific = [r for r in c.risks if r.level in ("caution", "danger") and r.code not in ("SENSITIVE_AREA", "NATIONAL_PARK", "MOCK_DATA")]
    if specific:
        out.append("Risques du jour : " + " ; ".join(f"{r.title}" for r in specific[:6]) + ".")
    # 11. logistique & sécurité
    out.append(
        f"Sécurité : radio vol libre {rules.RADIO_FREQ_MHZ} MHz, urgence {rules.EMERGENCY_NUMBER} "
        f"(position déco {c.takeoff.lat:.4f}, {c.takeoff.lon:.4f}) ; prévenir le chauffeur / un proche de la route et de l'heure de retour"
        + (f" ; coucher du soleil {fmt_hm(c.sunset)}." if c.sunset else ".")
    )
    if c.takeoff.access:
        out.append(f"Accès : {c.takeoff.access} (prévoir 15-30 min de préparation au déco).")
    return out


def _reading_short(a: Attachment, landing: bool) -> str:
    b = a.beacon
    g = f" (raf. {b.wind_gust_kmh:.0f})" if b.wind_gust_kmh is not None else ""
    txt = f"{dir_label(b.wind_direction_deg) + ' ' if b.wind_direction_deg is not None else ''}{b.wind_speed_kmh:.0f} km/h{g}"
    tl = trend_label(b)
    if tl != "tendance indisponible":
        txt += f", {tl}"
        t = b.trend
        if t is not None and t.speed_change_kmh * 60.0 / t.window_min > rules.TREND_1H["wind_increase_kmh_per_h"]["caution"]:
            txt += ", la brise forcit" if landing else ", le vent forcit"
    coh = coherence_text(a)
    if coh:
        txt += f", {coh}"
    return txt


def beacons_line(c: Candidate) -> str:
    """Lecture des balises du déco et de l'atterro (§12.5) : valeur, âge, tendance, cohérence avec la prévision ;
    absence de balise représentative dite explicitement, avec la confiance réduite."""
    tw, lw = c.takeoff_wind, c.landing_wind
    nc_to, nc_l = tw.nowcast, lw.nowcast
    top = c.landing.id == c.takeoff.id
    has_to = nc_to is not None and nc_to.has_representative
    has_l = top or (nc_l is not None and nc_l.has_representative)
    parts: list[str] = []
    ages: list[float] = []
    if has_to:
        a = nc_to.representative[0]
        ages.append(a.age_min)
        parts.append(f"déco ({a.beacon.name}) {_reading_short(a, False)}")
    if not top and nc_l is not None and nc_l.has_representative:
        a = nc_l.representative[0]
        ages.append(a.age_min)
        txt = f"atterro ({a.beacon.name}) {_reading_short(a, True)}"
        te = nc_l.trend
        if te is not None and te.v_ext is not None:
            txt += (f" : environ {te.v_ext:.0f} km/h (raf. {te.g_ext:.0f}) attendus à ton arrivée vers {fmt_hm(lw.time)}, "
                    f"alors que le modèle en prévoit {lw.model_speed_kmh:.0f}")  # fmt: skip
        parts.append(txt)
    conf = f"confiance réduite ({c.confidence * 100:.0f} %)"
    if not parts:
        return (
            f"Pas de balise représentative au déco ni à l'atterro ({nearest_reading_text_safe(c)}) : vent estimé par le "
            f"modèle seul, {conf}. Regarde la manche à air de l'atterro avant de décoller, ou demande le vent par radio."
        )
    line = f"Balises (il y a {max(ages):.0f} min) : " + " ; ".join(parts) + "."
    if not has_to:
        line += " Pas de balise représentative au déco : vent du déco estimé par le modèle seul."
    if not has_l:
        breeze = ", brise comprise" if lw.breeze_factor > 1 else ""
        line += (
            f" Pas de balise à l'atterro ({nearest_reading_text_safe(c)}) : vent d'arrivée estimé par le modèle seul "
            f"(environ {lw.model_speed_kmh:.0f} km/h{breeze}), {conf}. Regarde la manche à air de l'atterro avant de décoller."
        )
    return line


def nearest_reading_text_safe(c: Candidate) -> str:
    nc = c.landing_wind.nowcast
    if nc is not None and nc.nearest_text:
        return nc.nearest_text
    return "aucune balise rattachable"


def checklist(c: Candidate) -> list[str]:
    items = [
        "Météo revue il y a moins d'1 h (balises déco + atterro), plan B connu.",
        "Espace aérien et NOTAM / activations (R, ZRT, AZBA) vérifiés pour le jour.",
        "Parachute de secours : poignée accessible et verrouillée, aiguilles en place, repliage < 12 mois.",
        "Sellette : cuissardes, ventrale réglée, mousquetons verrouillés, accélérateur connecté et libre.",
        "Casque jugulaire fermée ; gants, lunettes, vêtements adaptés au plafond (−0,65 °C / 100 m).",
        "Voile : visite pré-vol, suspentes démêlées, élévateurs non vrillés, freins libres, voile en arc.",
        "Instruments : vario/GPS chargés, tâche XCTrack/GPX chargée, live tracking activé, téléphone chargé.",
        f"Radio allumée sur la fréquence du jour ({rules.RADIO_FREQ_MHZ} MHz), test de réception.",
        "Eau, nourriture" + (" (cross)" if c.variant == "xc" else "") + ", kit de secours / couverture de survie.",
        "Plan de vol communiqué à un proche ou au chauffeur (site, route, heure de retour).",
        "Contrôle final au déco (PRÉVOL) : attaches, casque, suspentes, voile, vent et espace devant libres.",
    ]
    if c.horizon in rules.NOWCAST_WINDOW_START_MIN:  # §12.5
        items.insert(1, "Regarder la manche à air de l'atterro avant de décoller (jumelles), ou demander le vent par radio.")
    return items
