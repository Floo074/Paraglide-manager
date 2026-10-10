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
- Lots 3 et 4 : acceptés. Fixtures corrigées : Plaine-Joux avec un atterro à ~2,8 km ; atterros du Puy de Dôme rapprochés ; Gourdon passé en advanced ; Doussard déplacé hors de la RNN du Bout du Lac (que la vraie couche Biodiv'Sports contient). Textes des parcs conformes à la consigne 2.16. `window.latest_landing` et `sun` ajoutés au contrat. Règles d'import PGE a à g en place. `od_time = min(...)`, `gust_max`, `WEAK_THERMALS` : faits. 4.2 confirmé : Open-Meteo est interrogé avec `elevation=<altitude du site>`, déco et atterro séparément.
- **Désaccord S09, tranché** : avec un seul atterro, la règle du cône de finesse limite un circuit à ~70 km, soit environ 2 h 30 : le scénario était irréaliste. Décision de l'expert : option (a), ajout d'`alternate_landings` réels dans S09 (7 atterros de Haute-Provence), S25 (5 atterros autour d'Annecy) et S05 (Les Houches, Passy). Principe retenu : en live, le cône s'appuie sur tous les atterros officiels de la zone.
- Premier passage des scénarios dans le moteur : **24/32 conformes**. Propositions du backend acceptées par l'expert :
  1. `VERDICT.go_min_safety_subscore` 50 → **40** (la courbe vaut 50 à 75 % du seuil, ce qui rendait marginaux des critères à 75-80 %, incohérent avec la bande 80 %). CDC mis à jour.
  2. Vent arrière : au-delà de 90° d'écart, c'est la **vitesse totale** qui se compare au seuil (la composante au secteur le plus proche donnait 4,2 km/h pour un plein E sur Forclaz). CDC mis à jour ; ma règle 5.3 est corrigée.
  3. Le créneau n'est décalé que si le vol est infaisable à l'heure cible (ou pour la règle « élève hors pic ») ; un no-go météo reste un no-go (S08 et S13 sortaient marginaux 2 à 3 h plus tard).
  4. Contrôle du relief sous la ligne de plané seulement avec le MNT réel ; en mock, un warning « profil de terrain non vérifié » est demandé.
  - Les raisons de rejet listent aussi les cautions explicatives (S20 : `BEACON_MISMATCH`).

### Lot 6 : premier passage des 32 scénarios dans le moteur réel, jugés comme au briefing (envoyé)

Exécution par l'expert de `run_scenario` sur `scenarios-validation.yaml` : **32/32 conformes** sur le verdict et les codes de risque obligatoires. Relecture détaillée des plans :

| # | Constat → demande | Statut |
|---|---|---|
| 6.1 | **Bug** : la convection et l'heure de surdév sont calculées sur ±16 h autour de la cible, donc sur la veille (S06 annonce un « surdéveloppement vers 21h00 »). Il faut limiter au jour local (lever → coucher). | envoyé |
| 6.2 | Classement : le plouf de 13 min passe devant un local thermique qui respecte la durée demandée, à score égal à cause du plafond de sécurité (S08b, S17b, S22). Tri attendu : verdict, puis durée dans la plage, puis score plafonné, puis score non plafonné. | envoyé |
| 6.3 | Texte : le plouf affiche « pas de thermique exploitable » alors qu'une variante thermique existe ; reformuler en « plan B ». | envoyé |
| 6.4 | `thermal_match` en `required` calculé sur le ratio STRONG_THERMALS (S09 : 60) au lieu de la courbe de préférence du §9.3 | envoyé |
| 6.5 | Cross sous-dimensionné : S09 fait 115 km en 3 h 54 sur 8 h de convection, avec un motif « fin des thermiques » erroné. Dimensionner sur le budget de temps, dans la limite du cône des atterros. | envoyé |
| 6.6 | Local thermique trop loin du cône (S22 : r = 0,93). Déclencheurs locaux limités à r ≤ 0,80. | envoyé |
| 6.7 | Créneau : vérifier vent au déco et à l'atterro sur toute la fenêtre, couper avant le no-go, `WIND_INCREASING` si le vent forcit ; `weather.landing.time = window.start + durée` | envoyé |
| 6.8 | Risques en doublon (S16b : 5 cautions pour un seul fait) : un Risk par code ; en soaring, pas de STRONG_WIND_ALOFT ni de LANDING_WIND redondants | envoyé |
| 6.9 | Durée réaliste du local thermique selon le vario et le plafond (≤ 60 / 120 / 45 min) | envoyé |
| 6.10 | Couche `useful_height` dans `/api/forecast/grid` | envoyé |
| 6.11 | `glide.required_ratio` = pire cas (déco à son altitude, et chaque point bas de la route) | envoyé (confirmation demandée) |

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
| F2.6 | Ordre des blocs de la page plan (à vérifier une fois la page assemblée) | **corrigé** (vérifié sur les captures `docs/screenshots/plan-detail-*.png`) |

Réponse du frontend : F1 et F2 appliqués, page `PlanDetailPage.tsx` assemblée dans l'ordre demandé. Sur mobile, le premier écran montre verdict + créneau + début du vent.

### Lot F3 : relecture des captures de la fiche plan (envoyé)

| # | Demande | Statut |
|---|---|---|
| F3.1 | Afficher `weather.landing.time` (et non un recalcul) : validé | validé |
| F3.2 | Mock : finesse requise Forclaz→Doussard affichée 1,6 au lieu de ~5,0 ; appliquer la règle du pire cas | envoyé |
| F3.3 | Mock : profil d'altitude au-dessus du plafond utile (2100 m pour 1990 m) | envoyé |
| F3.4 | Itinéraire : colonne « alt. de sécurité » si elle est fournie | envoyé |
| F3.5 | Risques « info » visuellement plus discrets | envoyé |
| F3.6 | Légende de la carte du plan : « Vent au sol (modèle, 10 m) », pour ne pas la confondre avec le vent retenu au déco | envoyé |
| F3.7 | Couche « hauteur utile » quand le backend l'exposera | en attente du backend (6.10) |

## Revue finale (09/10/2026) : plans réels jugés comme au briefing

### Périmètre et conditions de la revue

- Backend lancé sur le port 8015, `DATA_MODE=mock` puis `DATA_MODE=live` (serveur arrêté à la fin). 217 tests verts,
  `ruff` vert. Aucun code modifié par l'expert.
- **Mock** : zones Annecy (45,82 ; 6,22), Chamonix (45,93 ; 6,87), Saint-Hilaire (45,31 ; 5,89), Saint-André (43,97 ;
  6,51), rayon 25 km ; horizons 15m, 30m, 2h, 24h, 48h ; 4 niveaux ; thermiques required / allowed / avoid ; durées
  15-30 et 120-300 ; journées synthétiques variées : 15/10 belle journée thermique, 11/10 thermiques bleus, 12/10 bise,
  13/10 foehn, 17/10 inversion, 21/10 orages ; heures cibles de 10 h à 17 h légales. Décollage libre au-dessus de
  Talloires (45,835 ; 6,230) et points voisins, `POST /api/landings/analyze`, les 3 `landing_policy`.
- **Live** : sites ParaglidingEarth, balises Pioupiou, OpenAIP (un seul appel) et Biodiv'Sports lus sur Annecy et
  Chamonix. **Aucun plan live n'a pu être calculé** : Open-Meteo répond HTTP 429 « Daily API request limit
  exceeded » sur l'adresse de sortie (vérifié par un appel direct), et il était 19 h 30 légales, donc après le coucher.
  Les plans live (30m et 24h, intermediate, Annecy et Chamonix) **restent à juger** dès que le quota revient
  (00 h UTC). Pour compenser, les cas dangereux trouvés sur les données live ont été rejoués hors ligne avec
  `run_scenario` (scénarios S04, S05, S18 et S22 modifiés).
- Contrôles conformes : `rules.py` reprend fidèlement le §11 et le §12.9 ; heures en heure légale partout, y compris
  après le passage à l'heure d'hiver (26/10 : 12:00Z affiché 13h00) ; ordre du briefing du §7.1 et, à 15m/30m, ligne
  des balises en position 1 (§12.5) ; checklist du §7.2, plus la manche à air aux horizons courts ; refus du décollage
  libre pour l'élève, pente minimale, seuils et contrôles obligatoires du §12.6 ; atterros communautaires et champs
  filtrés par politique et par niveau, avertissements « Non officiel » présents (§12.7) ; foehn (13/10), bise (12/10)
  et orages (21/10) rejetés à Annecy, Saint-Hilaire et Saint-André ; mode démo signalé partout ; exports GPX et
  XCTrack lisibles (heures UTC dans la tâche).

### Lot 7 : constats (requêtes et extraits ; « ref » = `reference_time`)

Gravité : **B** = bloquant (danger possible pour le pilote ou résultat absurde) ; **M** = majeur (faux ou incomplet) ;
**m** = mineur.

| # | G | Constat (preuve) → correction attendue | Statut |
|---|---|---|---|
| 7.1 | B | **Secours hors de portée présentés comme secours.** Mock, Annecy 24h intermediate allowed 15-30, ref 2026-10-14T09:00Z : plouf Planfait → Perroix GO, `alternate_landings` = Doussard, Montmin village, Saint-Jorioz. Dans `landing_analysis` : Doussard requis 12,14 pour 6,08, arrivée −587 m, score 85,1, `use: main`, « marge de finesse juste (2,00) » ; Montmin village requis 42,7, arrivée −843 m, de l'autre côté de la crête de Lanfon. Le briefing écrit « secours : Doussard, Montmin village, Saint-Jorioz ». Même chose à 15m (Saint-Jorioz requis 11,5, arrivée −1513 m, score 79,9). → `planner._landing_setup` et `landings.candidates_for_plan` : ne garder en secours que les atterros atteignables avec la marge (r ≤ 1 depuis le déco pour un plouf ; pour un local ou un cross, depuis au moins un point de la route à son altitude de sécurité). Les autres sortent des `alternate_landings`, des waypoints et du briefing. Dans `landing_analysis`, mention « Écarté : hors de portée (finesse requise X pour Y) ». `_phrase('glide_margin')` : « hors de portée » si r > 1. Score plafonné comme au §9.1 (sous-score finesse 0 ⇒ score ≤ 40). | envoyé |
| 7.2 | B | **Surdéveloppement modéré : vol proposé à l'heure du surdéveloppement, ou après.** Mock, Chamonix 24h expert allowed 120-300, ref 2026-10-20T11:00Z : plouf Plan Praz MARGINAL, créneau 13h00-13h15, « être posé avant 13h16 (surdéveloppement attendu 1 h plus tard) », alors que le Risk dit « Surdéveloppement possible vers 13h00 : être posé au plus tard 1 h avant ». Hors ligne, S22 modifié (CAPE 450-700 et LI −1 dès 10Z, ref 11Z) : plouf proposé à 13h00, **aucun** Risk OVERDEVELOPMENT, et `latest_landing` (13h12) tombe avant `window.end` (13h15). Cause : dans `planner.convective_findings` (moderate), rien n'est signalé si l'heure du surdéveloppement précède le décollage ; dans `_build_plan`, `cand.latest_landing = max(latest, landing_time)` efface le plafond horaire. → Si décollage + durée > surdév − 1 h, ou si surdév < décollage : rejet « [OVERDEVELOPMENT] Surdéveloppement possible vers hh:mm : plus de créneau (il fallait être posé avant hh:mm) ». Ne jamais remonter `latest_landing` au-dessus du plafond ; garantir `latest_landing ≥ window.end + durée`, sinon réduire `window.end`. | envoyé |
| 7.3 | B | **ParaglidingEarth : orientations « tous secteurs » ou incohérentes, donc plus aucun contrôle du vent arrière ni du dévent.** En live : Plaine Joux (Passy) pge:3021, Dômes de Miage, Le Méruz et Marlens ont les 16 secteurs ; Plan Praz/Brévent est noté `['NE','S']` (le NE est un vent arrière sur ce déco sud) ; Plan de Langot a 9 secteurs, de l'E à l'W. Rejoué hors ligne avec les 16 secteurs : S04 (dévent, attendu no_go) sort **MARGINAL** en local thermique de 2 h ; S18 (vent arrière de 6 km/h, attendu no_go) sort « **GO pour élève / brevet initial** ». Cause : `providers/sites.pge_orientations` transforme 8 secteurs notés en 16 orientations. → (a) Dès 6 secteurs PGE notés sur 8, l'orientation est **inconnue** : la déduire de l'exposition MNT ± 22,5° (comme `terrain.py` pour le décollage libre), avec un Risk caution « Orientation du déco incertaine (ParaglidingEarth) : vérifie sur place ». (b) Préférer les secteurs notés 2. (c) Écarter les secteurs à plus de 90° de l'exposition MNT (le NE de Plan Praz). (d) Orientation incertaine et MNT indisponible : site non proposé, avec la raison. Test attendu : S04 et S18 restent no_go avec 16 secteurs. | envoyé |
| 7.4 | B | **Zones où le parapente est interdit, traitées comme un survol autorisé au-dessus de 300 m/sol.** Biodiv'Sports en live : « Réserve naturelle nationale des Aiguilles Rouges : Parapente et autres sports aériens interdits dans la zone » (`min_height_agl_m` null) ; même texte pour la Réserve du Bout du Lac d'Annecy. Le déco du Brévent est à 77 m de la réserve des Aiguilles Rouges ; la ligne droite Forclaz → Doussard traverse celle du Bout du Lac, et l'atterro de Doussard est à 270-290 m de sa limite. Cause : dans `airspace.evaluate_sensitive_route`, la hauteur vaut 300 m par défaut ; une zone réglementée ne donne qu'une caution, et seulement sous cette hauteur, rien au-dessus. Les zones OpenAIP `LOW_OVERFLIGHT` (PARC/RESERVE, ZSM) ne produisent **aucun** constat dans `airspace.evaluate`. → `providers/sensitive.py` : repérer « interdit(s) dans la zone », « survol interdit », « vol libre interdit » et poser `flight_prohibited=True`. Moteur : traverser une telle zone, à toute hauteur, est un no-go (CDC §3 #12) ; le routeur la contourne, et le briefing Atterrissage le dit (« PTU hors de la réserve du Bout du Lac »). Survol d'une zone réglementée sous sa hauteur : no-go, pas caution. Zones OpenAIP `LOW_OVERFLIGHT` : même traitement, plafond lu comme une hauteur sol. | envoyé |
| 7.5 | M | **GO malgré la caution bloquante WIND_INCREASING (§9.4).** Mock, Annecy 24h intermediate allowed 15-30, ref 2026-10-14T09:00Z : plouf Planfait GO 89, avec la caution « Le vent forcit à partir de 13h30 (proche des limites de ton niveau) » sur un créneau 11h00-14h00. Même cas à Saint-Hilaire Nord (ref 2026-10-10T11:00Z, GO 70,9). Cause : `_compute_window` ajoute le Risk après le verdict. → Couper `window.end` au dernier pas avant `increasing_at` (le GO reste valable sur ce créneau réduit) et publier l'info « fin du créneau GO à 13h30 : le vent forcit ensuite ». Si `increasing_at` ≤ début + 30 min : caution, et verdict recalculé (marginal). | envoyé |
| 7.6 | M | **Le créneau n'est pas revérifié sur toute sa durée (coucher − 30 min, déco E à l'ombre).** Mock, Saint-Hilaire 24h beginner avoid 15-30, ref 2026-10-14T15:00Z : plouf GO, créneau 17h00-18h30, « posé avant 18h43 », coucher à 18h51, pas de SUNSET (§3 #11, §10 #18). Même cas à Annecy avoid (posé 18h44, coucher 18h49) et à l'horizon 2h. Saint-Hilaire Nord (E/ESE/NE), ref 2026-10-10T11:00Z : GO avec un créneau 13h00-16h00, alors que le déco E est interdit après 12h30 solaires (13h53 légales), vent de crête NE à 8 km/h, sous les 10 km/h de l'exemption (§4.3). Cause : `_wind_ratio_at` ne regarde que le vent et la pluie. → `hard_end = min(…, coucher − 30 min − durée)` pour toutes les variantes ; arrêter le créneau au premier pas où un constat bloquant de déco (déco E à l'ombre, LEE_SIDE) ou un no-go convectif apparaîtrait. | envoyé |
| 7.7 | M | **« Être posé avant … (raison) » : raison fausse.** « être posé avant 14h14 (coucher du soleil). Coucher du soleil à 18h49. » (plouf Planfait, 24h) ; « 15h13 (coucher du soleil) » (Saint-Hilaire, 48h) ; « posé avant 15h00 (fin des thermiques) » à 15m alors que la convection dure jusqu'à 17h00 ; « 17h30 (thermiques 0.9 m/s, plafond utile 1017 m au-dessus du déco) ». Le summary dit « Seul un plouf d'environ 14 min est possible avant le coucher du soleil » (la durée vient du dénivelé) et « Vol limité à ~45 min (fin des thermiques) » pour un élève (la vraie limite est les 45 min de l'élève). Cause : `_build_plan` (`latest = min(cand.latest_landing, window_end + durée)`) ne met pas à jour `landing_cap_reason`. → Quand c'est `window.end + durée` qui borne, la raison est « fin du créneau (hh:mm) + durée du vol », ou la cause qui a fermé le créneau (vent qui forcit, cible + 3 h, coucher − 30 min). Raison « limite élève 45 min » pour l'élève, « dénivelé » pour le plouf. | envoyé |
| 7.8 | M | **Points de décision vides en local thermique (§5.4, §7.1-7).** « Point de décision : Rester dans le cône de finesse de Talloires – Perroix : si le thermique ne monte pas au-dessus de 1240 m, revenir vers l'atterro. » 1240 m, c'est l'altitude du déco (même chose à Saint-Hilaire avec 975 m, et en décollage libre avec 855 m). Le cross, lui, le fait bien (« Segment 1 : sous 1500 m, rentrer vers Lumbin »). → `routing.build_local_thermal` : calculer `alt_securite` à chaque `thermal_trigger` et l'écrire : « Pour aller aux Dents de Lanfon, sois au-dessus de X m à la Crête N ; en dessous, retour vers Perroix. » | envoyé |
| 7.9 | M | **Rafale fusionnée à facteur de rafale non borné.** Mock, Saint-Hilaire 30m intermediate, ref 2026-10-15T11:30Z : la balise de Lumbin mesure 7 km/h (rafales 13), le modèle × 1,3 donne 4 km/h (rafales 13), et le plan **retient 6 km/h avec rafales 21** : VALLEY_BREEZE caution et MARGINAL (21/25 = 84 %). Cause : dans `stations.fuse`, `g = model_g × v / model_v`, soit un facteur de 3,25 appliqué au vent fusionné. → `g_fusion = g_modèle + poids × (g_balise − g_modèle à l'heure de la mesure)`, même formule que pour le vent moyen (§12.1), au moins égal à `v_fusion` ; garder le max avec la rafale balise à 15m, 30m et 1h. | envoyé |
| 7.10 | M | **La difficulté du plan ignore les règles de l'élève et le score.** Mock, Saint-Hilaire 48h intermediate (ref 2026-10-13T10:00Z) : local thermique de 1 h « GO pour élève / brevet initial », créneau 14h00-16h30 avec pic à 15h00 (§2.1 : un élève vole 45 min au plus, et décolle avant convection + 1 h). Demande élève (24h, allowed, durée longue) : local de 45 min, créneau 14h00-16h30, convection à 14h00. À l'inverse, le plouf Forclaz est publié avec la difficulté intermediate (demande advanced), mais rejeté pour un intermediate (« Score global insuffisant (40/100) »). → Difficulté au moins intermediate si la durée dépasse 45 min, ou si le créneau thermique déborde convection + 1 h. Pour un élève en thermique, `window.end` ≤ convection + 1 h, sauf restitution. Difficulté = plus petit niveau dont le **verdict** n'est pas no_go (score compris). | envoyé |
| 7.11 | M | **Cross proposé sur des thermiques faibles.** Mock, Saint-Hilaire 24h expert allowed 120-300, ref 2026-10-14T09:00Z : « cross triangle FAI 25 km 3h13 … thermiques 0.9 m/s », GO. Selon le §4.8, 0,8 à 1,5 m/s, c'est du local doux. Les points tournants s'appellent « Relief à 7 km au O ». → `rules.XC_MIN_VARIO_MS` = 1,5 (intermediate, advanced), 1,2 (expert). En dessous, pas de variante cross, avec la raison « [WEAK_THERMALS] Thermiques trop faibles pour un cross (0,9 m/s ; 1,5 requis) ». Nommer le sommet quand la couche relief le connaît. | envoyé |
| 7.12 | M | **Atterro officiel au vent d'arrivée hors niveau, proposé comme utilisable.** `POST /api/landings/analyze` (45,755 ; 6,245 ; 24h ; ref 2026-10-14T12:00Z ; intermediate ; include_fields) : seul candidat, Doussard, `use: main`, score 83,1, avec l'avertissement « Vent à l'arrivée 17 km/h, rafales 31 : au-dessus du seuil de ton niveau ». Pour le local Planfait (24h), Doussard est donné en secours avec des rafales de 26 km/h (seuil 25). → Atterro dont le vent ou les rafales à l'arrivée dépassent le seuil du niveau : `usable=False` dans l'analyse et en secours (« écarté : vent d'arrivée 17 km/h, rafales 31 ; seuils 20 / 25 »). Score du candidat plafonné à 40 + min(sous-scores finesse, vent d'arrivée). | envoyé |
| 7.13 | M | **Forclaz → Doussard : mon calage du §2.3 était faux.** PGE live : déco pge:3046 (45,8142 ; 6,247 ; 1265 m), atterro Doussard (45,7819 ; 6,2221 ; 467 m), à **4,1 km** et non 3,4 km (la balise Pioupiou 1720 « Atterrissage de Doussard » confirme la position). Finesse requise 5,9. Résultat en mock (Annecy 24h beginner allowed 15-30, ref 2026-10-14T09:00Z) : **aucun plan pour un élève, par belle journée**, avec « [GLIDE_MARGIN] Finesse requise 5.9 … pour 5.5 disponible ». Pour un brevet de pilote : no-go par le score (40/100), ou au mieux marginal GLIDE_MARGIN. Même chose à 15m, 30m et 2h. → **Décision expert** : pour le plané direct déco → atterro officiel associé, l'association venant de la source (FFVL, PGE ou fixture, jamais déduite par proximité), et seulement si le relief est vérifié sur MNT réel, la finesse de calcul vaut **k = 0,80 à tous les niveaux** (`GLIDE_K_ASSOCIATED_PAIR`, `rules.py` partie 2). Les autres planés gardent le k du §11. Attendu : Forclaz → Doussard par vent calme, 6,8 disponible, r = 0,86, GO pour un élève ; avec 10 km/h de face, 4,96 disponible, no-go. Ajouter un test de non-régression. Contrôle du §2.3 à corriger (CDC rév. 4). | envoyé |
| 7.14 | M | **Fixture Plaine-Joux → Passy jamais corrigée (lot 3.1).** Mock Chamonix, à toutes les requêtes : « [GLIDE_MARGIN] Finesse requise 7.2 vers Passy – atterrissage pour 5.3 à 6.4 disponible. Hors limites pour tous les niveaux. » `fixture:passy` est toujours en (45,9195 ; 6,7055), à 4,8 km, inchangé depuis b2e0006. PGE live : Plaine Joux pge:3021 → Chedde à 2,6 km. → `fixtures/sites.json` : atterro de Plaine-Joux = Chedde (45,9285 ; 6,7246 ; 603 m), plus un test « GO élève par vent calme ». | envoyé |
| 7.15 | M | **Décollage au-dessus du FL115 accepté sans réserve.** PGE live, sites officiels : Mont Blanc (4536 m), Aiguille du Midi (3593 m), Dômes de Miage (3563 m, 16 secteurs). Hors ligne, S05 modifié (déco à 3593 m, thermiques allowed) : « go advanced … plouf 39 min », `max_altitude_m` 3593, aucun Risk. En thermiques required, le rejet dit « plafond utile −188 m au-dessus du déco », ce qui ne veut rien dire pour un pilote. → Déco au-dessus de FL115 − 100 m : Risk ALTITUDE_LIMIT caution bloquante « Décollage au-dessus du plafond réglementaire FL115 (≈ 3505 m) : haute montagne, réglementation locale (Mont-Blanc, R30) à vérifier », difficulté expert. Raison de rejet en clair : « plafond limité par le FL115 sous l'altitude du déco ». | envoyé |
| 7.16 | M | **Espaces aériens : les plafonds référencés au sol sont perdus.** OpenAIP live : « PARC/RESERVE AIGUILLES ROUGES, LOW_OVERFLIGHT, 0-300 AMSL » ; « LF-R30C MONT BLANC (JUNE - 15 OCT), R, 0-305 AMSL », zone active jusqu'au 15/10 ; mêmes 300 m pour Passy, Contamines, Sixt et Bauges. Cause : `providers/airspaces.py` ne convertit un plafond sol qu'avec le MNT, et au seul point central ; l'indicateur sol du plafond n'est pas conservé ; `/api/airspaces` n'expose que `floor_reference`. → Garder `ceiling_agl` ; contrat : ajouter `ceiling_reference: "AMSL" \| "GND"`. Moteur : recouvrement vertical calculé point par point avec terrain(p) + valeur pour les limites sol, ce qui fait apparaître AIRSPACE_ACTIVATION pour la R30C quand la route passe à moins de 305 m du sol. `LOW_OVERFLIGHT` : voir 7.4. | envoyé |
| 7.17 | M | **Règles du CDC jamais lues par le moteur.** Aucune occurrence hors de `rules.py` pour : `pressure_drop_hpa_3h` (§3 #13), `foehn_dp_hpa` (§3 #4), `XC_CEILING_MIN_ABOVE_RELIEF_M` (§2.1 : plafond d'un cross ≥ relief max de la route + 500 / 400 / 300 m), `TRANSITION_ARRIVAL_ABOVE_TERRAIN_M` (§5.4), `VENTURI_FACTOR_COL` et `ROTOR_LEE_FACTOR` (§4.5), `GLIDE_LEE_PENALTY` (§2.3, −10 %). → Implémenter : pression réduite au niveau de la mer d'Open-Meteo et sa variation sur 3 h ; relief max le long de la route d'un cross sur MNT réel ; zone de rotor de 5 à 10 fois la hauteur du relief sous le vent, dès 15 km/h de vent à la crête. En attendant, Risk info « non vérifié par l'outil : rotor, venturi, tendance de pression », et liste dans le README. | envoyé |
| 7.18 | m | **Raisons de rejet confuses.** Doublons d'une variante à l'autre (VALLEY_BREEZE à 12h14 puis à 13h30, TAKEOFF_GUSTS et LANDING_WIND en double). Code faux : « [TAKEOFF_WIND] Vent jusqu'à 33 km/h vers 1545 m sur la tranche volée » (c'est du vent en altitude). Formules ambiguës : « (seuil de ton niveau appliqué). Hors limites pour tous les niveaux ». « [LANDING_WIND] Score global insuffisant (40/100) : point faible = atterrissage et finesse » ne donne pas les chiffres de finesse. « Pente MNT de 25 % : trop faible (minimum 25 %) » (afficher 24,6 %). En official_only, « Aucun atterro à portée » alors qu'un atterro communautaire est à portée mais exclu par la politique : le §12.7 demande de le nommer. → Dédoublonner par code en gardant le plus grave ; corriger les codes ; une décimale pour les pentes proches du seuil. | envoyé |
| 7.19 | m | **Fausse précision à 24-48 h (§1.1, §10 #21).** « posé avant 15h13 », « 14h14 ». → Arrondir au quart d'heure dès 12 h d'horizon. | envoyé |
| 7.20 | m | **Restitution manquée.** Annecy 24h intermediate avoid, ref 2026-10-14T15:00Z, cible 17h00 : la restitution commence à 17h19 (coucher − 1 h 30), dans [cible − 30 min ; cible + 3 h], et seul un plouf est proposé. → `planner` (vers la l. 1500) : accepter la restitution si son créneau recoupe [cible − 30 min ; cible + 3 h]. | envoyé |
| 7.21 | m | **Textes et détails.** « Cross en triangle fai » (écrire FAI). « confiance réduite (30 %) » en mock, où 30 % est le plafond de la démo. L'aérologie d'un plouf mélange « thermiques de 14h00 à 17h00 » et « vario 0.0 m/s, plafond utile 1300 m », et `ThermalAnalysis.ceiling_m` change d'un plan à l'autre le même jour (1339 puis 2250 m). Atterro PGE nommé « null » (pge:3045). Pioupiou 1720 marquée `stale` alors que la mesure date d'1 min (c'est la mesure qui manque). `trend` toujours null dans `/api/beacons`. L'analyse d'un point libre dit « pente 21 % » sans dire que c'est insuffisant. Tâche XCTrack : SSS sur le 1er point tournant au lieu d'un départ autour du déco. ETA de 15 min aux Dents de Lanfon pour +1173 m à 1,0 m/s. | envoyé |
| 7.22 | m | **Statut des sources en live trompeur.** Quota Open-Meteo épuisé : `/api/sources` affiche « Open-Meteo (AROME HD, ICON-D2, ECMWF) : healthy, Pas encore interrogée », alors que les trois API sont suspendues ensemble (REPRISE §4) et que les plans répondent 503 (« Open-Meteo Elevation indisponible : quota journalier atteint »). Le 503 et le 422 de l'analyse (« indique elevation_m ») sont, eux, clairs. → Propager la suspension aux trois sources dans `/api/sources`. | envoyé |

### Décisions sur les choix backend listés dans REPRISE §8

- Taille, pente ou obstacle inconnus : **validé**, sans exclusion, avec un sous-score réduit et une note, pour un atterro
  communautaire. Un **champ détecté** dont la pente est inconnue (MNT indisponible) est exclu.
- Approche : obstacle de plus de 10 m à moins de 150 m dans l'axe ⇒ exclusion ; longueur utile = L − (5 h − distance) :
  **validé**.
- Atterro officiel au vent d'arrivée trop fort, gardé dans la sélection : **validé pour l'atterro principal d'un plan
  classique**, qui sort alors en no-go LANDING_WIND, raison expliquée. **Refusé** pour l'analyse d'un décollage libre et
  pour les secours (voir 7.12).
- Atterro PGE non officiel = usage « occasional » : **validé** (choix prudent).
- Pente mesurée sur le MNT 90 m : **validé**, avec l'avertissement « pente estimée sur MNT 90 m : à vérifier en vol ».
- Doussard de démo sur la position PGE / Pioupiou 1720 : **validé**. Conséquence sur la finesse : voir 7.13.

### Ce qui serait dangereux aujourd'hui (synthèse moniteur)

1. Croire avoir un secours alors qu'il est hors de portée, ou derrière une crête (7.1).
2. Décoller à l'heure du surdéveloppement prévu, un jour d'orages (7.2).
3. Un déco ParaglidingEarth « tous secteurs » donné GO par vent arrière ou en dévent, y compris à un élève (7.3).
4. Survoler une réserve où le parapente est interdit (Aiguilles Rouges, Bout du Lac) sans aucun avertissement (7.4, 7.16).

**À faire avant usage pilote** : 7.1 à 7.4 corrigés et testés (scénarios hors ligne fournis plus haut). Puis plans live
de 30m et 24h à juger sur Annecy et Chamonix, comparés à la prévision brute Open-Meteo, dès que le quota revient.

## Réponse du backend à la revue finale (10/10/2026)

Chaque constat a été reproduit (mock ou scénario hors ligne) avant correction ; un test de non-régression le couvre
(`backend/tests/test_review_fixes.py`, sauf mention). Requêtes et seuils cités : ceux du lot 7.

| # | Statut | Correction |
|---|---|---|
| 7.1 | corrigé | Secours = atterros officiels atteignables (r ≤ 1, relief dégagé) depuis le déco (plouf, soaring) ou depuis un point de la route à son altitude de sécurité (déclencheur − 150 m en local, plafond − 300 m tous les 2 km en cross), vent d'arrivée dans les seuils ; sinon hors des `alternate_landings`, des waypoints, du briefing et de `landing_analysis`. « hors de portée (finesse requise X pour Y) » ; score plafonné à 40 + min(finesse, vent d'arrivée). Planfait (24h) : plus de Doussard / Montmin village / Saint-Jorioz en secours. |
| 7.2 | corrigé | `moderate` (et `high`) : vol à l'heure du surdéveloppement, après, ou posé moins d'1 h avant → rejet « [OVERDEVELOPMENT] … plus de créneau (il fallait être posé avant hh:mm) » ; `latest_landing` jamais remonté au-dessus du plafond ; `window.end + durée ≤ latest_landing` garanti. S22 modifié : rejeté. |
| 7.3 | corrigé (b interprété) | (a) ≥ 6 secteurs notés sur 8 : orientation incertaine, déduite de l'exposition MNT ± 22,5° (4 points à ± 150 m, MNT réel), caution TAKEOFF_WIND « Orientation du déco incertaine … vérifie sur place » ; (c) secteurs à plus de 90° de l'exposition écartés (NE de Plan Praz) ; (d) sans MNT : site non proposé, raison donnée. (b) appliqué seulement quand ≥ 6 secteurs sont notés (sinon Forclaz perdait son W, noté 1, axe principal) : **à confirmer par l'expert**. S04 et S18 avec 16 secteurs : no_go (sans MNT, et avec exposition imposée). |
| 7.4 | corrigé | `flight_prohibited` (code PARAGLIDING-FORBIDDEN, « interdits dans la zone », « survol / vol libre interdit » ; pas une interdiction limitée en hauteur) : traverser = no-go à toute hauteur, déco / atterro dedans = no-go ; le routeur contourne (graphe de visibilité, marge 150 m, plané allongé d'autant) ; briefing « PTU et approche hors de la zone … ». Survol réglementé sous sa hauteur : no-go. OpenAIP `LOW_OVERFLIGHT` = zone réglementée, plafond lu comme hauteur sol. Fixture des Aiguilles Rouges alignée sur Biodiv'Sports. |
| 7.5 | corrigé | Le créneau GO s'arrête au pas précédant l'entrée du vent dans la bande 80-100 % (Risk info « Fin du créneau à hh:mm : le vent forcit ensuite ») ; dans les 30 premières minutes : caution WIND_INCREASING et verdict MARGINAL. |
| 7.6 | corrigé | Fin de créneau = min(heure limite − durée, cible + 3 h, coucher − 30 min − durée, élève : convection + 1 h) pour toutes les variantes ; chaque pas revérifié avec les constats bloquants horaires (vent arrière, déco E à l'ombre, dévent, vent hors limites, orage / surdéveloppement). |
| 7.7 | corrigé | « être posé avant » : « fin du créneau à hh:mm + durée de vol ; cause » quand c'est le créneau qui borne ; durée : « limite élève 45 min », « dénivelé de X m » (plouf), cause réelle sinon. |
| 7.8 | corrigé | Local thermique : « Pour aller à B, sois au-dessus de X m à A ; en dessous, retour vers L. À B, sous Y m, rentre vers L » (alt_sécurité au cône des atterros, jamais sous relief + 150 m). |
| 7.9 | corrigé | Rafale fusionnée = rafale modèle + poids × (rafale balise − rafale modèle à l'heure de la mesure), ≥ vent fusionné ; max avec la rafale balise 10 min aux horizons courts. Lumbin 30m : 6 km/h, rafales 14 (et non 21). |
| 7.10 | corrigé | Difficulté = plus petit niveau dont le VERDICT (score compris) n'est pas no_go ; au moins « brevet de pilote » si le vol dépasse 45 min ou si le créneau thermique déborde convection + 1 h ; élève en thermique : décollage avant convection + 1 h. |
| 7.11 | corrigé | `XC_MIN_VARIO_MS` 1,5 (inter., conf.) / 1,2 (expert) : « [WEAK_THERMALS] Thermiques trop faibles pour un cross (0,9 m/s ; 1,5 requis) » ; points tournants nommés d'après le sommet connu le plus proche (≤ 2 km). |
| 7.12 | corrigé | Vent / rafales d'arrivée au-dessus du seuil : écarté dans l'analyse et en secours (« vent d'arrivée 17 km/h, rafales 31 (seuils 20 / 25) ») ; gardé pour l'atterro principal d'un plan classique (jugé par LANDING_WIND). |
| 7.13 | corrigé | `GLIDE_K_ASSOCIATED_PAIR = 0,80` pour le plané direct déco → atterro officiel associé par la source (jamais une association déduite par proximité, marquée `deduced_landing_ids`), relief vérifié sur MNT réel (démo / scénario : données réputées exactes). Forclaz → Doussard élève par vent calme : 6,8 disponible, GO ; 10 km/h de face : pas de GO. CDC §2.3 corrigé (rév. 4). En live, le contournement de la réserve du Bout du Lac allonge le plané (+ 150 m environ) : r ≈ 0,91, **à juger par l'expert**. |
| 7.14 | corrigé (partiel) | Atterro de Plaine-Joux = Chedde (45,9285 ; 6,7246 ; 603 m) : GO élève par vent calme. Le déco de démo reste en (45,9545 ; 6,7420), à 3,2 km de Chedde (2,6 km pour le déco PGE pge:3021) : position à vérifier sur PGE (injoignable le 10/10, « connection reset »). |
| 7.15 | corrigé | Déco au-dessus de FL115 − 100 m : ALTITUDE_LIMIT caution BLOQUANTE (« … réglementation locale (Mont-Blanc, R30) à vérifier ; réservé aux pilotes experts »), difficulté expert ; rejet clair « Plafond limité par le FL115 (≈ 3405 m) sous l'altitude du déco ». |
| 7.16 | corrigé | Limites sol gardées comme hauteurs (`ceiling_reference`, `floor_height_m`, `ceiling_height_m` au contrat), converties point par point sur la route ; R30C sous 305 m/sol → AIRSPACE_ACTIVATION. |
| 7.17 | partiel | Lus : baisse de pression ≥ 3 hPa / 3 h (FRONT no-go, `pressure_msl` Open-Meteo), rotor à l'atterro (5 / 10 × la hauteur du relief au vent, vent de crête ≥ 15 km/h, MNT réel), plafond d'un cross ≥ relief de la route + 500/400/300 m (MNT réel). Non vérifiés, listés dans un Risk info `UNCHECKED` et le README : venturi, Δp du foehn, hauteur d'arrivée sur la face suivante, −10 % sous le vent. |
| 7.18 | corrigé | Une raison par code (la plus grave) ; STRONG_WIND_ALOFT pour le vent en altitude ; plus de « (seuil de ton niveau appliqué) » ; chiffres de finesse dans « Score global insuffisant » ; pente à une décimale près du seuil ; terrain communautaire exclu par la politique nommé. |
| 7.19 | corrigé | « être posé avant » au quart d'heure dès 12 h d'horizon (jamais au-dessus du plafond horaire). |
| 7.20 | corrigé | Restitution proposée dès que son créneau recoupe [cible − 30 min ; cible + 3 h] (sauf no-go absolu à l'heure cible : S13). |
| 7.21 | corrigé | « FAI » ; « confiance plafonnée (démo) » ; aérologie du jour (pic, plafond du jour) puis l'heure du vol ; atterro PGE « null » → « Atterrissage PGE n° … » ; `stale` = mesure ancienne (mesure absente = vent null) ; tendance dans /api/beacons (≤ 8 balises) ; verdict de pente dans l'analyse ; SSS autour du déco ; ETA = transition + montée au vario. |
| 7.22 | corrigé | /api/sources : suspension du quota Open-Meteo propagée aux trois API. Plans live 30m / 24h sur Annecy et Chamonix **toujours à juger**. |
| B5 | corrigé | Jamais d'altitude tirée du MNT de démo hors `DATA_MODE=mock` (sites, /api/forecast/point, /api/forecast/grid) ; site sans altitude écarté, avertissement, cache 10 min. |
| B6 | corrigé | OpenAIP par tuiles de 1° (cache 24 h, un appel / 5 min, verrou) ; jamais d'espaces de démo hors mock ; sinon `unverified` + Risk « Espaces aériens non vérifiés ». |
| B7 | corrigé | Voir 7.16 ; cache indépendant du MNT. |
| TMA | corrigé | Espace interdit au-dessus du déco, de l'atterro et du relief : vol thermique reconstruit sous plancher − 100 m (ALTITUDE_LIMIT non bloquant) au lieu d'un rejet. |
| ids | corrigé | Id de plan = hachage de toute la requête normalisée. |
| Balises auto | corrigé | Balises de démo seulement en mode démo ou météo synthétique ; sinon aucune, avertissement. |
| Altitude saisie | corrigé | Écart au MNT > 100 m : avertissement + caution FREE_TAKEOFF ; > 300 m : plané calculé avec min(saisie, MNT + 50 m). |
| Tendance | corrigé | Régression linéaire sur tous les échantillons. |
| Heure cible | corrigé | Même arrondi (15 min jusqu'à 1 h, l'heure au-delà, demie vers le haut) au front, au moteur et dans les réponses. |
| Mineurs | corrigés | Verrou par clé (prévisions, sites, MNT, zones) ; confiance × 0,8 avec un seul modèle et modèles réels par heure ; seuils de tendance du front alignés ; mots entiers pour « fermé » ; `<ele>` omis si inconnu ; pluie « 3 h avant » à la convention Open-Meteo ; caution AIRSPACE < 100 m vertical ; tests renforcés (assertion tautologique, `risk_codes_forbidden` à tout niveau, contenu GPX / .xctsk). |
| Doussard démo | **refusé** | Le constat demande de replacer Doussard à ≈ 3,4 km du déco ; le constat 7.13 de l'expert établit que la vraie distance est 4,1 km (PGE pge:3046, balise Pioupiou 1720) et règle le plouf par k = 0,80 : la fixture reste sur le vrai terrain. |

## Décisions de l'expert sur les points « à juger » (révision 5 du CDC, 10/10/2026)

- **7.13, contournement de la réserve du Bout du Lac** (Forclaz → Doussard) :
  - Par **calme strict** : r ≈ 0,91 en live (+ 150 m), et 0,93 dans le scénario S35 (+ 260 m, avec l'enveloppe de la couche Biodiv'Sports). Le verdict est MARGINAL pour l'élève (`GLIDE_MARGIN` caution), et je le **confirme** : il ne reste aucune réserve de calcul, même si la hauteur d'arrivée réaliste reste d'environ 240 m.
  - Par **vent du N** : le plané passe aisément, GO (S34). Voir le CDC §14.6.
- **7.3 (b)**, secteurs notés 2 préférés seulement quand au moins 6 secteurs sont notés : l'interprétation est **confirmée** pour la Forclaz. Le déco garde O, ONO et NO (lac à l'O-NO). Le N et le NNO ne sont pas ajoutés, faute de relevé terrain de l'azimut (CDC §14.6, valeur prudente).
- **Vent sur le plané** (remarque du pilote) : doctrine au CDC §14. Scénarios S33-S41 dans le bloc `scenarios_phase3`, à charger avec l'implémentation. La revue de l'implémentation fera l'objet du lot 8.

## Désaccords remontés au coordinateur

_(aucun pour l'instant)_
