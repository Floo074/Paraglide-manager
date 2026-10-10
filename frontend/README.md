# Paraglide Manager — frontend

Interface web (React 18 + TypeScript + Vite + Leaflet) de **Paraglide Manager**, outil d'aide à la
planification de vols en parapente : choix d'une zone sur la carte, critères du pilote, plans de vol
classés, fiche détaillée (briefing, météo, émagramme, carte, GPX / XCTrack).

> Outil d'aide à la décision : il ne remplace pas l'analyse du pilote sur place.

Le contrat d'API partagé avec le backend est dans [`../docs/API_CONTRACT.md`](../docs/API_CONTRACT.md) ;
sa transcription TypeScript exacte est dans `src/api/types.ts`.

## Démarrage rapide

Prérequis : Node.js 20+ (testé avec Node 22) et npm.

```bash
cd frontend
npm install

# 1) Démonstration sans backend (données synthétiques, tout fonctionne hors-ligne)
npm run dev:mock          # http://localhost:5173

# 2) Avec le backend FastAPI sur http://localhost:8000 (proxy Vite /api → :8000)
npm run dev
```

Si le backend ne répond pas (réseau, 502/504, réponse non JSON), le site **bascule automatiquement en
données de démonstration** et affiche un bandeau rouge « Données de démonstration » ; il retente la
connexion toutes les 60 s (bouton « Réessayer »). Un **503 JSON** vient du backend lui-même (source
indispensable indisponible en live, ex. quota Open-Meteo) : le message est affiché tel quel, sans bascule
en démonstration ; une couche de carte en échec (sites, balises…) est signalée par un bandeau sur la carte.

### Autres commandes

| Commande | Rôle |
|---|---|
| `npm run build` | vérification de types (`tsc --noEmit`) puis build de production dans `dist/` |
| `npm run preview` | sert `dist/` sur http://localhost:4173 (avec le même proxy `/api`) |
| `npm run typecheck` | `tsc --noEmit` seul |
| `npm run lint` | ESLint (TypeScript, règles des hooks React) |
| `npm test` | tests unitaires Vitest (conversions, formats, heure cible, zones, exports, moteur de démo, erreurs d'API) |
| `npm run check:contract -- http://localhost:8014` | valide les vraies réponses du backend contre `src/api/types.ts` (voir « Intégration ») |
| `npm run e2e` | parcours Playwright contre le vrai backend (voir « Intégration ») |

## Variables d'environnement (lues au build, préfixe `VITE_`)

Copier `.env.example` en `.env.local` :

| Variable | Défaut | Rôle |
|---|---|---|
| `VITE_USE_MOCKS` | `false` | `true` = n'appelle jamais le backend (mode démo). `npm run dev:mock` l'active sans fichier. |
| `VITE_API_PROXY_TARGET` | `http://localhost:8000` | cible du proxy `/api` de `vite dev` / `vite preview` |
| `VITE_KK7_TILES_URL` | vide | tuiles « hotspots thermiques » KK7 (couche optionnelle, désactivée par défaut). Ex. `https://thermal.kk7.ch/tiles/thermals_all_all/{z}/{x}/{y}.png?src=mon-domaine` — licence CC BY-NC-SA. |
| `VITE_KK7_TMS` | `true` | schéma TMS (axe Y inversé) des tuiles KK7 |

**Aucune clé d'API n'est nécessaire côté frontend** : les fonds de carte (OpenTopoMap, OpenStreetMap,
Esri World Imagery) sont libres d'accès. Les clés éventuelles (OpenAIP, FFVL…) se configurent côté
backend ; la page **Sources & statut** explique comment activer chaque source.

## Pages

| Route | Contenu |
|---|---|
| `/` | **Planification** : carte plein écran (relief OpenTopoMap par défaut, OSM, satellite Esri), zone en rectangle ou cercle (deux appuis / un appui + poignées centre et rayon), zones prédéfinies (Annecy, Chamonix, Saint-Hilaire, Saint-André, Dune du Pilat, Puy de Dôme, Millau), « ma position » (rayon 30 km), « vue actuelle ». Sites (déco avec secteurs d'orientation, atterros), balises temps réel (flèche vers où va le vent, couleur selon les seuils du niveau choisi, rafales et âge), zones sensibles, espaces aériens, grilles météo à l'heure cible, regroupement des marqueurs à faible zoom. Critères : horizon (30 min → 48 h, heure cible affichée), heure de référence, durée (double curseur + « plouf », « 1 h », « 2-3 h », « cross »), niveau (4 brevets), thermiques, types de vol, finesse. Résultats classés + « Pourquoi pas ces sites ? ». Zone et horizon mémorisés (localStorage) et partageables (`?zone=c:45.81,6.2,18&h=2h`). |
| `/plan/:id` | **Fiche plan de vol**, dans l'ordre d'un briefing de moniteur : verdict (GO / LIMITE / NO-GO, niveau requis, confiance, pourquoi) → créneau en heure légale + frise ±3 h → vent (déco, 1500/2000/3000 m, atterro à l'arrivée) → briefing → carte (route colorée par altitude, waypoints avec ETA, rayons de plané, espaces aériens, zones sensibles, balises, couches météo commutables avec curseur horaire, KK7 en option) + itinéraire et profil → aérologie (fenêtre convective, plafond utile, base, surdéveloppement, graphiques détaillés et émagramme repliés) → risques → atterrissage → espaces aériens et zones sensibles → checklist cochable → urgence (112, 143,9875 MHz, coordonnées à copier) → exports GPX / XCTrack, partage, impression A4 → détails techniques repliés (score, sources). |
| `/sources` | **Sources & statut** (`/api/sources`) : mode réel / simulé / désactivé, clé requise / configurée, message du backend et aide « Comment l'activer » (`FFVL_API_KEY`, `OPENAIP_API_KEY`, fichiers OpenAir dans `backend/data/airspaces/`…). |
| `/a-propos` | Méthode de calcul, seuils de vent par niveau, règles de priorité, données et licences, limites. |

Thème clair / sombre (suit le système, forçable avec le bouton en haut à droite). Mise en page
mobile d'abord (panneau coulissant sur la carte à 375 px), deux colonnes sur grand écran.
Impression : feuille de vol A4 (carte remplacée par un croquis vectoriel de la route, sections
repliées dépliées automatiquement).

## Mode démonstration (`src/mocks/`)

Tout le contrat est simulé dans le navigateur, avec les mêmes chemins et formes de réponse :

- `sites.ts` : sites approximatifs (Forclaz 1250 m → Doussard 460 m, Planfait, Montmin, Semnoz Est/Ouest,
  Mont Veyrier fermé ; Planpraz, Plan de l'Aiguille ; Saint-Hilaire ; Chalvet ; Dune du Pilat ;
  Puy de Dôme ; Puncho d'Agast).
- `weather.ts` : météo **synthétique déterministe** (aujourd'hui : anticyclonique, brise de NO,
  cumulus ; demain : flux d'ouest fort en altitude ; après-demain : dégradation orageuse), cycle diurne
  calé sur la position du soleil, brises de pente, sondage, grilles (vent par altitude, vario, plafond,
  base, CAPE, pluie).
- `planner.ts` + `rules.ts` : moteur de plans simplifié suivant le cahier des charges pilote
  (`docs/expert/`) : filtres no-go puis score non compensatoire, seuils par niveau, routes plouf /
  local / soaring / cross, briefing dans l'ordre moniteur. Les identifiants de plans de démo
  (`demo_…`) encodent la requête : un lien de démo partagé se recalcule.
- `beacons.ts`, `airspaces.ts`, `sensitiveAreas.ts`, `sources.ts` : balises, espaces aériens et zones
  sensibles **fictifs/approximatifs**, statut des sources.

Les plans de démo sont marqués « Démo hors-ligne : données synthétiques » partout (liste, fiche,
briefing, risque `MOCK_DATA`). Ne jamais les utiliser pour voler.

## Structure

```
src/
  api/          types.ts (contrat), client.ts (fetch + repli démo), errors.ts, planCache.ts
  mocks/        API simulée (voir ci-dessus)
  config/       libellés FR, zones prédéfinies, fonds de carte, seuils de vent par niveau
  utils/        unités, formats (heure légale Europe/Paris), horizon, zones, géo, soleil, couleurs, exports GPX/XCTrack
  hooks/        useAsync, usePersistentState, useTheme, useApiMode, useNow, useMediaQuery
  components/
    layout/     en-tête, bandeau démo, avertissement
    map/        MapShell, contrôles, icônes, sites, balises (regroupées), zones, routes, grilles météo
    planner/    critères, résultats, cartes de plans
    plan/       blocs de la fiche (verdict, créneau, vent, aérologie, émagramme, graphiques…)
    ui/         badges, puces, jauges, toast
  pages/        PlannerPage, PlanDetailPage, SourcesPage, AboutPage
  styles/       base (jetons clair/sombre), layout, components, map, plan, print
  test/         tests Vitest
```

## Docker

```bash
docker build -t paraglide-frontend ./frontend
docker run -p 8080:80 --network <réseau-du-backend> paraglide-frontend
# variables d'exécution : BACKEND_UPSTREAM (défaut http://backend:8000), NGINX_RESOLVER (défaut 127.0.0.11)
# variables de build : --build-arg VITE_USE_MOCKS=true, --build-arg VITE_KK7_TILES_URL=...
```

Image en deux étapes : build Vite (Node 22) puis nginx qui sert `dist/` (routes SPA → `index.html`)
et relaie `/api/` vers le service `backend:8000`. La résolution DNS se fait à la volée : le conteneur
démarre même si le backend est absent (le site passe alors en démonstration).

## Intégration avec le vrai backend

```bash
# backend (port libre au choix) puis front en dev, proxy /api pointé dessus
cd backend  && DATA_MODE=mock uv run uvicorn app.main:app --port 8014
cd frontend && VITE_API_PROXY_TARGET=http://localhost:8014 npx vite --port 5180 --strictPort

# 1) contrat : chaque endpoint appelé pour de vrai, réponses typées contre src/api/types.ts (tsc)
node scripts/check-contract.mjs http://localhost:8014 [--live] [--ref 2026-10-11T08:30:00Z]

# 2) parcours navigateur (Chromium préinstallé, playwright-core local ou global de npm)
BASE=http://localhost:5180 REF=2026-10-11T10:30 node e2e/parcours.mjs          # bureau 1440 px
BASE=http://localhost:5180 REF=2026-10-11T10:30 VIEW=mobile node e2e/parcours.mjs
```

Le parcours : zone Annecy → horizon 30 min → recherche → fiche plan (bloc « Balises en direct »,
carte et couches, fond satellite, GPX / XCTrack téléchargés et vérifiés, « Actualiser les balises »,
rechargement de l'URL) → décollage libre (clic sur la carte, analyse des atterrissages, cône, recherche
depuis le point) → page Sources. Il échoue sur toute erreur JavaScript en console. `REF` = heure de
référence locale (en journée : la nuit, aucun plan et seuls les sites écartés s'affichent) ;
`SHOTS=dossier` garde des captures de contrôle ; `FINAL=dossier` produit les captures ci-dessous.
En `live`, préférer `--live` pour le contrôle du contrat (moins d'appels Open-Meteo).

## Captures d'écran

[`../docs/screenshots/`](../docs/screenshots/) : planification et fiche plan (375 px et 1440 px), fiche
complète, décollage libre (cône et atterros candidats), page Sources. Produites par `e2e/parcours.mjs`
(`FINAL=…`) contre le vrai backend en `DATA_MODE=mock` (données synthétiques, vrais fonds de carte
OpenTopoMap), puis réduites à 256 couleurs.
