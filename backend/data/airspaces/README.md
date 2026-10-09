# Espaces aériens locaux (format OpenAir)

Ce dossier sert de **repli sans clé** pour les espaces aériens. Ordre de priorité dans le backend :

1. **OpenAIP** (API, clé gratuite `OPENAIP_API_KEY`) ;
2. **fichiers OpenAir de ce dossier** (si OpenAIP est absent ou en échec) ;
3. espaces de démonstration approximatifs (fixtures) — à ne jamais utiliser pour naviguer.

Tout fichier `.txt`, `.air` ou `.openair` déposé ici est chargé au démarrage puis relu dès que sa
date de modification change (pas besoin de redémarrer). Les autres fichiers (dont ce README) sont
ignorés. Le dossier peut être changé avec `AIRSPACE_OPENAIR_DIR`.

## Où trouver un fichier OpenAir pour la France

| Source | Contenu | Remarques |
|---|---|---|
| **planeur-net** — dépôt GitHub `planeur-net/airspace` (fichier `france.txt`) | Espaces aériens France métropolitaine (CTR, TMA, CTA, SIV, R, D, P, ZRT, LTA…) | Maintenu par la communauté vol à voile, mis à jour à chaque cycle AIRAC |
| **XContest** — `airspace.xcontest.org` | Export OpenAir par pays (France, Suisse, Italie…) | Compte XContest nécessaire pour télécharger |
| **OpenAIP** — rubrique *Data / Exports* du site openaip.net | Fichier par pays au format OpenAir (`fr_asp.txt`) | Mêmes données que l'API (licence CC BY-NC 4.0) |
| **Fédération (FFVL)** — rubrique espace aérien du site fédéral | Cartes et fichiers pour instruments de vol libre | Vérifier le format proposé (OpenAir) |

Pour un vol près d'une frontière (Annecy → Genève, Chamonix → Suisse / Italie), ajouter aussi le
fichier du pays voisin : tous les fichiers du dossier sont fusionnés.

La source officielle reste le **SIA** (AIP France, cartes OACI, SUP AIP) : un fichier OpenAir est une
transcription, il peut être en retard d'un cycle AIRAC (28 jours) ou contenir des erreurs. Ne
jamais l'utiliser sans vérifier les NOTAM, SUP AIP et l'activation des zones (R, ZRT, D, TRA, TSA,
réseau très basse altitude défense / AZBA) le jour du vol.

## Format pris en charge

Commandes OpenAir lues : `AC` (classe), `AN` (nom), `AY` (type, extension récente), `AL` / `AH`
(plancher / plafond), `DP` (point), `V X=` (centre), `V D=` (sens des arcs), `DA` (arc par angles),
`DB` (arc entre deux points), `DC` (cercle, rayon en NM). Les commentaires commencent par `*`.

- Classes : `A`…`G` ; `R` (réglementée), `Q` (dangereuse), `P` (interdite), `GP` (interdite aux
  planeurs, traitée comme `P`), `CTR` (traitée comme classe D), `RMZ`, `TMZ`, `W`, `SIV`.
- Altitudes : `SFC` / `GND` (sol), `FL115`, `1500ft`, `1500 ft AMSL`, `300 m AGL`, `2000 ft ASFC`,
  `UNLIM`. Les FL sont convertis en atmosphère standard (× 30,48 m, sans QNH) ; les hauteurs « sol »
  sont converties en altitude avec le MNT (Open-Meteo Elevation) au centre de la zone.
- Encodage : UTF-8, sinon Windows-1252 / Latin-1 (fréquent pour les fichiers français).

Vérifier le chargement : `uv run python -m app.check_sources --only openair` (ligne « OpenAir local »
du tableau : nombre de fichiers, nombre d'espaces au total et dans la zone d'Annecy).
