# Point de reprise

Tout est sur la branche `claude/paraglide-flight-planner`. La clé OpenAIP est dans `backend/.env`
(non versionné) : à recréer si la session est neuve (`OPENAIP_API_KEY=...`).

## État (09/10/2026)

- **Backend** : 217 tests passent (`uv run pytest -q`), `uv run ruff check .` vert. Moteur d'évaluation,
  seuils (`app/engine/rules.py`, blocs YAML §11 et §12.9 recopiés), calculs aérologiques, providers
  (Open-Meteo + 15 min, ParaglidingEarth, Pioupiou + archive, OpenAIP, OpenAir, Biodiv'Sports,
  Overpass désactivé par défaut), balises au déco et à l'atterro, horizon 15 min, décollage libre et
  analyse des atterrissages (`POST /api/landings/analyze`), exports GPX / XCTrack, Dockerfile, README.
  Les 37 scénarios du moniteur (`scenarios` + `scenarios_phase2`, S28-S32 compris) passent, sans xfail.
- **Frontend** : pages Planification, Détail du plan, Sources, À propos ; balises en direct, bascule
  « Classique / Décollage libre », cône de finesse, fiches des atterros candidats. 80 tests Vitest.
- **Intégration (09/10/2026)** : contrat validé sur les vraies réponses du backend (`frontend/scripts/check-contract.mjs` :
  26 réponses typées contre `src/api/types.ts`, 0 écart en mock) ; parcours Playwright complet
  (`frontend/e2e/parcours.mjs`, 39 vérifications, 1440 px et 375 px, 0 erreur console) contre le backend en mock.
- **Expert** : cahier des charges (rév. 2, §12 compris), 37 scénarios (`docs/expert/scenarios-validation.*`),
  journal `docs/expert/revue-backend.md`.

## Reste à faire

1. [x] Backend : lot 6 du moniteur (`engine/planner.py`).
2. [x] Backend : `tests/test_expert_scenarios.py` (scénarios + invariants, phase 2 chargée).
3. [x] Backend : balises au déco ET à l'atterro (heure d'arrivée), horizon `15m`, altitude MNT des
   balises Pioupiou, tendance (archive Pioupiou), `station_readings`.
4. [x] Backend : sources live validées sur de vraies réponses, `app.check_sources`, OpenAIP, PGE en
   `https://www.`. Quotas : un HTTP 429 suspend la source (quota journalier Open-Meteo : les trois API
   Open-Meteo ensemble, 1 h au plus, `QUOTA_BLOCK_MAX_S` ; OpenAIP : 5 min au moins) ; repli
   (échec transitoire) des sites et des zones sensibles gardé 10 min seulement au lieu de 24 h.
5. [x] Backend : export GPX / XCTrack, Dockerfile, README (image Docker non construite : pas de démon ici).
6. [x] Frontend : types et UI « Balises en direct », chip 15 min, couche zones sensibles, tests contre
   le vrai backend (`npm run check:contract`, `npm run e2e`), captures `docs/screenshots/` (8 fichiers, 3 Mo).
   Corrigé à l'intégration : un 503 JSON du backend (source indisponible en live) n'est plus pris pour une panne
   du backend (avant : bascule silencieuse sur des plans SYNTHÉTIQUES) ; 503 au lieu de 500 sur toutes les routes
   quand une source manque ; `/api/sites` servi en live même sans MNT ; couches en échec signalées sur la carte ;
   message « relief indisponible » compréhensible en décollage libre ; anciennes routes classiques masquées en
   mode libre ; atterros candidats au-dessus des balises ; clic de pose du déco non intercepté par un marqueur ;
   bandeau « Touche la carte… » et puces d'horizon non tronqués à 375 px.
   - [ ] **Parcours live complet à refaire quand le quota Open-Meteo est revenu** (09/10/2026 : 429 « Daily API
     request limit exceeded » sur l'adresse de sortie → recherche, prévisions et analyse des atterrissages en 503,
     message affiché ; ParaglidingEarth par intermittence en « connection reset » / ConnectTimeout). En live ont
     fonctionné : balises Pioupiou réelles (altitude MNT absente faute de quota), 28 espaces aériens OpenAIP,
     24 zones Biodiv'Sports, 13 sites PGE sur Annecy (2 sans altitude écartés faute de MNT). Commande :
     `node scripts/check-contract.mjs http://localhost:8014 --live --ref <demain 08:30Z>` puis
     `LABEL=live REF=<demain 10:30> node e2e/parcours.mjs` (et `VIEW=mobile`).
7. [ ] Expert : valeurs pour les balises atterro / tendance / 15 min, puis revue des plans réels sur
   Annecy, Chamonix, Saint-Hilaire, Saint-André (mock et live).
8. **Décollage libre et atterros non officiels** (contrat : `PlanRequest.mode`, `custom_takeoff`,
   `filters.landing_policy`, `Site.official`, `Site.landing_kind`, `LandingCandidate` (+ `use`),
   `FlightPlan.landing_analysis`, `POST /api/landings/analyze`) :
   - [x] Backend, mode **classique** (défaut) : déco ET atterro officiels uniquement ; décos communautaires
     listés dans `rejected` ; `landing_analysis` = atterros officiels évalués (le 1er = l'atterro du plan).
   - [x] Backend, mode **décollage libre** : point cliqué ; altitude et exposition au MNT (grille 5 × 5 au
     pas de 100 m puis ligne de pente 150 m et profil de l'axe 300 m, 2 appels Open-Meteo Elevation,
     cache 7 j) ; seuils et contrôles du §12.6 (`app/engine/free_takeoff.py`, `terrain.py`).
   - [x] Backend, **atterros candidats** (`app/engine/landings.py`) : officiels → communautaires (PGE non
     officiels, OSM `free_flying`) → champs (OSM + MNT) selon `landing_policy` puis le niveau ; critères
     minimaux, marges renforcées, score pondéré, avertissements obligatoires, rejet expliqué, nowcast
     atterro à l'heure d'arrivée ; cône de finesse GeoJSON (`glide_cone`).
   - [x] Backend : adaptateur Overpass (`app/providers/landing_spots.py`, `OVERPASS_ENABLED=false` par
     défaut : `overpass-api.de` est bloqué ici) ; repli : terrains de démonstration FICTIFS
     (`app/fixtures/landing_spots.json`) en mode démo seulement — en live, jamais de terrain fictif.
   - [ ] Backend : valider l'adaptateur Overpass sur une vraie réponse (dès que `overpass-api.de` est
     autorisé) et enregistrer une fixture ; vérifier les hauteurs d'obstacles typiques.
   - [ ] Backend : vérification live complète (MNT réel au point, prévision réelle) : impossible le
     09/10/2026 (quota Open-Meteo épuisé sur les adresses de sortie, 429 « Daily API request limit »).
   - [x] Frontend : bascule « Classique / Décollage libre », clic sur la carte pour poser le déco, cône de
     finesse, atterros colorés par type, fiche de chaque candidat (obstacles, pente, taille, vent, `use`) —
     vérifié de bout en bout contre le backend (mock) par `frontend/e2e/parcours.mjs`.
   - [ ] Expert : valider les choix backend suivants (à reporter dans `docs/expert/revue-backend.md`) :
     données inconnues (taille, pente, obstacle) = pas d'exclusion mais sous-score réduit + note ;
     approche : obstacle > 10 m à < 150 m dans l'axe = exclusion, longueur utile = L − (5 h − distance) ;
     atterro officiel au vent d'arrivée trop fort non exclu de la sélection (le plan le juge,
     `LANDING_WIND`) ; atterro PGE non officiel = usage « occasional » ; usage du MNT 90 m pour la pente ;
     coordonnées de l'atterro de démo de Doussard ramenées sur la position PGE / Pioupiou 1720 (45,7820 ;
     6,2224), hors de la réserve du Bout du Lac (l'ancienne position, 45,789, tombait 58 m dans le polygone
     Biodiv'Sports : faux positif SENSITIVE_AREA signalé par l'agent balises).
   - Piste « communauté » non disponible en API ouverte : points d'atterrissage tirés des traces
     XContest (pas d'API publique) ; à étudier plus tard.
9. [ ] Commit final propre, puis proposition de PR.
