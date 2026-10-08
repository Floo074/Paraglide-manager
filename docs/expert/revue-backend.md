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
| 1.1 | `rules.py` = bloc YAML CDC §11 (mêmes clés et valeurs) | envoyé |
| 1.2 | Verdict non compensatoire, `score ≤ 40 + min(sous-scores sécurité)`, seuils go 65 / no-go 45 | envoyé |
| 1.3 | Bande marginale 80-100 % ; interpolation des sous-scores ; vent nul = 80 | envoyé |
| 1.4 | Vent au déco interpolé à l'altitude réelle du déco ; rafales mises à l'échelle | envoyé |
| 1.5 | Écart angulaire / travers / arrière / composante de travers | envoyé |
| 1.6 | Dévent : vent à déco + 300 m ≥ 15 km/h venant de > 120° de l'axe → no-go `LEE_SIDE` | envoyé |
| 1.7 | Vent en altitude seulement sur les niveaux atteints ; no-go absolu 45 km/h, et 50 km/h à 3000 m | envoyé |
| 1.8 | Atterro évalué à l'heure d'arrivée + brise de vallée × 1.3 (13-17 h) | envoyé |
| 1.9 | Formule de finesse sol (k niveau, V_air 37, composante vent, marge d'arrivée) | envoyé |
| 1.10 | Plafond utile = min(plafond, base − 300) ; altitude max ≤ FL115 − 100 m | envoyé |
| 1.11 | Calcul de `difficulty` du plan et rejet si > niveau demandé | envoyé |
| 1.12 | Beginner : pas de cross, ≤ 45 min, créneau hors pic thermique | envoyé |
| 1.13 | Fin de créneau = min(fin convection + 30 min, surdév − 1 h, coucher − 30 min) ; ne pas étirer la durée | envoyé |
| 1.14 | Diversité : au plus 2 plans par déco | envoyé |
| 1.15 | Catalogue des codes `Risk` standardisés | envoyé |
| 1.16 | Point d'entrée moteur pour les tests de scénarios | envoyé, en attente de réponse |

## Réponses du backend

_(à compléter)_

## Lots envoyés au frontend

_(à compléter)_

## Désaccords remontés au coordinateur

_(aucun pour l'instant)_
