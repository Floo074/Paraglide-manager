# Point de reprise

Travail mis en pause volontairement (limite de tokens). Tout est sur la branche
`claude/paraglide-flight-planner`. La clé OpenAIP est dans `backend/.env` (non versionné) :
à recréer si la session est neuve (`OPENAIP_API_KEY=...`).

## État au moment de la pause

- **Backend** : 34 tests passent. Moteur d'évaluation, seuils (`app/engine/rules.py`), calculs
  aérologiques, providers (Open-Meteo, ParaglidingEarth, Pioupiou, OpenAIP, OpenAir,
  Biodiv'Sports), `main.py` présents. En cours : lot 6 du moniteur dans `engine/planner.py`
  (points 6.1 à 6.9 et 6.11).
- **Frontend** : pages Planification, Détail du plan, Sources, À propos. En cours : mise à jour
  des types pour l'horizon 15 min, `Beacon.trend`, `StationReading`, `station_readings`.
- **Expert** : cahier des charges (rév. 2), 32 scénarios (`docs/expert/scenarios-validation.*`),
  journal `docs/expert/revue-backend.md`. Les 32 scénarios passaient sur le moteur.

## Reste à faire (dans l'ordre)

1. Backend : terminer le lot 6 (voir `docs/expert/revue-backend.md`).
2. Backend : `tests/test_expert_scenarios.py` à partir de `docs/expert/scenarios-validation.yaml`.
3. Backend : balises au déco ET à l'atterro (heure d'arrivée), horizon `15m`, altitude des
   balises Pioupiou via Open-Meteo Elevation (sinon elles sont ignorées), tendance via
   `https://api.pioupiou.fr/v1/archive/{id}?start=last-hour&stop=now`, `station_readings`
   (contrat : `docs/API_CONTRACT.md`).
4. Backend : valider chaque source live sur de vraies réponses ; commande `app.check_sources` ;
   parseur OpenAIP calé sur la vraie réponse (unit 1=ft, 6=FL ; datum 0=GND, 1=MSL, 2=STD ;
   classe 8 = SIV → info seulement) ; URL ParaglidingEarth en `https://www.` uniquement.
5. Backend : export GPX / XCTrack, Dockerfile, README.
6. Frontend : types et UI « Balises en direct », chip 15 min, couche zones sensibles,
   tests contre le vrai backend, captures `docs/screenshots/`.
7. Expert : valeurs pour les balises atterro / tendance / 15 min, puis revue des plans réels
   sur Annecy, Chamonix, Saint-Hilaire, Saint-André (mock et live).
8. Commit final propre, puis proposition de PR.
