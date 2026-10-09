# Paraglide Manager — backend

API FastAPI (Python 3.12, gestionnaire `uv`) qui croise prévisions multi-modèles, balises temps réel,
sites de vol libre, espaces aériens et zones sensibles pour proposer des plans de vol en parapente
(France, Alpes en priorité). Le contrat d'API (source de vérité avec le frontend) est dans
[`docs/API_CONTRACT.md`](../docs/API_CONTRACT.md) ; les règles métier viennent du
[cahier des charges pilote](../docs/expert/cahier-des-charges-pilote.md).

> Outil d'aide à la décision : il ne remplace ni l'analyse du pilote sur place, ni l'observation des
> conditions réelles, ni les consignes du site, ni la consultation des NOTAM / SUP AIP.

## Installation

```bash
cd backend
uv sync                                   # dépendances (dont outils de dev : pytest, ruff)
cp .env.example .env                      # puis renseigner les clés éventuelles
uv run uvicorn app.main:app --reload --port 8000
```

- Documentation interactive : http://localhost:8000/docs
- Tests : `uv run pytest -q` — lint : `uv run ruff check .`
- Vérification des sources live : `uv run python -m app.check_sources` (voir plus bas)

### Docker

```bash
docker build -t paraglide-backend backend/
docker run --rm -p 8000:8000 --env-file backend/.env paraglide-backend
# ou, à la racine du dépôt : docker compose up --build   (frontend sur http://localhost:8080)
```

Image `python:3.12-slim` + `uv`, dépendances figées par `uv.lock`, utilisateur non privilégié,
`uvicorn` sur le port 8000, sonde de santé sur `/api/health`. Le fichier `.env` n'est jamais copié
dans l'image : les clés sont passées à l'exécution.

## Variables d'environnement

Toutes sont décrites dans [`.env.example`](.env.example) ; aucune n'est obligatoire.

| Variable | Défaut | Rôle |
|---|---|---|
| `DATA_MODE` | `auto` | `auto` : sources réelles avec repli sur la démo en cas d'échec ; `live` : sources réelles seulement ; `mock` : données de démonstration, aucun appel réseau |
| `HTTP_TIMEOUT_S` | `5` | délai par appel HTTP |
| `LIVE_RETRY_AFTER_S` | `120` | en mode `auto`, une source en échec n'est pas retentée avant ce délai |
| `OPEN_METEO_MODELS` | `meteofrance_arome_france_hd,icon_d2,ecmwf_ifs025` | modèles interrogés ensemble |
| `OPEN_METEO_API_KEY` | vide | offre commerciale Open-Meteo uniquement |
| `OPENAIP_API_KEY` | vide | espaces aériens OpenAIP (clé gratuite, compte openaip.net → *API clients*) |
| `AIRSPACE_OPENAIR_DIR` | `data/airspaces` | fichiers OpenAir locaux (repli sans clé, voir [`data/airspaces/README.md`](data/airspaces/README.md)) |
| `FFVL_API_KEY` | vide | sites et balises FFVL (clé à demander à la FFVL) |
| `SPOTAIR_*`, `METEO_PARAPENTE_*` | vide | pas d'API publique : accord nécessaire, aucun scraping |
| `CACHE_TTL_*_S` | 2 min à 7 j | durées de cache mémoire par type de donnée |
| `SYNTHETIC_SCENARIO` | vide | force un scénario de météo synthétique en mode `mock` |
| `CORS_ORIGINS`, `LOG_LEVEL` | dev Vite, `INFO` | serveur |

Les clés ne sont jamais écrites dans les logs, les messages d'erreur ni les réponses de l'API
(`/api/sources` indique seulement « clé configurée » ou non).

## Sources de données, licences et attributions

| Source | Données | Accès | Licence / attribution |
|---|---|---|---|
| **Open-Meteo** (`api.open-meteo.com`) | Prévisions horaires AROME France HD 1,3 km (Météo-France), ICON-D2 2,2 km (DWD), ECMWF IFS 0,25° ; niveaux de pression ; MNT (Elevation API, Copernicus 90 m) | libre, sans clé, usage non commercial | **CC BY 4.0** : afficher « Weather data by Open-Meteo.com » avec un lien ; données sources Météo-France, DWD, ECMWF (open data) |
| **Pioupiou / OpenWindMap** (`api.pioupiou.fr`) | Balises vent temps réel (moyen, rafale, direction) | libre | « (c) contributors of the OpenWindMap wind network <https://www.openwindmap.org> » ; conditions : https://developers.pioupiou.fr/data-licensing |
| **OpenAIP** (`api.core.openaip.net`) | Espaces aériens (géométrie, classes, planchers / plafonds) | clé gratuite, Cloudflare (429 possible) | **CC BY-NC 4.0** : citer « © openAIP » ; usage non commercial |
| **ParaglidingEarth** (`https://www.paraglidingearth.com` uniquement) | Sites : décollages, atterrissages documentés, orientations, altitudes, consignes | libre | citer ParaglidingEarth et lier chaque fiche (`url` du site) ; conditions de réutilisation à confirmer sur la page API du site (usage non commercial) |
| **Biodiv'Sports** (`biodiv-sports.fr`) | Zones sensibles faune / réglementaires pour la pratique « aérien » (mois de sensibilité, hauteur de survol, règles) | libre | citer Biodiv'Sports (LPO et partenaires) et le lien de chaque zone (`url`) ; conditions de réutilisation à confirmer auprès de Biodiv'Sports |
| Fichiers **OpenAir** locaux | Espaces aériens (repli sans clé) | fichiers déposés par l'utilisateur | selon la source du fichier (voir `data/airspaces/README.md`) |
| **FFVL** (`data.ffvl.fr`) | Terrains et balises officiels | clé sur demande | selon l'accord FFVL — désactivé sans clé |
| Fixtures (`app/fixtures/`) | Sites, balises, zones et espaces de démonstration | local | approximatifs, **jamais pour naviguer** |

Chaque réponse de l'API liste les sources réellement utilisées (`sources[]`, mode `live` / `mock`),
à afficher avec leurs attributions (page Sources du frontend, attributions de la carte).

### Constats sur les vraies réponses (tests/fixtures/)

- **Open-Meteo** : avec plusieurs modèles, chaque variable est suffixée (`temperature_2m_icon_d2`) ;
  avec un seul modèle, pas de suffixe. AROME HD : surface seulement (pas de niveaux de pression, ni
  `cloud_cover` total — reconstruit à partir des couches —, ni rayonnement), ~42 h d'échéance ;
  ICON-D2 : 9 niveaux 1000…500 hPa, ~48 h ; ECMWF : 1000/925/850/700/600/500 hPa. Valeurs `null` en
  bout d'horizon (heures ignorées). `wind_speed_unit=kmh`, `timezone=GMT` (unités contrôlées via
  `hourly_units`). `elevation=<alt du site>` ramène la température à l'altitude du déco. Quota :
  `429 {"error": true, "reason": "Daily API request limit exceeded…"}` → repli sur la météo
  synthétique en mode `auto`. Open-Meteo compte une requête de plus de 10 variables comme plusieurs
  appels : la requête complète (61 variables) pèse au moins 6 appels par point, davantage si les
  modèles sont comptés séparément.
- **OpenAIP** : racine `{items, limit, page, nextPage}` (pas de `totalCount` ; `nextPage` absent sur
  la dernière page). Limites `{value, unit, referenceDatum}` : unit 0 = m, 1 = ft, 6 = FL ; datum
  0 = sol, 1 = MSL, 2 = STD. `icaoClass` 0…6 = A…G, 8 = non classé. Types : 1 R, 2 D, 3 P, 4 CTR,
  7 TMA, 8 TRA, 9 TSA, 10 FIR, 26 CTA, 33 secteur FIS (= SIV), 34 LTA… Les SIV / FIR sont de
  l'information seulement ; les zones R / D / TRA / TSA sont « activité à vérifier ».
- **ParaglidingEarth** : `getBoundingBoxSites.php?north&south&east&west&limit&style=detailled` →
  GeoJSON de décollages, propriétés en chaînes (`takeoff_altitude` « -1 » si inconnue, secteurs
  N…NW notés 0/1/2, `ffvl_site_id`, objet `landing` si l'atterro est documenté). Le http et le domaine
  sans `www` sont refusés : URL forcée en `https://www.`.
- **Biodiv'Sports** : `sensitivearea/?in_bbox=…&practices=3&period=ignore&format=geojson` ; le
  paramètre `bbox` est ignoré ; `format=geojson` exige un en-tête `Accept` GeoJSON (sinon HTTP 406) ;
  la règle `PARAGLIDING-FORBIDDEN` (ex. réserve naturelle du Bout du Lac d'Annecy) est reprise dans la
  consigne.

### Statut « officiel » des sites ParaglidingEarth

PGE n'a pas de drapeau officiel. Règle retenue (`Site.official`, `Site.landing_kind`, cahier §12.7),
à valider par l'expert : un déco est **référencé** s'il est lié à une fiche FFVL (`ffvl_site_id` > 0)
ou si sa fiche est complète (altitude connue et au moins une orientation notée), sauf mention
« sauvage / non officiel / interdit » dans le nom ; sinon il est **communautaire**
(`official = false`). L'atterro documenté d'un déco référencé est `official`, sinon `community`.
Les doublons (< 100 m, ou < 300 m avec nom proche ou orientations communes) sont fusionnés en
gardant la source prioritaire (fixture > FFVL > PGE > SpotAir) puis la fiche la plus complète ; les
références d'atterros fusionnés sont réécrites.

## Algorithme (vue d'ensemble)

Tous les seuils sont dans [`app/engine/rules.py`](app/engine/rules.py) (repris du cahier des charges).

1. **Collecte** (`app/services.py`) : sites de la zone (fusion dédoublonnée, altitudes manquantes
   corrigées par le MNT), prévisions Open-Meteo au déco et à l'atterro (altitude du site imposée),
   balises proches, espaces aériens (OpenAIP > OpenAir > démo), zones sensibles. Chaque source a son
   cache ; en mode `auto`, une source en échec bascule sur la démo sans bloquer la réponse.
2. **Analyse météo** (`app/meteo/`) : moyenne multi-modèles (vectorielle pour le vent) et dispersion
   → confiance ; profil vertical à partir des niveaux de pression (niveaux sous le sol ignorés) ;
   plafond thermique par la méthode de la particule (T sol + surchauffe, adiabatique sèche), base des
   cumulus (Espy : 125 m × (T − Td)), plafond utile = min(plafond, base − 300 m), W* de Deardorff et
   vario moyen, CAPE / LI et risque de surdéveloppement.
3. **Conditions au site** (`app/engine/conditions.py`) : vent interpolé à l'altitude du déco entre
   le 10 m du modèle et les niveaux de pression, correction par les balises pondérée selon
   l'horizon (forte à 15-30 min, nulle au-delà de 12 h), brises de vallée.
4. **Variantes et routes** (`app/engine/routing.py`) : plouf, local thermique, soaring, cross ;
   finesse sol = finesse polaire × k(niveau) × (V_air + vent arrière projeté) / V_air ; contrôle
   « toujours un atterro dans le cône » tous les 500 m pour le cross ; plafond limité par l'espace
   aérien le plus bas au-dessus de la route (− 100 m) et par le FL115.
5. **Filtres et verdict** (`app/engine/findings.py`, `scoring.py`) : no-go absolus (§3), seuils par
   niveau de pilote (§2, bande marginale 80-100 %), score pondéré non compensatoire (vent au déco 25,
   vent en altitude 15, atterro 15, thermiques 15, durée 10, stabilité 10, confiance 5, site 5),
   verdict `go` / `marginal` / `no_go`, difficulté du plan.
6. **Espaces et zones** (`app/engine/airspace.py`) : classes A-D et P interdites (traversée = no-go),
   classe E autorisée en VMC (info), R / ZRT / D / TRA / TSA « à vérifier » (activations inconnues),
   SIV / FIR information seulement ; zones sensibles actives au mois du vol → risque `SENSITIVE_AREA`.
7. **Briefing** (`app/engine/briefing.py`) : textes en français, checklist, exports GPX et XCTrack.

## Vérification des sources : `app.check_sources`

```bash
uv run python -m app.check_sources                      # un vrai appel par source, zone d'Annecy
uv run python -m app.check_sources --save-fixtures /tmp/reponses   # + réponses brutes (JSON)
uv run python -m app.check_sources --only open-meteo,biodivsports  # ou --skip openaip
```

Sources : Open-Meteo prévision (Forclaz, 3 modèles) et Elevation, ParaglidingEarth, Pioupiou,
OpenAIP (si clé), OpenAir local (si fichiers), Biodiv'Sports, sur la bbox
`6.05,45.75,6.35,45.95`. Le tableau donne l'état, le(s) code(s) HTTP, le nombre d'éléments analysés
par le vrai parseur, la durée et l'erreur précise. Code de sortie 1 si une source attendue échoue
(une source désactivée faute de clé ou de fichier n'est pas attendue). La clé OpenAIP n'est jamais
affichée (« clé configurée ») ni enregistrée ; OpenAIP n'est pas rappelé moins de 5 min après le
dernier appel (limitation Cloudflare). Exemple (09/10/2026) :

```text
Source                 | État      | HTTP    | Éléments | Durée  | Détail / erreur
-----------------------+-----------+---------+----------+--------+-----------------------------------------
Open-Meteo prévision   | OK        | 200     | 111      | 1.62 s | arome_france_hd 37 h/0 niv., icon_d2 37 h/9 niv., ecmwf_ifs025 37 h/6 niv.
Open-Meteo Elevation   | OK        | 200     | 2        | 0.05 s | Forclaz 1244 m, Doussard 463 m
ParaglidingEarth       | OK        | 200     | 14       | 1.05 s | 10 décos, 4 atterros ; 5 décos sans orientation, 2 sans altitude
Pioupiou / OpenWindMap | OK        | 200     | 700      | 1.98 s | 5 dans la zone (dont 4 à jour)
OpenAIP                | OK        | 200     | 23       | 1.05 s | clé configurée ; classes : C 4, D 4, E 4, R 2, SIV 8, UNCLASSIFIED 1
OpenAir local          | DÉSACTIVÉ | -       | -        | 0.00 s | aucun fichier OpenAir dans backend/data/airspaces
Biodiv'Sports          | OK        | 200+200 | 17       | 2.07 s | pratiques aériennes [3] ; regulatory 4, species 13
```

## Tests

`uv run pytest -q` exécute, sans réseau :

- `tests/test_expert_scenarios.py` : scénarios de validation métier de l'expert ;
- `tests/test_providers_*.py` : parseurs sur les **vraies réponses enregistrées** dans
  `tests/fixtures/` (Open-Meteo 3 modèles et 429, Elevation, OpenAIP page partielle et page complète,
  ParaglidingEarth, Biodiv'Sports), requêtes construites (paramètres, en-têtes, pagination bornée)
  via `httpx.MockTransport`, repli propre en cas de 429, et `check_sources` rejoué hors ligne.

Pour rafraîchir une fixture : `uv run python -m app.check_sources --only <source> --save-fixtures DIR`,
puis copier la réponse utile dans `tests/fixtures/` (jamais de clé dans une fixture).

## Limites connues

- Activations des zones R / ZRT / D / TRA / TSA et NOTAM non disponibles : toujours « à vérifier ».
- Conversion des FL en atmosphère standard (sans QNH) : marge de sécurité appliquée sous les planchers.
- Quota Open-Meteo gratuit (pondéré par le nombre de variables et de modèles) : en cas de 429, repli
  sur la météo synthétique (mode `auto`) jusqu'au prochain essai.
- FFVL, SpotAir et Météo-Parapente désactivés sans accord / clé ; sites FFVL non vérifiés faute de clé.
