# Architecture — Paraglide Manager

Outil d'aide à la décision pour parapentistes : pour une zone choisie sur une carte et un horizon
(30 min → 48 h), proposer les meilleurs plans de vol filtrés (durée, difficulté, thermiques), avec
briefing complet, GPX / tâche XCTrack et carte interactive des indicateurs météo/aérologiques.

> ⚠️ Outil d'aide à la décision : il ne remplace jamais l'analyse du pilote sur place.

## Arborescence

```
backend/            FastAPI (Python 3.12+), moteur météo + algorithme de plans de vol
  app/
    main.py         création de l'app, routes /api
    config.py       réglages (env vars, clés API, mode live/mock)
    models.py       modèles Pydantic = docs/API_CONTRACT.md
    providers/      un adaptateur par source de données (live + repli fixtures/synthétique)
    meteo/          calculs aérologiques (plafond, base, W*, vario, émagramme, nowcasting)
    engine/         sélection des sites, scoring, routage, difficulté, risques, briefing
      rules.py      TOUS les seuils métier (vent, rafales, CAPE…) — réglables par l'expert
    export/         GPX, XCTrack
    fixtures/       données hors-ligne (sites, balises, espaces aériens)
  tests/            pytest
frontend/           React + TypeScript + Vite + Leaflet
docs/
  API_CONTRACT.md   contrat d'API partagé (source de vérité)
  ARCHITECTURE.md   ce fichier
  expert/           cahier des charges et revues du pilote expert
docker-compose.yml
```

## Sources de données

| Source | Usage | Accès |
|---|---|---|
| Open-Meteo (AROME France HD, ICON-D2, ECMWF IFS) | prévisions sol + niveaux de pression | libre, sans clé |
| Open-Meteo Elevation | altitude terrain | libre |
| FFVL (data.ffvl.fr) | sites (déco/atterro), balises | balises libres ; terrains via clé API FFVL |
| ParaglidingEarth | sites mondiaux (GeoJSON) | libre |
| Pioupiou / OpenWindMap | balises vent temps réel | libre |
| OpenAIP | espaces aériens | clé API gratuite |
| SpotAir | sites / spots | pas d'API publique → adaptateur prêt, nécessite accord/partenariat |
| Météo-Parapente | prévisions dédiées vol libre | pas d'API publique → adaptateur prêt, nécessite accord/licence |
| KK7 thermal maps | couche "hotspots" thermiques (tuiles) | côté carte uniquement |

Chaque fournisseur a un **mode live** et un **repli mock** (fixtures + météo synthétique
déterministe), activé par `DATA_MODE=mock|live|auto` (auto = live avec repli mock en cas d'erreur).
Indispensable car l'environnement de développement n'a pas accès à ces hôtes.

## Principe de l'algorithme

1. **Candidats** : décollages de la zone (fusion des sources), avec atterrissages associés.
2. **Météo** au temps cible T = maintenant + horizon : multi-modèles, profil vertical, calculs
   aérologiques (plafond thermique, base des cumulus, W*, vario, surdéveloppement, foehn).
   Pour T ≤ 2 h : **nowcasting** — correction du vent prévu par les balises proches.
3. **Filtres durs** (no-go) : pluie, orage, vent/rafales hors limites, vent de travers/arrière,
   base des nuages sous le déco, vent fort en altitude, foehn.
4. **Routage** : vol local / soaring / cross (triangle ou aller-retour) selon thermiques, vent,
   durée souhaitée, finesse de l'aile, atterrissages accessibles.
5. **Scoring** pondéré + difficulté estimée + niveau de confiance → classement.
6. **Briefing** : risques, créneau, checklist, sources ; exports GPX / XCTrack.
