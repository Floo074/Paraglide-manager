# Journal de revue métier — backend & frontend

> Tenu par l'expert pilote (référent métier). Statuts : **envoyé** · **corrigé** · **refusé** (avec justification) · **en attente** · **remonté au coordinateur**.
> Références : `cahier-des-charges-pilote.md` (CDC), `scenarios-validation.md` (SV).

## État du code au début de la revue (phase 2)

- `backend/app/meteo/` (thermo, profile, solar, types) présent. `engine/` et `rules.py` pas encore écrits.
- Remarques sur l'existant :
  - `meteo/thermo.py` : Espy 125 m/°C ✔ ; LCL par itération ✔ ; profil de particule sec puis saturé ✔.
  - `meteo/profile.py` : niveaux de pression ignorés à moins de 150 m au-dessus du sol du modèle ✔ ; interpolation du vent en (u, v) ✔. **Point d'attention** : le vent au déco doit venir de `VerticalProfile.wind(alt_déco)` et non du 10 m du point de grille (lot 1.4).
  - `meteo/solar.py` : heure solaire avec équation du temps ✔ (base des règles aérologiques en heure solaire, CDC §0).

## Lots envoyés au backend

### Lot 1 : exigences structurantes avant l'écriture d'`engine/` et de `rules.py` (envoyé)

| # | Demande | Statut |
|---|---|---|
| 1.1 | `rules.py` = bloc YAML CDC §11 (mêmes clés et valeurs) | **corrigé** (vérifié dans `engine/rules.py`, partie 1 fidèle) |
| 1.2 | Verdict non compensatoire, `score ≤ 40 + min(sous-scores sécurité)`, seuils go 65 / no-go 45 | accepté, en cours d'implémentation |
| 1.3 | Bande marginale 80-100 % ; interpolation des sous-scores ; vent nul = 80 | accepté, en cours d'implémentation |
| 1.4 | Vent au déco interpolé à l'altitude réelle du déco ; rafales mises à l'échelle | accepté, en cours d'implémentation |
| 1.5 | Écart angulaire / travers / arrière / composante de travers | accepté, en cours d'implémentation |
| 1.6 | Dévent : vent à déco + 300 m ≥ 15 km/h venant de > 120° de l'axe → no-go `LEE_SIDE` | accepté, en cours d'implémentation |
| 1.7 | Vent en altitude seulement sur les niveaux atteints ; no-go absolu 45 km/h, et 50 km/h à 3000 m | accepté, en cours d'implémentation |
| 1.8 | Atterro évalué à l'heure d'arrivée + brise de vallée × 1.3 (13-17 h) | accepté, en cours d'implémentation |
| 1.9 | Formule de finesse sol (k niveau, V_air 37, composante vent, marge d'arrivée) | accepté, en cours d'implémentation |
| 1.10 | Plafond utile = min(plafond, base − 300) ; altitude max ≤ FL115 − 100 m | accepté, en cours d'implémentation |
| 1.11 | Calcul de `difficulty` du plan et rejet si > niveau demandé | accepté, en cours d'implémentation |
| 1.12 | Beginner : pas de cross, ≤ 45 min, créneau hors pic thermique | accepté, en cours d'implémentation |
| 1.13 | Fin de créneau = min(fin convection + 30 min, surdév − 1 h, coucher − 30 min) ; ne pas étirer la durée | accepté, en cours d'implémentation |
| 1.14 | Diversité : au plus 2 plans par déco | accepté, en cours d'implémentation |
| 1.15 | Catalogue des codes `Risk` standardisés | accepté, en cours d'implémentation |
| 1.16 | Point d'entrée moteur pour les tests de scénarios | **accepté** : `app.engine.scenario.run_scenario(spec) -> PlanResponse` |

### Lot 2 : recalibrages après rédaction des scénarios, format des tests, zones sensibles (envoyé)

| # | Demande (actuel → attendu) | Statut |
|---|---|---|
| 2.1 | `GLIDE_K` 0.50/0.60/0.65/0.70 → 0.65/0.70/0.72/0.75 ; `LANDING_ARRIVAL_MARGIN_M` 200/150/120/100 → 100/100/100/80, bornée à 25 % du dénivelé ; courbe du sous-score de finesse ; `GLIDE_MARGIN`. Raison : Forclaz→Doussard (finesse 4,9) devenait marginal à tous les niveaux. | accepté |
| 2.2 | Facteur de rafale non bloquant (caution seulement, si moyenne ≥ 15) | accepté |
| 2.3 | Rotation du vent mesurée entre déco + 300 m et le plafond utile | accepté |
| 2.4 | Soaring : seuils de vent ridge jusqu'à déco + 300 m ; vent d'atterro en top landing ; pas de contrôle de finesse en top landing | accepté |
| 2.5 | Vent arrière ≥ 5 km/h ⇒ au mieux marginal | accepté |
| 2.6 | Fenêtres orage [déco, atterro + 1 h] / [déco, atterro + 2 h] ; heure de surdév tirée de la timeline ; jour `high` ⇒ marginal | accepté |
| 2.7 | Coucher : no-go après le coucher, caution dans les 30 dernières minutes | accepté |
| 2.8 | Jamais de rejet pour la durée seule | accepté |
| 2.9 | `window.start ∈ [cible − 30 min, cible + 3 h]` | accepté |
| 2.10 | Horizons 30m/1h : rafale = max(balise, fusion) | accepté |
| 2.11 | `go_min_confidence` 0.5 → `go_min_confidence_ratio` 0.75 × base de l'horizon | accepté |
| 2.12 | Mock : confiance affichée ≤ 0,3 mais verdict non plafonné ; `MOCK_DATA` non bloquant | accepté |
| 2.13 | Code `SITE_LEVEL` | accepté |
| 2.14 | `VALLEY_BREEZE` info/caution, `LANDING_WIND` danger | accepté |
| 2.15 | Espaces aériens interdits par classe (A, B, C, D) ou type P, pas par type CTR/TMA | accepté |
| 2.16 | Consignes cœurs de parcs / zones Biodiv'Sports (textes fournis) | accepté |
| 2.17 | Briefing (verdict en tête, 112, 143,9875) et contenu minimal de la checklist | accepté |
| clés spec | `landing_temperature_c` / `landing_dew_point_c` / `landing_cloud_cover_low_pct`, `models`, `winds_aloft` à altitudes libres, clés `expect` étendues | accepté |

Documents produits : `scenarios-validation.md` (lecture humaine) et `scenarios-validation.yaml` (32 cas, format `run_scenario`). Le CDC passe en révision 2 (cohérente avec le lot 2).

### Lot 3 : revue des fixtures (sites, zones sensibles, espaces aériens) + champs de contrat + règles d'import ParaglidingEarth (envoyé)

| # | Demande | Statut |
|---|---|---|
| 3.1 | Couples déco→atterro suspects : `plaine-joux → passy` (finesse 7,2 avec marge, impossible pour un site école), `puy-de-dome-sud → laschamp` (7,8), `puy-de-dome-ouest → col-de-ceyssat` (6,6) ; `gourdon` à passer en advanced (6,6) | envoyé |
| 3.2 | Pilat `both` : déco = top landing pour le soaring ; plage = atterro de secours | envoyé |
| 3.3 | `restrictions` du site toujours reprises dans le briefing + `SITE_RESTRICTED` avec le texte | envoyé |
| 3.4 | Semnoz Est l'après-midi : rejet « déco passé à l'ombre » | envoyé |
| 3.5 | Texte des cœurs de parcs selon la consigne 2.16 (formulation prudente) | envoyé |
| 3.6 | R 46 d'activité inconnue → `AIRSPACE_ACTIVATION` caution | envoyé |
| 3.7 | Contrat : `window.latest_landing` et `sun {sunrise, sunset}` (optionnels) | envoyé |
| 3.8 | Règles d'import ParaglidingEarth (dédoublonnage, sans orientation, sans atterro, altitude vs MNT, sites fermés, landing plus haut que le déco) | envoyé |

Vérifications faites sur les fixtures : aucun déco n'est situé dans une zone sensible (test point-dans-polygone) ; Dents de Lanfon (Planfait) et Dent de Crolles (St-Hilaire) touchent les routes locales, ce qui est réaliste.
Essai d'accès direct à ParaglidingEarth depuis l'environnement de l'expert : connexion réinitialisée par le proxy. La revue des sites réels attend donc le mode live du backend.

### Lot 4 : relecture de `meteo/thermals.py` et `meteo/ensemble.py` (envoyé)

| # | Demande | Statut |
|---|---|---|
| 4.1 | `convection_window` : `od_time = min(first_cu + 3,5 h, 1re heure où le risque ≥ moderate)` (la formule actuelle est trop optimiste quand la CAPE monte avant first_cu + 3,5 h) | envoyé |
| 4.2 | Requête Open-Meteo avec `elevation=<altitude du site>` (déco et atterro séparément), sinon T2 trop chaud et plafond surestimé d'environ 1000 m en haute montagne | envoyé (confirmation demandée) |
| 4.3 | Dépassement d'un seuil par un seul modèle (rafales, CAPE, pluie) ⇒ Risk caution + verdict au mieux marginal ; ajouter `gust_max` à `Spread` | envoyé |
| 4.4 | `WEAK_THERMALS` (info) si thermiques exigés et vario < 1,0 m/s | envoyé |

Points validés tels quels : surchauffe +1 °C proportionnelle au rayonnement, Espy 125 m/°C, plafond utile = min(plafond, base − 300), W* de Deardorff avec zi = sommet sec, vario = W* − 1 réduit au-delà de 20 km/h de vent, mélange pondéré 35 % avec la hauteur de couche limite du modèle, définitions low/moderate/high du surdéveloppement (CDC §4.6), fenêtre de convection (couche limite ≥ 500 m et W* ≥ 1,2 au début, W* ≥ 1,0 à la fin), vitesse du vent moyennée sur les forces et non vectoriellement (prudent).

### Lot 5 : relecture de `engine/conditions.py` et `engine/findings.py` (envoyé)

| # | Demande | Statut |
|---|---|---|
| 5.1 | Critères de faisabilité (vent mini en soaring, plafond mini, vario mini) : `band=False`, `blocks_go=False` ; sous le minimum, pas de plan de ce type plutôt qu'un danger | envoyé |
| 5.2 | Brise d'atterro : rampe × 1,15 entre 12 et 13 h et entre 17 et 18 h, au lieu d'une marche d'escalier | envoyé |
| 5.3 | Composante de vent arrière au secteur le plus proche : vérifiée, conforme | constaté conforme |
| 5.4 | Dans un FlightPlan, `wind_10m` = vent RETENU au site (altitude du déco, nowcast, brise à l'atterro) ; à documenter dans le contrat | envoyé (décision expert) |

Validé tel quel : architecture des `Finding` évalués par niveau (seuil strict, bande 80-100 %, difficulté = plus petit niveau qui passe) ; nowcast (modèle + poids × écart balise, pondération par âge et par écart d'altitude, rafale max des balises aux horizons courts) ; vent de crête à déco + 300 m.

## Réponses du backend

- Lot 1 : tout accepté. Précision technique acceptée : le sol « lissé » du modèle = moyenne du MNT sur 2,5 km de rayon autour du déco ; le vent au déco est interpolé entre ce point 10 m et les niveaux de pression. Rafales = `gust_10m × v_déco / v_10m`, bornées à `v_déco + 25` (× 1,35 si le modèle ne fournit pas de rafales). ScoreItem `airspace` informatif (poids 0) : **accepté** côté expert (les espaces aériens restent un filtre dur).
- Lot 2 : tout accepté, en cours d'implémentation.

## Lots envoyés au frontend

### Lot F1 : contenu et ordre de la fiche plan, carte, libellés (envoyé)

| # | Demande | Statut |
|---|---|---|
| F1.1 | `mocks/rules.ts` aligné sur la révision 2 (glideK, arrivalMargin, ratio de confiance) + bandeau « Démo hors-ligne » | accepté |
| F1.2 | Fiche plan en 12 blocs ordonnés (verdict → créneau → vent → briefing → carte → aérologie → risques → atterro → espaces/zones → checklist + urgence → exports → détails repliés) | accepté |
| F1.3 | Contenu de la carte résumé d'un plan | accepté |
| F1.4 | Section « Pourquoi pas ces sites ? » (`rejected`) + écran « Rien de volable » | accepté |
| F1.5 | Priorité des couches de la carte principale | accepté |
| F1.6 | Libellés de niveau selon les brevets FFVL | accepté |
| F1.7 | Unités, heure légale, m AMSL | accepté |

Réponse du frontend : F1 accepté en totalité. Trois choix soumis :
- (a) « posé avant » = `min(window.end + durée, coucher − 30 min)` → **corrigé par l'expert** : `min(window.end + durée, coucher)`, en orange si l'heure dépasse coucher − 30 min. Champs backend `window.latest_landing` / `sun` demandés (lot 3.7) ;
- (b) couleurs selon le niveau choisi : validé, avec seuils de soaring pour les plans `ridge_soaring` et rafales d'atterro colorées ;
- (c) grilles météo désactivées par défaut sur la carte principale : validé, avec l'altitude affichée en gros dans la légende.

### Lot F2 : premiers composants (PlanCard, ResultsPanel, VerdictBanner, WindowBlock, planTimes) (envoyé)

| # | Demande | Statut |
|---|---|---|
| F2.1 | `wind_10m` d'un plan = vent retenu au site ; libellé « atterro à l'arrivée vers hh:mm » | envoyé |
| F2.2 | Lire `window.latest_landing` et `sun.sunset` tels que le backend les publiera dans le contrat | envoyé |
| F2.3 | Libellé du code `SITE_LEVEL` | envoyé |
| F2.4 | PlanCard : « posé avant », et « air calme » au lieu de « 0,0 m/s » | envoyé |
| F2.5 | Verdict : rappel « l'analyse sur place prime » pour GO et MARGINAL | envoyé |
| F2.6 | Ordre des blocs de la page plan (à vérifier une fois la page assemblée) | en attente |

## Désaccords remontés au coordinateur

_(aucun pour l'instant)_
