# Cahier des charges pilote — Paraglide Manager

> Rédigé du point de vue d'un moniteur fédéral FFVL / pilote cross & compétition (Alpes du Nord et du Sud).
> Destinataires : backend (`engine/rules.py`, scoring, routage, briefing) et frontend (carte, fiche plan).
> Unités = celles du contrat d'API : km/h, m AMSL (sauf `_agl`), m/s, degrés « d'où vient le vent ».
> Tous les seuils ci-dessous sont des **valeurs par défaut réglables** : ils doivent vivre dans `rules.py`, nulle part ailleurs.
> **Révision 2 (phase 2)** : finesse de calcul et marges recalibrées, facteur de rafale non bloquant, rotation mesurée au-dessus de la brise de pente, fenêtres orage, coucher, confiance relative à l'horizon. Validé par les scénarios chiffrés de `scenarios-validation.md`.
> **Révision 3** : §12 — horizon 15 min, balises d'atterro et tendance sur 1 h, absence de balise d'atterro, décollage libre, atterros non officiels (`community` / `field`). Scénarios S28-S32.

---

## 0. Conventions utilisées dans ce document

| Terme | Définition opérationnelle (pour l'algorithme) |
|---|---|
| **Axe du déco** | Direction (°) face à laquelle le pilote décolle = centre du secteur `orientations` du site. Un vent « de face » vient de cette direction. Si plusieurs secteurs : on prend le secteur le plus proche du vent. |
| **Écart angulaire** | `ecart = min_k |angle(vent_dir, centre_secteur_k)|` − 11,25° (demi-largeur d'un secteur de la rose 16 points), borné à 0. |
| **Vent de travers** | 0° < écart ≤ 90°. |
| **Vent arrière** | écart > 90°. |
| **Vent nul** | vent moyen < 5 km/h : la direction n'est pas significative, on ne juge ni travers ni arrière (mais on vérifie le vent à +300 m, cf. piège « faux calme »). |
| **Vent moyen / rafale** | Balise : moyenne et max sur 10 min (jamais une mesure instantanée). Modèle : `wind_10m.speed_kmh` / `gust_kmh` **interpolé à l'altitude du déco** (cf. §10). |
| **Plafond utile** | `min(thermal_ceiling_m, cloud_base_m − 300)` (VMC : 300 m sous la base au-dessus de 900 m AMSL). |
| **Vario** | `thermal_strength_ms` = vario net moyen intégré (pas le pic). Pic instantané ≈ 2 × vario moyen. Approximation : `vario ≈ max(0, W* − 1,0)`. |
| **Finesse polaire** | `wing_glide_ratio` (défaut 8,5, aile EN-B). |
| **Finesse de calcul** | Finesse prudente retenue pour vérifier qu'un atterro est accessible (§2, §5). |
| **Heure solaire** | `heure_UTC + lon/15 + équation_du_temps`. Dans les Alpes (lon ≈ 6°E) : midi solaire ≈ 13h35 heure d'été (CEST), 12h35 heure d'hiver. **Toutes les règles aérologiques sont en heure solaire** ; l'affichage est en heure légale. |

---

## 1. Besoins du pilote

### 1.1 Comment un pilote utiliserait vraiment l'outil

| Moment | Horizon | Question du pilote | Ce qu'il regarde en premier | Décision |
|---|---|---|---|---|
| **J-2 / J-1 (planif)** | 24-48 h | « Ça vole où ce week-end ? Je pose ma journée ? » | Situation générale (anticyclone/front), vent à 2000-3000 m, risque orageux, tendance | Choisir un massif / une vallée, réserver la navette, prévenir les copains |
| **La veille au soir** | 12-24 h | « Quel site, quelle heure de déco, quel type de vol ? » | Vent déco prévu à l'heure cible, plafond/base, heure de début des thermiques, heure de surdéveloppement, brise à l'atterro | Site + créneau + plan A/plan B (site de repli d'une autre orientation) |
| **Le matin** | 2-8 h | « Le plan tient-il ? » | Écart prévision/réalité sur les balises à 7-9h (direction, force en altitude), émagramme du matin, cumulus précoces | Confirmer / basculer sur le plan B / renoncer |
| **En route / au déco** | 30 min-2 h | « Je décolle maintenant ou j'attends ? » | Balises du déco et de l'atterro (moyenne + rafales 10 min), tendance sur 1 h, ciel (cumulus qui gonflent ?), autres pilotes en l'air | Go / attendre / redescendre à pied |

Conséquences pour l'outil :
- **Horizon court (30 min-2 h)** = mode « au déco » : priorité absolue aux balises, affichage de la **tendance** (vent qui forcit ou mollit sur la dernière heure), créneau restant avant forcissement de la brise / surdéveloppement.
- **Horizon long (24-48 h)** = mode « planif » : on raisonne par **massif et orientation**, on affiche la confiance et la dispersion des modèles ; ne jamais donner une précision horaire illusoire (créneaux arrondis à l'heure).
- Toujours proposer un **plan B** d'orientation différente (si le plan A est orienté S, un plan B orienté W ou N est précieux quand le vent tourne).

### 1.2 Les décisions à prendre (dans l'ordre où le pilote les prend)

1. **Est-ce volable dans le secteur ?** (no-go météo global : pluie, orage, foehn, vent fort en altitude)
2. **Quelle orientation de déco ?** (vent météo + brise au moment du décollage)
3. **Quel site pour mon niveau ?** (difficulté du déco, atterro, encombrement)
4. **Quelle heure ?** (fenêtre : après le démarrage des thermiques si je les veux, avant la brise forte / le surdéveloppement)
5. **Quel vol ?** (plouf, local, soaring, cross ; distance ; points de décision)
6. **Comment je rentre ?** (atterro, navette, coucher du soleil)

### 1.3 Ce qui manque aux outils actuels

| Outil | Force | Manque |
|---|---|---|
| Météo-Parapente | Émagrammes, plafond, vent par niveau, base, très lisible | Pas de lien avec les sites/déco/atterros ni avec le niveau du pilote ; pas de croisement balises ; pas de plan de vol |
| SpotAir | Fiches sites, orientations, carte | Pas de décision « go/no-go » contextualisée, pas d'aérologie horaire |
| Balises FFVL / Pioupiou / OpenWindMap | Réalité terrain | Instantané uniquement, qualité d'implantation variable, pas d'interprétation (thermique cyclique vs vent météo) |
| RASP / KK7 | Champs convectifs, hotspots, skyways | Aucune notion de sécurité (vent déco, atterro, espaces aériens) |
| XContest | Ce qui a été fait historiquement | Biais vers les jours exceptionnels ; aucun lien avec la météo du jour |
| OpenAIP / cartes FFVL | Espaces aériens | Activations (R, ZRT, AZBA, NOTAM) souvent absentes ; pas de zones environnementales |

**La valeur ajoutée de Paraglide Manager = le croisement** : *site (orientations, consignes) × vent au déco à l'heure T × aérologie (fenêtre thermique, plafond, surdév) × brise à l'atterro à l'heure d'arrivée × niveau du pilote × espaces aériens/zones sensibles*, avec un verdict expliqué.

### 1.4 Comment croiser les sources (méthode pilote)

1. **Synoptique** (ECMWF/ICON) : flux dominant à 700 hPa (~3000 m) et 850 hPa (~1500 m), pression, fronts → élimine les journées/massifs.
2. **Méso** (AROME 1,3 km, ICON-D2) : vent par niveau sur la zone, nébulosité, précipitations, CAPE → choisit l'orientation et l'heure.
3. **Émagramme** au point du déco : plafond, base, inversion, humidité → type de vol et plafond utile.
4. **Balises** : valident/corrigent le modèle. Règle d'or : *si la balise du sommet contredit le modèle en direction de plus de 45° ou en force de plus de 10 km/h, on fait confiance à la balise pour les 2 prochaines heures et on baisse la confiance pour la suite*.
5. **Fiche site FFVL** : consignes, interdictions, fermetures saisonnières → priment sur tout.

---

## 2. Seuils par niveau

> Les seuils s'appliquent **au créneau du vol** (de l'heure de déco à l'heure d'atterrissage estimée) et, pour l'altitude, **uniquement aux niveaux réellement atteints** (déco → plafond utile + 300 m).
> Zone « marginal » = entre **80 % et 100 %** du seuil. Au-delà du seuil = **no-go pour ce niveau** (le plan peut rester valide pour un niveau supérieur → c'est ainsi qu'on calcule la `difficulty` estimée du plan, cf. §9.4).

### 2.1 Tableau principal

| Critère | beginner (élève / brevet initial) | intermediate (brevet de pilote) | advanced (brevet confirmé) | expert (cross/compét.) |
|---|---|---|---|---|
| **Vent moyen max au déco** | 15 km/h (idéal 5-12) | 20 km/h | 25 km/h | 30 km/h |
| **Rafales max au déco** | 20 km/h | 25 km/h | 30 km/h | 35 km/h |
| **Écart rafale − moyenne max** | 8 km/h | 10 km/h | 12 km/h | 15 km/h |
| **Facteur de rafale max** (rafale/moyenne, si moyenne ≥ 15) — *caution seulement, jamais no-go* | 1,4 | 1,5 | 1,6 | 1,7 |
| **Vent de travers max** (écart angulaire) | 30° | 45° | 60° | 75° |
| ↳ composante de travers max (`v·sin(écart)`) | 6 km/h | 10 km/h | 13 km/h | 16 km/h |
| **Vent arrière** (écart > 90° : c'est la **vitesse totale** du vent qui est comparée au seuil ; tout vent arrière ≥ 5 km/h ⇒ au mieux marginal) | Interdit (seul vent nul < 5 km/h accepté) | Interdit (vent nul < 5 km/h seulement) | ≤ 5 km/h, déco pentu uniquement | ≤ 8 km/h, déco pentu uniquement |
| **Vent max à 1500 m** | 15 km/h | 20 km/h | 25 km/h | 30 km/h |
| **Vent max à 2000 m** | 20 km/h | 25 km/h | 30 km/h | 35 km/h |
| **Vent max à 3000 m** | 25 km/h (rarement atteint) | 30 km/h | 35 km/h | 40 km/h |
| **Vent max à l'atterro (brise incluse)** | 15 km/h, rafales 20 | 20 km/h, rafales 25 | 25 km/h, rafales 30 | 28 km/h, rafales 35 |
| **Vario thermique moyen max** (`thermal_strength_ms`) | 1,5 m/s | 2,5 m/s | 3,5 m/s | 5,0 m/s (au-delà : caution) |
| **Gradient de vent** déco → déco+1000 m (Δ vitesse) | ≤ 10 km/h | ≤ 15 km/h | ≤ 20 km/h | ≤ 25 km/h |
| **Rotation du vent** déco + 300 m → plafond utile (brise de pente exclue ; si les deux vents ≥ 10 km/h) | ≤ 45° | ≤ 60° | ≤ 90° | ≤ 120° |
| **Cisaillement local** (Δ vitesse sur 300 m, typiquement à l'inversion) | ≤ 8 km/h | ≤ 12 km/h | ≤ 15 km/h | ≤ 20 km/h |
| **Plafond utile mini au-dessus du déco — vol local thermique** | +700 m (et vario ≤ 1,5) | +600 m | +400 m | +300 m |
| **Plafond utile mini — cross** | — (pas de cross) | déco +1200 m ET relief max de la route +500 m | déco +1000 m ET relief max +400 m | déco +800 m ET relief max +300 m |
| **Coefficient finesse de calcul** `k` (finesse_calcul = polaire × k) | 0,65 (→ 5,5 pour 8,5) | 0,70 (→ 6,0) | 0,72 (→ 6,1) | 0,75 (→ 6,4) |
| **Marge d'arrivée au-dessus de l'atterro** (entrée dans l'approche ; bornée à 25 % du dénivelé déco→atterro) | 100 m | 100 m | 100 m | 80 m |
| **Distance max de cross raisonnable** | 0 (interdit) | 25 km (retour possible à un atterro connu) | 80 km | 250 km (illimité en distance libre plaine) |
| **Durée max de vol** | 45 min (élève : 15-30 min) | 2 h | 5 h | 9 h (fenêtre convective) |
| **Types de vol autorisés** | local (plouf, thermique doux), soaring doux (vent 15-20 sur site école) | local, soaring, petit cross | tous | tous |
| **Thermique : heure de décollage** | Hors pic : avant convection+1 h ou en restitution du soir | Jusqu'au pic si vario ≤ 2,5 | Libre | Libre |

### 2.2 Soaring dynamique (seuils spécifiques)

| Critère | beginner | intermediate | advanced | expert |
|---|---|---|---|---|
| Vent de face mini pour tenir | 15 km/h | 15 km/h | 15 km/h | 13 km/h |
| Vent de face max | 20 km/h | 22 km/h | 27 km/h | 30 km/h |
| Écart à la perpendiculaire de la crête | ≤ 20° | ≤ 30° | ≤ 40° | ≤ 45° |
| Rafales max | 22 km/h | 26 km/h | 32 km/h | 35 km/h |
| Hauteur de relief mini / pente | 50 m / pente ≥ 30° | 50 m | 30 m | 30 m |

### 2.3 Finesse : formule à implémenter

```
V_air  = 37 km/h (vitesse bras hauts aile EN-B ; 39 pour EN-C/D si wing_glide_ratio >= 9.5)
finesse_calcul_air = wing_glide_ratio × k(niveau)
W_comp = composante du vent moyen sur la tranche déco→atterro, projetée sur la route (positive = vent arrière)
finesse_calcul_sol = finesse_calcul_air × (V_air + W_comp) / V_air      # si ≤ 0 : atterro inaccessible
hauteur_dispo = altitude_point − (alt_atterro + marge_arrivée(niveau))
required_ratio = distance_horizontale_m / hauteur_dispo
margin_ok = required_ratio ≤ finesse_calcul_sol  ET  le profil de terrain ne coupe pas la ligne de plané (dégagement ≥ 50 m)
```
- Exemple : polaire 8,5, intermediate → 6,0 ; vent de face 15 km/h → 6,0 × 22/37 = **3,6**. C'est réaliste : face à une brise de 15 km/h, on « ne va nulle part ».
- Contrôle : Forclaz → Doussard (3,4 km, 800 m de dénivelé, marge 100 m) demande 4,9 → passe à tous les niveaux par vent calme, ce qui est conforme à la réalité (plouf d'école).
- Sous-score finesse sur `r = required / available` : r ≤ 0,75 → 100 ; 0,90 → 60 ; 0,95 → 40 ; 1,0 → 0. `GLIDE_MARGIN` caution si r > 0,90, danger si r > 1.
- **Soaring avec top landing** (alt. atterro ≥ alt. déco − 50 m) : pas de contrôle de finesse (`required_ratio = 0`, `margin_ok = true`) ; briefing : « en cas de baisse du vent, posez-vous en bas de la pente côté au vent ».
- Ajouter **−10 %** sur la finesse de calcul si la ligne de plané passe sous le vent d'un relief ou dans une vallée en brise descendante.

---

## 3. Critères no-go absolus (tous niveaux)

| # | Critère | Règle chiffrée (no-go) | Marginal (caution) |
|---|---|---|---|
| 1 | **Pluie** | `precipitation_mm_h ≥ 0,2` sur le créneau ±1 h au déco OU sur la route ; ou pluie ≥ 1 mm dans les 3 h précédant le déco (aile mouillée → risque de parachutale, sol froid) | 0,05-0,2 mm/h ; averses possibles dans la zone |
| 2 | **Orage** | Sur **[déco, atterrissage + 1 h]** : `CAPE ≥ 800 J/kg ET LI ≤ −2`, ou `CAPE ≥ 1500` quel que soit LI ; sur **[déco, atterrissage + 2 h]** : précipitations convectives prévues < 30 km | `CAPE 300-800 ET LI ≤ 0` dans la fenêtre → marginal, fin de créneau = surdév − 1 h |
| 3 | **Surdéveloppement** | `overdevelopment_risk = "high"` ET créneau du vol après l'heure de surdév estimée | Risque du **jour** `high` → tout plan au mieux marginal (≤ 90 min, pas de cross sauf expert) ; `moderate` → marginal si l'heure de surdév tombe dans [déco, atterrissage + 2 h] ; fin du créneau = surdév − 1 h |
| 4 | **Foehn** | Vent ≥ 40 km/h à 700 hPa (~3000 m) perpendiculaire à la crête principale (Alpes du Nord : secteur S-SW ; Alpes du Sud / Briançonnais : N-NW) ; ou Δ pression ≥ 4 hPa entre versants (ex. Turin−Genève) ; ou lenticulaires / mur de foehn | Vent 25-40 km/h à 700 hPa dans ces secteurs ; air anormalement sec et chaud en vallée sous le vent (T +4 °C vs prévision, HR < 40 %) |
| 5 | **Vent régional** (mistral, tramontane, bise) | Mistral/bise ≥ 30 km/h au sol en vallée du Rhône / bassin genevois → no-go dans la zone d'influence | 20-30 km/h |
| 6 | **Base des nuages / visibilité** | `cloud_base_m < alt_déco + 200` ; nuages bas ≥ 80 % avec base < déco + 300 ; brouillard/stratus sur l'atterro ; visibilité < 5 km ; `T − Td < 1,5 °C` au déco | base < déco + 500 (pas de thermique exploitable) |
| 7 | **Vent fort en altitude** | Vent ≥ 45 km/h à un niveau atteint par le vol (déco → plafond utile + 300 m) ; ou ≥ 50 km/h à 3000 m en montagne même si le plafond est plus bas (turbulence descend) | 35-45 km/h |
| 8 | **Vent météo opposé (dévent)** | Vent au niveau des crêtes ≥ 15 km/h venant d'un secteur à plus de 120° de l'axe du déco (le déco est sous le vent) — **même si la balise du déco indique une brise favorable** | 10-15 km/h opposé ; vent météo de travers ≥ 20 km/h |
| 9 | **Vent au déco hors limites** | Vent moyen > 30 km/h ou rafales > 35 km/h (tous niveaux) ; écart rafale-moyenne > 15 km/h | cf. tableau §2 par niveau |
| 10 | **Atterrissage** | Vent à l'atterro > 28 km/h ou rafales > 35 km/h à l'heure d'arrivée ; aucun atterro accessible avec la finesse de calcul | brise > seuil du niveau − 20 % |
| 11 | **Jour aéronautique** | Atterrissage estimé après le coucher du soleil (le vol libre se pratique de jour) | atterrissage entre coucher − 30 min et coucher → marginal (`SUNSET`) |
| 12 | **Réglementaire** | Site `status = "closed"` ; route traversant un espace aérien interdit (P, R/ZRT actif, classe A/C/D sans clairance, CTR/TMA sous plancher) ; cœur de parc national / réserve avec survol interdit ; zone de quiétude rapaces en période active | espace aérien à moins de 1 km latéral / 100 m vertical de la route ; site `restricted` |
| 13 | **Front / dégradation** | Pression en baisse ≥ 3 hPa / 3 h ; arrivée de précipitations < 2 h après la fin du vol | voile d'altostratus qui épaissit (couverture moyenne/haute ≥ 80 % → thermiques coupés) |
| 14 | **Neige / gel** | Déco enneigé non signalé praticable ; T < −10 °C ressenti au plafond pour beginner | isotherme 0 °C < plafond (onglée, givre sur instruments) |

> Un seul critère no-go suffit : **pas de compensation par le score** (cf. §9).

---

## 4. Aérologie — règles simples exploitables par l'algorithme

### 4.1 Fenêtre thermique selon la saison (Alpes du Nord, face S, ciel clair, sol sec)

| Mois | Début (h légale) | Pic | Fin (h légale) | Vario moyen typique | Plafond typique Alpes N (AMSL) | Commentaire |
|---|---|---|---|---|---|---|
| Déc-Janv | 12h00 | 13h30 | 15h00 | 0,5-1,5 | 1500-2200 | Inversions de vallée, mer de nuages ; surtout plouf/soaring |
| Févr | 12h00 | 14h00 | 15h30 | 0,5-2 | 1800-2500 | |
| Mars-Avr | 11h00 | 14h00 | 17h00 | 2-4 | 2500-3200 | Air froid en altitude : thermiques forts, secs, turbulents ; vent d'altitude fréquent |
| Mai-Juin | 10h30 | 14h30 | 18h30 | 2-4 | 3000-3800 | Saison cross ; surdév fréquent |
| Juil-Août | 11h00 | 15h00 | 18h30 | 2-4 | 3000-4200 | Orages après 15h si instable ; brises de vallée fortes |
| Sept | 11h30 | 14h30 | 17h30 | 1,5-3 | 2500-3200 | Conditions plus douces |
| Oct | 12h00 | 14h00 | 16h30 | 1-2 | 2000-2800 | Heure d'été jusqu'au dernier dimanche d'octobre |
| Nov | 12h30 | 13h30 | 15h00 | 0,5-1,5 | 1500-2200 | |

- **Alpes du Sud** (Laragne, St-André, Serre-Ponçon) : début −30 min, plafond +300 à +500 m, vario +0,5 m/s.
- Ces valeurs sont un **fallback** : si le modèle fournit flux solaire et profil, préférer `convection_start` = première heure où `boundary_layer_height_agl_m ≥ 500` ET `wstar_ms ≥ 1,2` au point du déco ; `convection_end` = dernière heure où `wstar_ms ≥ 1,0`.

### 4.2 Décalage selon l'orientation de la face (en heure solaire, relatif à une face S)

| Face | Décalage début | Exposition max | Fin des thermiques de pente | Remarque |
|---|---|---|---|---|
| E | −1h30 | 8h-10h solaire | ~12h solaire (passe à l'ombre ~13-14h → brise descendante possible) | Vols du matin |
| SE | −0h45 | 9h-11h | ~14h | Excellente face de départ de cross |
| S | 0 | 11h-13h | ~16h | |
| SW | +1h00 | 13h-15h | ~17h30 | |
| W | +2h00 | 15h-17h | coucher − 1h ; **restitution** ensuite | Vols de l'après-midi/du soir |
| NW / N / NE | thermique « de convection générale » seulement, pas avant le pic (≈ +3 h) | — | — | Utiles en dynamique ou par vent météo de N |

Règle de déclenchement : **thermique exploitable sur une face ≈ 1h30-2h après que le soleil la frappe avec une incidence > 30°** (2h30 au printemps/automne, sol humide ou enneigé +1 h).

### 4.3 Brises

| Brise | Démarrage | Pic | Arrêt / bascule | Force typique |
|---|---|---|---|---|
| **Brise de pente montante** | ~1 h après ensoleillement de la face | 11h-15h solaire | dès que la face passe à l'ombre | 5-15 km/h |
| **Brise de vallée montante** (aval → amont) | 10h-11h légale (été) | 14h-17h légale | 1 h avant coucher → calme 30 min → bascule | Petite vallée 5-15 ; **grandes vallées alpines 15-25, pointes 30-35** |
| **Brise descendante** (pente puis vallée, amont → aval) | dès l'ombre / après coucher | nuit, matin tôt | 1-2 h après lever du soleil | 5-15 km/h (vallées encaissées : 20) |
| **Brise de lac** (Annecy, Bourget, Léman, Serre-Ponçon) | 11h-12h | 14h-17h | 18h-19h | 10-20 km/h, peut contrer le vent météo faible |
| **Brise de mer** (Provence, jusqu'à 60-80 km dans les terres) | 11h | 15h-16h | 19h | 15-25 km/h, ligne de convergence nette |

**Grandes vallées où la brise forcit fortement l'après-midi (×1,3 sur AROME 10 m entre 13h et 17h légale)** : Grésivaudan (St-Hilaire → atterro Lumbin), Arve (Chamonix/Passy/Sallanches), Maurienne, Tarentaise, Durance, Ubaye, Romanche, vallée du Rhône valaisanne (30-40 km/h), Bout du lac d'Annecy (Doussard : brise de N 15-25 km/h l'après-midi).

Règles algorithme :
- `vent_atterro(h) = max(vent_modèle_10m(h), brise_vallée(h, taille_vallée))`, direction = axe de vallée vers l'amont entre convection_start+1h et coucher−1h. Sans données d'axe de vallée : `vent_modèle_10m × 1,3` entre 13h et 17h légale si l'atterro est en fond de grande vallée (altitude < 800 m entourée de relief > 2000 m dans un rayon de 10 km).
- **Bascule** : un déco orienté E devient sous le vent de la brise de pente vers 13-14h solaire → interdire les décos E après 12h30 solaire sauf vent météo d'E ≥ 10 km/h.
- Brise montante + vent météo opposé ≥ 10 km/h → **ligne de convergence** (bonne pour le cross experts) mais **cisaillement et turbulence** près du relief → caution pour beginner/intermediate.

### 4.4 Restitution du soir

- Créneau : de **coucher − 1h30 à coucher**, faces W/SW, forêts, fonds de vallée ayant chauffé.
- Ascendances 0,3-1 m/s, larges et laminaires, plafond bas (déco + 200 à 500 m).
- **Idéal beginner et `thermals = "avoid"`** (air doux, quasi pas de turbulence) ; à proposer en priorité pour les durées 20-45 min.

### 4.5 Venturi, rotors, relief

- **Venturi aux cols et brèches** : vent au col = vent au même niveau × **1,5** (× 1,3 pour un col large). Interdire la traversée d'un col avec un vent de face > 15 km/h au niveau du col pour beginner/intermediate, > 20 km/h pour advanced/expert.
- **Rotor sous le vent** (vent au niveau de la crête ≥ 15 km/h) : zone dangereuse en aval sur **5 × hauteur du relief** (vent 15-25 km/h) à **10 ×** (vent > 25 km/h ou air stable), verticalement jusqu'à **crête + 50 % de la hauteur du relief**. Aucun segment de route ni déco ni atterro dans cette zone.
- **Dévent** : un déco dont la crête est au vent d'un vent météo ≥ 15 km/h est no-go (cf. §3 #8). Le calme au déco n'est pas une bonne nouvelle quand le vent souffle à la crête.
- **Effet d'accélération en crête** : vent au sommet ≈ vent libre × 1,2-1,4.

### 4.6 Surdéveloppement (été)

- Signaux : cumulus dès 10h légale ; base basse le matin (< 2000 m AMSL en été) ; `CAPE > 300` et `LI < 0` ; HR 700-500 hPa > 60 % ; castellanus/altocumulus le matin (instabilité d'altitude).
- **Heure estimée du surdéveloppement ≈ heure du premier cumulus + 3 à 4 h** (souvent 14h-16h légale).
- `overdevelopment_risk` :
  - `low` : CAPE < 300 ou LI > 2 ;
  - `moderate` : CAPE 300-800 et LI 0..2, ou HR 700 hPa > 70 % avec cumulus ;
  - `high` : CAPE > 800 et LI < 0, ou base des cumulus < plafond sec − 1000 m dès midi.
- Effet sur le plan : `moderate` → fin du créneau = heure surdév − 1 h ; `high` → vols du matin seulement, durée max 1h30, aucun cross (sauf expert, avec retour planifié avant 13h solaire).

### 4.7 Inversions

- **Inversion matinale de vallée** : thermiques bloqués tant que T sol < T de déclenchement (lue sur l'émagramme). Plouf laminaire possible, aucun thermique.
- **Inversion de subsidence** (anticyclone) : plafond bas et net, thermiques étroits, turbulence au passage ; si l'inversion est < déco + 300 m → pas de vol thermique, seulement plouf/soaring.
- **Hiver** : mer de nuages → déco au-dessus en plein soleil mais atterro dans le stratus = **no-go** (§3 #6).
- Calcul plafond : intersection de l'adiabatique sèche partant de `T_max_sol + 1 °C` avec le profil ; base cumulus ≈ `alt_sol + 125 × (T − Td)` ; plafond utile = min des deux − 300 m si cumulus.

### 4.8 Seuils de qualité thermique (pour scorer)

| Vario moyen | Qualité | Usage |
|---|---|---|
| < 0,8 m/s | non exploitable | plouf |
| 0,8-1,5 | faible | local doux, beginner |
| 1,5-2,5 | bon | local, petit cross |
| 2,5-3,5 | fort | cross |
| > 3,5 | très fort / turbulent | experts |

---

## 5. Typologie des vols et construction de la route

Mapping contrat : `local` (+ `thermal_usage = "none"` pour le plouf), `ridge_soaring`, `cross_country`.

### 5.1 Plouf / descente (`local`, `thermal_usage: none`)
- Conditions : vent déco dans les limites, aucun thermique requis. Meilleurs créneaux : matin (avant convection_start) ou restitution du soir.
- Route : déco → éventuellement 1 point au-dessus d'une zone dégagée près de l'atterro pour perdre l'altitude → **zone d'approche (PTU) côté sous le vent de l'atterro** → atterro face au vent.
- Waypoints : `takeoff`, (`turnpoint` « zone de perte d'altitude » à 300-500 m de l'atterro, ≥ 200 m sol), `landing`.

### 5.2 Local thermique (`local`, `thermal_usage: optional|essential`)
- Rester **en permanence dans le cône de finesse de l'atterro principal** (ou d'un atterro de secours explicite).
- Route : boucle de 3 à 10 km sur les déclencheurs proches du déco : éperons, sommets, ruptures de pente, lisières, barres rocheuses **sur les faces au soleil à l'heure considérée** (§4.2) et du côté au vent du relief ; hotspots KK7 de probabilité élevée.
- Type de waypoint : `thermal_trigger` avec `radius_m = 400`.

### 5.3 Soaring dynamique (`ridge_soaring`)
- Conditions §2.2 ; vent régulier (écart rafale-moyenne ≤ 8 km/h), plafond thermique non requis.
- Route : aller-retours parallèles à la crête, **au vent** de la crête, longueur de la portion soarable (≥ 500 m), demi-tours toujours **face à la pente → virage côté vallée** (on tourne en s'éloignant du relief).
- Atterro : top landing si le site le permet, sinon atterro en contrebas (vérifier finesse vent de face) ; sur dune/falaise : plage.

### 5.4 Cross (`cross_country`)

| Format | Quand | Règles de construction |
|---|---|---|
| **Aller-retour** | Chaîne de montagne orientée ~ dans l'axe du vent ; intermediate/advanced | **Aller face au vent d'abord** (on est frais, haut, et le retour est poussé) ; point de retour à mi-durée. |
| **Triangle FAI** | Advanced/expert, vent ≤ 20 km/h en altitude | Plus petit côté ≥ 28 % du total. Premier côté **face au vent / contre la dérive** ; ordre des points = ordre d'ensoleillement (faces E-SE le matin → S → W l'après-midi). |
| **Triangle plat** | Idem, relief non compatible FAI | Moins contraint ; mêmes règles d'ensoleillement. |
| **Distance libre sous le vent** | Expert, plaine ou sortie de massif, vent 15-30 km/h | Route sous le vent ; vérifier espaces aériens et routes de retour (train/route). |

**Placement des points tournants** :
- Sur des crêtes/sommets ensoleillés à l'heure de passage estimée (ETA), jamais en fond de vallée.
- Transitions : traverser les vallées **au plus étroit**, perpendiculairement, depuis le plafond utile ; l'arrivée sur la face suivante doit se faire à **≥ terrain + 500 m (intermediate), + 400 m (advanced), + 300 m (expert)** avec la finesse de calcul sol.
- Distance max entre deux déclencheurs consécutifs : `(plafond_utile − terrain_arrivée − marge) × finesse_calcul_sol`.
- Préférer les « skyways » (KK7 / densité XContest) quand disponibles.
- Éviter : faces sous le vent, faces à l'ombre, cols en venturi, fonds de vallée en brise forte, espaces aériens (marge 1 km / 100 m), parcs nationaux/réserves.
- `radius_m` : 400 m pour un point tournant, 200-400 m (cylindre) pour le but/atterro.

**Règle « toujours un atterro dans le cône de finesse »** (à vérifier tous les 500 m de route) :
```
alt_securite(p) = min sur atterros a [ alt_a + marge_arrivée + dist(p,a) / finesse_calcul_sol(p→a) ]
contrainte : alt_securite(p) ≤ plafond_utile(p) − 300 m
```
- Si violée → raccourcir la route ou insérer un atterro de secours **identifié** (officiel FFVL/ParaglidingEarth uniquement, jamais « un champ quelconque »).
- Publier `alt_securite` par segment dans le briefing : c'est le **point de décision** (« sous 2100 m à la Tournette, retour vers Doussard »).

### 5.5 Vitesse de croisière réaliste (`V_xc`, km/h, air calme, aile EN-B ; ×1,15 en EN-C/D)

| Vario moyen | intermediate | advanced | expert |
|---|---|---|---|
| 1 m/s | 8 | 10 | 12 |
| 2 m/s | 14 | 17 | 20 |
| 3 m/s | 19 | 23 | 27 |
| 4 m/s | — (hors seuil) | 27 | 32 |
| 5 m/s | — | — | 36 |

Effet du vent (W = vent moyen sur la tranche de vol, projeté sur l'axe des branches) :
- Circuit fermé (aller-retour, triangle) : `V_eff = V_xc − W² / V_xc` (pour un triangle prendre `W × 0,7`). Ex. V_xc 25, W 15 → 16 km/h.
- Distance sous le vent : `V_eff = V_xc + 0,8 × W`.
- Si `V_eff < 8 km/h` → le cross n'est pas proposé.

---

## 6. Estimation des durées

| Type | Formule | Ordre de grandeur |
|---|---|---|
| **Plouf** | `(alt_déco − alt_atterro) / (taux_chute × 60) + 3 min` avec taux de chute 1,2 m/s (air calme), 1,0 m/s en restitution, 1,5 m/s en air descendant | 800 m de dénivelé → 14 min |
| **Plouf en restitution** | durée plouf × 1,5 à 2 | 20-30 min |
| **Soaring** | min(durée demandée, durée pendant laquelle le vent reste dans les limites §2.2), plafonné à 90 min (beginner 30 min) | 30-90 min |
| **Local thermique** | min(durée demandée, `convection_end − heure_déco` + durée de plouf, fin surdév − 1 h) ; beginner ≤ 45 min | 30 min - 2 h |
| **Cross** | `t_montée_initiale + distance / V_eff + t_glide_final` ; `t_montée_initiale = (plafond_utile − alt_déco) / vario` (≥ 10 min) ; `t_glide_final ≈ 10 min` | 50 km à 20 km/h → ~3 h |

Contraintes :
- Heure d'atterrissage estimée ≤ `min(convection_end + 30 min (glide final), coucher du soleil − 30 min, heure surdév)`.
- `est_duration_min` = durée en l'air (sans la préparation au déco, 15-30 min, à signaler dans le briefing).
- Si la durée demandée par l'utilisateur excède ce que la fenêtre permet : **ne pas étirer** le vol ; proposer la durée réaliste et l'indiquer dans `summary`.
- Hors thermiques, aucun vol ne doit dépasser la durée de plouf/soaring : un plouf de 1h30 n'existe pas.

---

## 7. Contenu d'un bon plan de vol / briefing

### 7.1 Ordre du briefing (`briefing: string[]`) — ce que dit un moniteur

1. **Verdict** : go / marginal / no-go, niveau requis, confiance (ex. « GO pour brevet de pilote — confiance 75 % »).
2. **Créneau** : décoller entre hh:mm et hh:mm, être posé avant hh:mm (et pourquoi : brise, surdév, coucher à hh:mm).
3. **Situation générale** : flux, tendance (« anticyclone, flux faible de NW, stable demain »).
4. **Vent** : au déco (moyen/rafales/direction à l'heure de déco), à 1500/2000/3000 m, à l'atterro à l'heure d'arrivée (brise), évolution sur le créneau.
5. **Aérologie** : début/pic/fin des thermiques, vario moyen attendu, plafond utile, base des cumulus, inversion, risque de surdéveloppement.
6. **Décollage** : orientation, technique conseillée (face voile si vent ≥ 12 km/h, dos voile sinon), pièges du site (consignes FFVL).
7. **Itinéraire** : points, ETA, altitude de sécurité par segment, **points de décision** (« si pas 1800 m à X à 14h, retour »).
8. **Atterrissage** : principal + secours, sens d'approche et côté de la PTU, obstacles (lignes HT, arbres, routes), brise attendue, zones interdites.
9. **Espaces aériens et zones sensibles** : noms, plancher/plafond, distance mini à la route ; parcs/réserves ; zones rapaces.
10. **Risques** spécifiques du jour (rotor sous X, venturi au col Y, convergence, dévent après 14h…).
11. **Logistique & sécurité** : navette/retour, fréquence radio, numéro d'urgence, heure de coucher du soleil.

### 7.2 Checklist pré-vol (`checklist: string[]`)

1. Météo revue < 1 h (balises déco + atterro), plan B connu.
2. Espace aérien et NOTAM / activations (R, ZRT, AZBA) vérifiés pour le jour.
3. Parachute de secours : poignée accessible et verrouillée, aiguilles en place, date de repliage < 12 mois.
4. Sellette : cuissardes, ventrale (réglage), **mousquetons verrouillés**, accélérateur connecté et libre.
5. Casque jugulaire fermée ; gants, lunettes, vêtements adaptés au plafond (−0,65 °C / 100 m).
6. Voile : visite pré-vol, suspentes démêlées, élévateurs non vrillés, freins libres, voile en arc, caissons ouverts.
7. Instruments : vario/GPS chargés, tâche XCTrack/GPX chargée, live tracking activé, téléphone chargé.
8. Radio allumée sur la fréquence du jour, test de réception.
9. Eau, nourriture (cross), kit de secours / couverture de survie (montagne).
10. Plan de vol communiqué à un proche ou au chauffeur (site, route, heure de retour).
11. **Contrôle final au déco (PRÉVOL)** : attaches, casque, suspentes, voile, **vent et espace devant libres**.

### 7.3 Consignes de sécurité et règles de priorité (à afficher)

- Croisement face à face : **chacun s'écarte vers la droite**.
- Le long d'une pente : **priorité au pilote qui a la pente à sa droite** ; dépassement par le côté opposé au relief, jamais entre un pilote et la pente.
- En thermique : **le premier entré donne le sens de rotation** ; on s'intègre dans le même sens.
- Convergence : priorité à droite. Pilote le plus bas / en approche finale prioritaire.
- Pas de survol / sous-vol rapproché d'un autre pilote (angles morts). Distance mini 50 m.
- Aéronefs motorisés, planeurs, hélicoptères (secours, DZ) : anticiper, dégager.
- Ne jamais pénétrer dans un nuage ; se tenir à 300 m sous la base et à 1,5 km horizontalement des nuages au-dessus de 900 m AMSL (VMC classe E/G).

### 7.4 Espaces aériens et zones sensibles

| Élément | Règle pour l'algorithme |
|---|---|
| Classe A | Interdit |
| Classes C, D (CTR, TMA, CTA) | Interdit sans clairance → **interdit** en pratique ; respecter plancher (souvent exprimé en FL ou ft AMSL) |
| Classe E | Autorisé en VMC (France) |
| Classe G | Libre (VMC) |
| **Plafond légal France** | En règle générale **FL115** (≈ 3505 m en atmosphère standard ; `alt_m ≈ 3505 + (QNH − 1013) × 8,3`) sauf espace plus bas. **Limiter `max_altitude_m` = min(FL115 − 100 m, plancher de l'espace le plus bas au-dessus de la route − 100 m)**. Plafonds alpins > 3500 m fréquents en été : c'est un vrai problème. |
| P (interdite) | Interdit |
| R, ZRT, D | Interdit si actif ; activation souvent par NOTAM/SUP AIP → afficher « à vérifier » si statut inconnu (caution) |
| AZBA (réseau très basse altitude défense) | Caution les jours ouvrés, consulter le planning |
| SIV | Information seulement |
| Unités | Planchers « SFC », « ASFC » (sol), « AMSL », « FL » : **convertir systématiquement en AMSL avec le terrain** |
| **Cœurs de parcs nationaux** (Vanoise, Écrins, Mercantour…) | Décollage/atterrissage interdits ; survol réglementé (hauteur mini 1000 m/sol selon le décret du parc) → traiter comme **zone à éviter** (no-go route sous 1000 m/sol) sauf consigne contraire de la fiche site FFVL |
| Réserves naturelles | Selon arrêté (souvent survol < 300 m/sol interdit) → éviter |
| Zones de quiétude / ZSM rapaces (gypaète, aigle royal, faucon pèlerin) | Évitement saisonnier (souvent déc → juillet), distance typique 500-1000 m ; source : **Biodiv'Sports** (LPO/FFVL) et fiches site |
| Fermetures saisonnières de sites | Statut fiche FFVL prioritaire |

### 7.5 Urgence

- **112** (bascule vers le PGHM / secours en montagne). Donner : position GPS (afficher les coordonnées du déco/atterro et de la route dans le plan), altitude, état du blessé, météo sur place (vent, plafond pour l'hélico).
- Fréquence radio vol libre FFVL : **143,9875 MHz**.
- En cas d'arbre / de falaise : ne pas bouger, se longer, appeler 112.
- Rappeler : prévenir le chauffeur / la base si atterrissage hors atterro prévu (évite un déclenchement inutile des secours).

---

## 8. Données : quoi utiliser, comment pondérer, quoi afficher

### 8.1 Utilité par source (priorité décroissante)

| Priorité | Source | Données les plus utiles | Précautions |
|---|---|---|---|
| 1 | **Fiches sites FFVL** | Orientations, altitude déco/atterro, consignes, interdictions, statut, difficulté, atterros associés | Prime sur toute autre source pour le réglementaire |
| 2 | **Balises FFVL / Pioupiou / OpenWindMap** | Vent moyen/rafale/direction au déco et à l'atterro | Utiliser moyenne/max sur 10-20 min ; `stale` > 30 min = ignorée ; certaines Pioupiou sont mal exposées (abritées ou en sommet) → comparer aux voisines ; balise de sommet ≠ déco à mi-pente |
| 3 | **AROME France HD 1,3 km** | Vent 10 m et par niveau, nébulosité basse, précip, CAPE, couche limite — **meilleur modèle < 42 h** pour brises et relief | Relief lissé : interpoler au niveau du déco, pas au sol du modèle |
| 4 | **ICON-D2 2,2 km** | Second avis haute résolution (< 48 h) | Sert à mesurer la dispersion |
| 5 | **ECMWF IFS** | Synoptique, 24-48 h, foehn/fronts | Trop lissé pour le vent au déco |
| 6 | **Émagrammes (Météo-Parapente / RASP / calcul interne)** | Plafond, base, inversions, W*, humidité | |
| 7 | **OpenAIP** | Géométrie des espaces aériens | Activations absentes → toujours « vérifier NOTAM/SUP AIP » |
| 8 | **KK7 thermal hotspots / skyways** | Placement des `thermal_trigger`, couloirs de cross | Probabilité historique, pas la météo du jour |
| 9 | **XContest** (traces historiques) | Routes réellement volées par site × direction de vent ; distances réalistes | Biais jours exceptionnels → prendre la médiane, pas le record |
| 10 | **SpotAir / ParaglidingEarth** | Complément de sites (hors FFVL, étranger) | Données moins fiables : `difficulty` souvent absente → considérer le site au niveau `intermediate` par défaut |
| 11 | **Biodiv'Sports** | Zones sensibles faune | À intégrer comme couche « restrictions » |

### 8.2 Pondération prévision vs balises selon l'horizon

| Horizon | Poids balises (correction du vent au déco/atterro) | Poids modèles | Modèles | Confiance de base |
|---|---|---|---|---|
| 15 min | 0,85 (persistance + tendance 60 min, §12) | 0,15 | AROME | 0,92 |
| 30 min | 0,7 (persistance + tendance 60 min) | 0,3 | AROME | 0,90 |
| 1 h | 0,5 | 0,5 | AROME (+ICON-D2) | 0,85 |
| 2 h | 0,3 | 0,7 | AROME + ICON-D2 | 0,80 |
| 8 h | 0,1 (correction de biais du matin uniquement) | 0,9 | AROME + ICON-D2 | 0,70 |
| 12 h | 0 | 1 | AROME + ICON-D2 + ECMWF | 0,65 |
| 24 h | 0 | 1 | AROME + ICON-D2 + ECMWF | 0,55 |
| 48 h | 0 | 1 | ECMWF (+ AROME si dispo) | 0,40 |

Règles :
- **Ne corriger par les balises que si le régime diurne est le même** : une balise à 9h (brise descendante) ne corrige pas une prévision à 11h (brise montante). Corriger la composante synoptique (vent de crête) plutôt que le vent de fond de vallée.
- Balise utilisable si : distance < 5 km du site ET |Δalt| < 300 m (sinon poids divisé par 2), fraîcheur < 30 min. Détail du rattachement au déco **et à l'atterro** (heure d'arrivée), altitude inconnue, balise périmée : §12.1.
- Tendance : si la moyenne 10 min a augmenté de > 5 km/h sur la dernière heure → extrapoler pour 15 min-1 h et ajouter un risque « vent qui forcit » (seuils, rotation, rafale max et effet par horizon : §12.2).
- **Confiance** = base(horizon) × facteur_dispersion × facteur_balises :
  - dispersion inter-modèles du vent au déco : σ ≤ 3 km/h → ×1 ; σ = 10 km/h → ×0,6 ; direction σ > 45° → ×0,7 ;
  - balise fraîche cohérente (Δ < 5 km/h, < 30°) → ×1,1 (max 0,95) ; contradictoire → ×0,8 ;
  - mode mock/synthétique → confiance plafonnée à 0,3 et warning explicite.
- Si **une** source (balise ou modèle) indique un no-go et la confiance < 0,6 → `marginal` au minimum, jamais `go`.

### 8.3 Indicateurs à afficher sur la carte (par priorité)

1. **Vent au sol + balises** : flèches colorées selon les seuils du niveau choisi (vert / orange = 80-100 % / rouge), rafales en étiquette.
2. **Vent à l'altitude du vol** (sélecteur 1500 / 2000 / 3000 m).
3. **Hauteur utile au-dessus du relief** (plafond utile − terrain) : la vraie carte « où on peut voler ».
4. **Base des cumulus + couverture nuageuse**.
5. **Vario / W\***.
6. **CAPE + précipitations** (risque orageux).
7. **Espaces aériens + zones sensibles** (parcs, réserves, Biodiv'Sports) avec plancher/plafond.
8. **Hotspots KK7** (couche optionnelle).
9. Sur la route : cône de finesse / altitude de sécurité par segment, atterros de secours.

---

## 9. Score et verdict

### 9.1 Principe : filtre d'abord, score ensuite (non compensatoire)

1. Appliquer les no-go absolus (§3) et les seuils du niveau (§2) → `no_go` immédiat, `rejected` avec raisons lisibles.
2. Calculer chaque critère sur 0-100.
3. `score = Σ poids × sous-score` **puis** `score = min(score, 40 + min_sous_score_sécurité)` pour qu'un critère de sécurité faible ne soit jamais masqué par de bons critères de confort.

### 9.2 Critères et poids

| Critère (`criterion`) | Poids | 100 = | 0 = |
|---|---|---|---|
| `takeoff_wind` (moyen, rafales, écart, travers) | 25 | vent de face 5-15 km/h, écart rafale ≤ 5 | au seuil du niveau |
| `wind_aloft` (vent aux niveaux atteints, gradient, cisaillement) | 15 | < 50 % du seuil | au seuil |
| `landing` (vent/brise à l'heure d'arrivée, marge de finesse, atterros de secours) | 15 | brise < 50 % du seuil, `required ≤ 0,75 × available` | au seuil / marge nulle (courbe finesse §2.3) |
| `thermal_match` (vario, plafond utile, créneau vs préférence) | 15 | cf. 9.3 | |
| `duration_match` | 10 | durée estimée dans [min, max] demandés | écart > 50 % |
| `convective_stability` (CAPE/LI, surdév, nuages, fin de créneau) | 10 | CAPE < 100, risque low | au seuil no-go |
| `data_confidence` | 5 | confiance ≥ 0,9 | ≤ 0,3 |
| `site_fit` (difficulté du site vs niveau, statut, consignes) | 5 | site ≤ niveau, open | site au-dessus du niveau (→ no-go en réalité) |

Interpolation : sous-score linéaire de 100 (à 50 % du seuil ou dans la plage idéale) à 40 (à 80 % du seuil) puis à 0 (au seuil).
Vent nul au déco : sous-score `takeoff_wind` = 80 (décollage plus technique, faisable sur pente correcte).

### 9.3 `thermal_match` selon la préférence

| Préférence | Règle |
|---|---|
| `required` | Exclure si vario < 0,8 ou plafond utile < seuil local du niveau ou aucun recouvrement créneau/convection. Score max si vario dans [1,5 ; seuil niveau − 0,5]. |
| `allowed` | Score neutre 70 sans thermique ; bonus si thermiques doux ; pénalité si vario > 80 % du seuil. |
| `avoid` | Placer le créneau avant `convection_start` ou en restitution ; exclure si vario prévu > 1,5 m/s pendant le vol ; types préférés : plouf, soaring, restitution. |

### 9.4 Verdict et difficulté

- **go** : aucun no-go, score ≥ 65, tous les critères de sécurité (`takeoff_wind`, `wind_aloft`, `landing`, `convective_stability`) ≥ 40 (= valeur de la courbe à 80 % du seuil, cohérent avec la bande marginale), `confidence ≥ 0,75 × confiance de base de l'horizon` (c'est-à-dire dispersion × cohérence balises ≥ 0,75), et aucun Risk `caution` « bloquant » (`TAILWIND`, `SUNSET`, `OVERDEVELOPMENT`, `CROSSWIND`, `VALLEY_BREEZE` en bande 80-100 %, `SENSITIVE_AREA`, `LOW_CONFIDENCE`, `GLIDE_MARGIN` ; et pour le §12 : `WIND_INCREASING`, `WIND_SHIFT`, `FREE_TAKEOFF`, `UNOFFICIAL_LANDING`, `DETECTED_FIELD` — mais **pas** `NO_LANDING_BEACON`, non bloquant).
- **marginal** : aucun no-go, mais score 45-65, ou un critère de sécurité dans la zone 80-100 % du seuil, ou un Risk caution bloquant, ou une confiance insuffisante. **Toujours dire pourquoi** (risque `caution` correspondant).
- **Mode mock** : confiance affichée plafonnée à 0,3, mais le verdict utilise le ratio non plafonné ; Risk `MOCK_DATA` (caution, non bloquant) et warning explicite.
- **Durée** : on ne rejette jamais un site pour la durée seule ; `duration_match` pénalise et `summary` explique.
- **Créneau** : `window.start ∈ [cible − 30 min, cible + 3 h]`.
- **no_go** : un no-go absolu, un seuil du niveau dépassé, ou score < 45.
- **`difficulty` du plan** = max(difficulté du site, plus petit niveau dont tous les seuils §2 passent, niveau mini du type de vol : cross ≥ intermediate, distance libre ≥ expert, triangle FAI ≥ advanced). Si `difficulty` > niveau demandé → plan rejeté (raison : « conditions trop fortes pour ton niveau, OK pour brevet confirmé » ; code `SITE_LEVEL` si c'est le site lui-même).
- **Diversité** : dans les 5 premiers plans, au plus 2 par décollage, et au moins un plan d'orientation différente si disponible.

---

## 10. Pièges qu'un outil automatique ferait (et pas un pilote)

1. **Prendre le vent 10 m du modèle au point de grille comme vent au déco** : le relief du modèle est lissé (le « sol » AROME peut être 300 m sous le déco). Interpoler le vent à l'altitude réelle du déco à partir des niveaux de pression, et le vent à l'atterro au 10 m.
2. **Le faux calme** : vent nul au déco + vent ≥ 15 km/h opposé à la crête = **déco dans le dévent / rotor**, pas une belle journée calme.
3. **Lire une balise thermique en instantané** : un cycle peut donner 0 puis 25 km/h. Toujours moyenne/max sur 10-20 min ; une direction qui tourne de 180° en cycles = thermique, pas vent arrière.
4. **Confondre « vient de » et « va vers »**, ou degrés vs secteurs ; erreur classique sur les fiches site (orientations = d'où vient le vent favorable).
5. **Mélanger UTC, heure légale et heure solaire** : heure d'été jusqu'au 25/10/2026 ; règles aérologiques en heure solaire.
6. **Tracer une ligne droite qui traverse un relief** plus haut que l'altitude du pilote : vérifier le profil de terrain sur chaque segment et chaque ligne de plané vers l'atterro.
7. **Atterro « le plus proche à vol d'oiseau »** derrière une crête, de l'autre côté d'un col venturi, ou face à une brise de 25 km/h. Calculer la finesse sol avec le vent et le terrain.
8. **Inventer un atterrissage** dans un champ quelconque : en mode classique, seuls les atterros officiels/identifiés comptent ; un atterro communautaire ou un champ détecté n'est proposé qu'aux conditions du §12.7 (niveau, critères minimaux, marges renforcées, avertissement « Non officiel »).
9. **Router sur une face à l'ombre ou sous le vent**, ou un `thermal_trigger` au milieu d'un lac / fond de vallée en brise.
10. **Ignorer l'évolution sur la durée du vol** : vent correct à 11h mais 30 km/h de brise à l'atterro à 16h ; surdév à 15h pour un cross de 4 h parti à 12h.
11. **Ignorer la brise de vallée** (non vue par ECMWF, sous-estimée par AROME) → atterrissage dangereux l'après-midi pour un beginner.
12. **Espaces aériens en 2D** ou sans conversion FL/ASFC/AMSL ; oublier FL115 ; considérer une R/ZRT inactive par défaut.
13. **Oublier le réglementaire et l'environnement** : site fermé, nidification, cœur de parc, réserve, consignes FFVL (« décollage interdit après 16h », « atterro fermé quand le champ est fauché »…). La fiche site prime sur l'algorithme.
14. **Proposer un cross à un beginner**, un plouf de 2 h, un soaring dans 35 km/h, ou des thermiques de 4 m/s à un brevet initial.
15. **Le plafond au-dessus de la base** : on ne vole pas dans le nuage ; plafond utile = base − 300 m.
16. **Faire confiance à une seule balise mal implantée** (Pioupiou abritée en forêt, ou balise de sommet exposée) ; comparer aux voisines et au modèle.
17. **Ignorer l'accès** : horizon 30 min pour un déco à 1 h de route + 30 min de marche n'a pas de sens → afficher un avertissement ou exiger un temps d'accès.
18. **Coucher du soleil** : atterrissage + plié + retour de nuit ; finir ≥ 30 min avant le coucher.
19. **Classer 5 variantes du même site** en tête : diversifier (orientations et sites).
20. **Score qui compense** : 95 en thermiques ne rattrape jamais 20 en vent déco.
21. **Fausse précision** à 48 h : créneaux à la minute, plafond au mètre. Arrondir (heure, 100 m) et afficher la confiance.
22. **Vario « fort = bon »** : pour beginner/intermediate, au-delà du seuil c'est une pénalité, pas un bonus.
23. **Ne pas exposer le mode mock** : un plan calculé sur données synthétiques doit être marqué comme tel, en rouge, dans le plan et le briefing.

---

## 11. Valeurs proposées pour `rules.py` (à copier/adapter)

```yaml
levels: [beginner, intermediate, advanced, expert]
takeoff_wind_max_kmh:        {beginner: 15, intermediate: 20, advanced: 25, expert: 30}
takeoff_gust_max_kmh:        {beginner: 20, intermediate: 25, advanced: 30, expert: 35}
gust_spread_max_kmh:         {beginner: 8,  intermediate: 10, advanced: 12, expert: 15}
gust_factor_max:             {beginner: 1.4, intermediate: 1.5, advanced: 1.6, expert: 1.7}   # caution seulement, si moyenne >= 15
crosswind_angle_max_deg:     {beginner: 30, intermediate: 45, advanced: 60, expert: 75}
crosswind_component_max_kmh: {beginner: 6,  intermediate: 10, advanced: 13, expert: 16}
tailwind_max_kmh:            {beginner: 0,  intermediate: 0,  advanced: 5,  expert: 8}
calm_wind_kmh: 5
wind_aloft_max_kmh:
  1500: {beginner: 15, intermediate: 20, advanced: 25, expert: 30}
  2000: {beginner: 20, intermediate: 25, advanced: 30, expert: 35}
  3000: {beginner: 25, intermediate: 30, advanced: 35, expert: 40}
landing_wind_max_kmh:        {beginner: 15, intermediate: 20, advanced: 25, expert: 28}
landing_gust_max_kmh:        {beginner: 20, intermediate: 25, advanced: 30, expert: 35}
thermal_max_ms:              {beginner: 1.5, intermediate: 2.5, advanced: 3.5, expert: 5.0}
gradient_max_kmh_per_1000m:  {beginner: 10, intermediate: 15, advanced: 20, expert: 25}
veer_max_deg:                {beginner: 45, intermediate: 60, advanced: 90, expert: 120}
shear_max_kmh_per_300m:      {beginner: 8,  intermediate: 12, advanced: 15, expert: 20}
local_ceiling_min_above_takeoff_m: {beginner: 700, intermediate: 600, advanced: 400, expert: 300}
xc_ceiling_min_above_takeoff_m:    {beginner: null, intermediate: 1200, advanced: 1000, expert: 800}
xc_ceiling_min_above_relief_m:     {beginner: null, intermediate: 500, advanced: 400, expert: 300}
glide_k:                     {beginner: 0.65, intermediate: 0.70, advanced: 0.72, expert: 0.75}
landing_arrival_margin_m:    {beginner: 100, intermediate: 100, advanced: 100, expert: 80}   # bornée à 25 % du dénivelé
glide_subscore_curve:        {0.75: 100, 0.90: 60, 0.95: 40, 1.0: 0}                        # r = required / available
xc_max_distance_km:          {beginner: 0, intermediate: 25, advanced: 80, expert: 250}
max_duration_min:            {beginner: 45, intermediate: 120, advanced: 300, expert: 540}
transition_arrival_above_terrain_m: {intermediate: 500, advanced: 400, expert: 300}
ridge: {min_kmh: 15, max_kmh: {beginner: 20, intermediate: 22, advanced: 27, expert: 30}, max_angle_deg: {beginner: 20, intermediate: 30, advanced: 40, expert: 45}}
air_speed_trim_kmh: 37
sink_rate_ms: {calm: 1.2, evening: 1.0, sinking_air: 1.5}
nogo:
  precip_mm_h: 0.2
  precip_prev_3h_mm: 1.0
  cape_storm: {cape: 800, li: -2}
  cape_absolute: 1500
  cloud_base_min_above_takeoff_m: 200
  wind_any_level_kmh: 45
  wind_3000m_mountain_kmh: 50
  foehn_700hpa_kmh: 40
  foehn_dp_hpa: 4
  regional_wind_ground_kmh: 30
  lee_wind_at_crest_kmh: 15      # vent opposé (> 120° de l'axe du déco)
  takeoff_wind_abs_kmh: 30
  takeoff_gust_abs_kmh: 35
  landing_before_sunset_min: 0   # caution si < 30
  pressure_drop_hpa_3h: 3
cloud_clearance_vertical_m: 300
fl115_m_standard: 3505
venturi_factor_col: 1.5
rotor_lee_factor: {moderate: 5, strong: 10}  # × hauteur du relief
valley_breeze_afternoon_factor: 1.3
marginal_band: 0.8                           # 80-100 % du seuil
verdict: {go_min_score: 65, go_min_safety_subscore: 40, go_min_confidence_ratio: 0.75, nogo_max_score: 45}   # ratio = confidence / base(horizon)
weights: {takeoff_wind: 25, wind_aloft: 15, landing: 15, thermal_match: 15, duration_match: 10, convective_stability: 10, data_confidence: 5, site_fit: 5}
horizon_beacon_weight: {"15m": 0.85, "30m": 0.7, "1h": 0.5, "2h": 0.3, "8h": 0.1, "12h": 0, "24h": 0, "48h": 0}      # 15m : §12
horizon_base_confidence: {"15m": 0.92, "30m": 0.9, "1h": 0.85, "2h": 0.8, "8h": 0.7, "12h": 0.65, "24h": 0.55, "48h": 0.4}
xc_speed_kmh_by_vario:   # vario m/s -> km/h (aile EN-B ; ×1.15 si finesse ≥ 9.5)
  intermediate: {1: 8,  2: 14, 3: 19}
  advanced:     {1: 10, 2: 17, 3: 23, 4: 27}
  expert:       {1: 12, 2: 20, 3: 27, 4: 32, 5: 36}
turnpoint_radius_m: 400
goal_radius_m: 300
```

---

## 12. Balises atterro, horizon 15 min, décollage libre et atterros non officiels

> Ajout de la phase 2, sur deux demandes utilisateur : « je décolle dans 15-30 min » et « vol rando depuis un point quelconque ».
> Vocabulaire du contrat : `Horizon` `"15m"`, `Beacon.trend`, `StationReading`, `PlanRequest.mode = "custom_takeoff"`, `filters.landing_policy`, `LandingKind` = `official | community | field`, `LandingCandidate`.
> **Nouveaux codes Risk** : `NO_LANDING_BEACON`, `WIND_SHIFT`, `FREE_TAKEOFF`, `UNOFFICIAL_LANDING`, `DETECTED_FIELD`. Codes existants réutilisés : `WIND_INCREASING`, `BEACON_MISMATCH`, `STALE_BEACONS`, `TAKEOFF_WIND`, `TAKEOFF_GUSTS`, `CROSSWIND`, `TAILWIND`, `LANDING_WIND`, `GLIDE_MARGIN`.
> Toutes les cautions de cette section sont **bloquantes** : le plan est au mieux `marginal`. Une seule exception : `NO_LANDING_BEACON`, à ajouter aux cautions non bloquantes (avec `MOCK_DATA`, `ALTITUDE_LIMIT`, `ACCESS_TIME`).
> Le bloc YAML du §12.9 se recopie tel quel dans `rules.py`. Les scénarios S28 à S32 (`scenarios-validation.yaml`, bloc `scenarios_phase2`) chiffrent ces règles.

### 12.1 Balises : poids par horizon, rattachement au déco et à l'atterro

**Poids par horizon.** La fusion vaut `modèle + weight × (balise − modèle)`. Le poids dépend de **Δt**, le nombre de minutes entre `reference_time` et l'instant évalué :
- au déco, Δt mène au **début du créneau** ;
- à l'atterro, Δt mène à l'**heure d'arrivée estimée** (début du créneau + `est_duration_min`). Pour un même plan, la balise de l'atterro pèse donc moins que celle du déco.

| Horizon | Poids nominal `w` | Confiance de base | Extrapolation de la tendance | Rafale retenue |
|---|---|---|---|---|
| 15m | 0,85 | 0,92 | oui | max(rafale balise 10 min, rafale fusionnée) |
| 30m | 0,70 | 0,90 | oui | idem |
| 1h | 0,50 | 0,85 | oui | idem |
| 2h | 0,30 | 0,80 | non | rafale fusionnée |
| 8h | 0,10 (biais du matin seulement, même régime de brise, §8.2) | 0,70 | non | modèle |
| ≥ 12h | 0 | §8.2 | non | modèle |

Entre deux valeurs, on interpole linéairement sur Δt (`beacon_weight_by_minutes`). À Δt = 0, le poids vaut 0,90 : même à l'instant présent, une balise ne donne jamais exactement le vent du déco.

Le poids final, publié dans `StationReading.weight` (0 pour une balise non représentative), vaut :

`weight = w(Δt) × f_distance × f_altitude × f_alt_inconnue × f_fraîcheur` (× 0,3 si la balise est isolée).

Une balise est **représentative** (`representative = true`) si trois conditions sont réunies : elle est fraîche (30 min au plus), elle n'est pas suspecte, et `f_distance × f_altitude × f_alt_inconnue × f_fraîcheur ≥ 0,3`. Une balise isolée reste représentative, avec son poids réduit. Une balise **non représentative** est affichée dans `station_readings`, mais n'entre pas dans la correction (poids effectif 0). S'il y a plusieurs balises représentatives, on fait la moyenne des écarts pondérée par leurs poids.

**Rattachement au déco**

| Critère | Poids 1 | Poids réduit | Non rattachée |
|---|---|---|---|
| Distance | ≤ 1 km (≤ 2 km avec bonus de nom) | linéaire jusqu'à 0,4 à 5 km | > 5 km |
| Écart d'altitude balise − déco | ≤ 100 m | linéaire jusqu'à 0,5 à 300 m. Entre 300 et 600 m : 0,3, et l'écart se calcule avec le vent modèle **à l'altitude de la balise** (on ne corrige que la composante synoptique) | > 600 m (la balise ne sert plus qu'au vent de crête et à `LEE_SIDE`) |
| Nom | bonus si le nom contient « déco », « décollage », « take off » ou le nom du site | — | nom en « atterro », « atterrissage » ou « landing » avec \|Δalt\| > 100 m |

**Rattachement à l'atterro.** Ici on est plus strict, car la balise doit voir la brise du fond de vallée.

| Critère | Poids 1 | Poids réduit | Non rattachée |
|---|---|---|---|
| Distance | ≤ 1,5 km (≤ 2,5 km avec bonus de nom) | linéaire jusqu'à 0,5 à 3 km (à 4 km avec bonus de nom) | au-delà |
| Écart d'altitude balise − atterro | ≤ 50 m | linéaire jusqu'à 0,5 à 150 m (à 200 m avec bonus de nom) | au-delà : une balise à mi-pente ne voit pas la brise de vallée |
| Même vallée | — | — | un point du MNT entre la balise et l'atterro dépasse max(alt. balise, alt. atterro) + 100 m |
| Nom | bonus si le nom contient « atterro », « attero », « atterrissage », « landing », « posé » ou le nom de l'atterro | — | nom en « déco », « décollage », « sommet », « crête », « col » ou « top » avec \|Δalt\| > 50 m |

Le bonus de nom ne fait jamais dépasser un poids de 1. Il élargit seulement les distances et les écarts admis : les coordonnées des balises sont souvent approximatives, et une balise nommée « Doussard atterro » est bien sur l'atterro.

**Altitude de balise inconnue** (`elevation_m = null`, cas fréquent sur Pioupiou) :
- **MNT disponible** : on prend l'altitude du MNT au point de la balise, avec `f_alt_inconnue = 0,8`. Le commentaire précise « altitude estimée (MNT) ».
- **MNT indisponible, balise de déco** : `f_alt_inconnue = 0,5`, sans facteur d'altitude, et rattachement limité à 2 km.
- **MNT indisponible, balise d'atterro** : elle n'est représentative que si elle a le bonus de nom **et** se trouve à moins de 1,5 km, avec `f_alt_inconnue = 0,5`. Sinon elle reste affichée mais non représentative. Le commentaire précise « altitude inconnue ».

**Fraîcheur, balise périmée, suspecte ou isolée**
- **Fraîcheur** : `f_fraîcheur = 1` jusqu'à 10 min, puis décroît linéairement jusqu'à 0,3 à 30 min.
- **Balise périmée** (`stale`, mesure de plus de 30 min) : poids 0 et tendance ignorée. Risk `STALE_BEACONS` en info (horizons ≤ 2 h). On l'affiche en gris avec un commentaire du type « muette depuis 47 min ». À l'atterro, une balise périmée compte comme **absente** (§12.3).
- **Balise suspecte** (poids 0) : moyenne à 0 et rafale à 0 ou nulle, alors que le modèle donne 12 km/h ou plus. C'est un anémomètre bloqué ou une balise abritée. On garde le modèle : c'est le choix prudent pour les seuils, et `LEE_SIDE` contrôle toujours le dévent.
- **Balise isolée** : avec au moins 2 balises représentatives sur le même site, celle qui s'écarte de plus de 10 km/h de la médiane a son facteur multiplié par 0,3. Commentaire : « possiblement abritée ou trop exposée » (§10, piège 16).

**Vent retenu à l'atterro avec balise** (calculé à l'heure d'arrivée) :

`v_fusion = v_modèle(arrivée) + weight × (v_balise − v_modèle(maintenant))`

Chaque vent modèle inclut le facteur de brise de son heure. La direction se corrige de la même façon si le vent fait au moins 8 km/h aux deux instants. Aux horizons 15m, 30m et 1h, la rafale retenue vaut `max(rafale fusionnée, rafale balise 10 min)`. On applique ensuite la tendance (§12.2).

### 12.2 Tendance sur 1 h (`Beacon.trend`)

La tendance n'est utilisable que si `trend` est renseigné, avec `window_min ≥ 45` et `samples ≥ 4`. Sinon on affiche « tendance indisponible », sans règle ni pénalité de confiance.

Notations :
- taux horaire : `r = speed_change_kmh × 60 / window_min` ;
- vent au début de la fenêtre : `v0 = v_balise − speed_change_kmh`.

| Signal (balise rattachée et représentative) | Seuils | Code |
|---|---|---|
| Hausse du vent moyen | `r > 5 km/h/h` → caution si la valeur extrapolée atteint au moins 50 % du seuil du niveau, info sinon. `r > 20 km/h/h` → danger : c'est un changement de régime (front de rafales, orage, percée de foehn, brise anormalement forte) | `WIND_INCREASING` |
| Rotation | `abs(direction_change_deg) ≥ 60°` avec v0 et v ≥ 8 km/h → caution | `WIND_SHIFT` |
| Bascule | `abs(direction_change_deg) ≥ 120°` avec v0 et v ≥ 10 km/h (bascule de brise, convergence, front d'orage) → danger pour beginner et intermediate, caution pour advanced et expert | `WIND_SHIFT` |
| Rafale max de l'heure | `gust_max_kmh` au-dessus du seuil de rafale du niveau → caution. Au-dessus du seuil + 10 km/h → danger. Seuil au déco : `takeoff_gust_max_kmh` ; à l'atterro : `landing_gust_max_kmh` | `TAKEOFF_GUSTS` / `LANDING_WIND` |

**Effet sur le verdict selon l'horizon.** La table vaut pour la balise du déco (évaluée au début du créneau) comme pour celle de l'atterro (évaluée à l'heure d'arrivée).

| Signal | 15m | 30m | 1h | 2h | ≥ 8h |
|---|---|---|---|---|---|
| Hausse > 5 km/h/h | caution + extrapolation | caution + extrapolation | caution + extrapolation | info | ignoré |
| Hausse > 20 km/h/h | **danger** | **danger** | **danger** | caution | ignoré |
| Rotation ≥ 60° | caution | caution | info | ignoré | ignoré |
| Bascule ≥ 120° | danger (beg./int.), caution (adv./exp.) | idem | caution | info | ignoré |
| Rafale max 1 h > seuil | caution | caution | caution | info | ignoré |
| Rafale max 1 h > seuil + 10 | **danger** | **danger** | caution | info | ignoré |
| Valeur extrapolée > seuil du niveau | **danger** (`LANDING_WIND`, `TAKEOFF_WIND` ou `TAKEOFF_GUSTS`) | idem | idem | — | — |

**Extrapolation** (horizons 15m, 30m et 1h, seulement si `r > 5`) :
- vent : `v_ext = v_balise + min(15, r × min(Δt, 60) / 60)` ;
- rafale : `g_ext = rafale balise 10 min + le même incrément`.

On n'extrapole **jamais à la baisse**. Le verdict utilise `max(v_fusion, v_ext)` et `max(rafale retenue, g_ext)`, comparés aux seuils habituels du niveau : strictement au-dessus → no-go ; entre 80 et 100 % → caution.

**Exemple (S28).** À 13 h 45 légales, la balise de Doussard mesure 12 km/h, rafales 17, en hausse de 10 km/h sur l'heure. Le modèle donne 4 km/h, soit 5 km/h avec la brise (× 1,3). Le pilote décolle à 14 h et doit arriver vers 14 h 25 (Δt ≈ 40 min). On obtient `v_ext ≈ 12 + 10 × 40/60 ≈ 19 km/h` et `g_ext ≈ 24 km/h`.
- Brevet confirmé (seuils 25 / 30) : environ 75 % et 80 %. `WIND_INCREASING` passe en caution → **marginal**.
- Brevet de pilote (seuils 20 / 25) : environ 95 % → marginal. Dix minutes de vol de plus suffisent à dépasser 20 km/h → no-go. La valeur extrapolée doit donc se calculer à l'heure d'arrivée **réelle** du plan.

Détail type : « Doussard atterro : 12 km/h (raf. 17), +10 km/h en 1 h, la brise forcit. Environ 19 km/h (raf. 24) attendus à ton arrivée vers 14 h 25, alors que le modèle en prévoit 5. Pose-toi tôt, sans t'éloigner de l'atterro. »

### 12.3 Aucune balise représentative à l'atterro

On est dans ce cas quand il n'y a aucune balise rattachée, ou que la seule balise est trop loin, trop haute, dans une autre vallée, périmée ou suspecte.
- On garde le modèle × facteur de brise, sans tendance.
- **Horizons 15m, 30m et 1h** : Risk `NO_LANDING_BEACON`, en caution **non bloquante** si l'arrivée tombe entre 12 h et 18 h légales (heures de brise), en info sinon. La bande marginale de l'atterro commence à 72 % du seuil au lieu de 80 % (`× 0,9`). Le seuil de no-go, lui, **ne change pas** : l'absence de balise ne suffit jamais à faire un no-go. Confiance × 0,9.
- **Horizon 2h** : `NO_LANDING_BEACON` en info, confiance × 0,95.
- **Horizons ≥ 8h** : rien, les balises n'interviennent pas.
- Détail type : « Pas de balise représentative à l'atterro (la plus proche, Pioupiou X, est à 4,2 km et 230 m plus haut). Vent d'arrivée estimé par le modèle seul : environ 8 km/h, brise comprise. En vol, regarde la manche à air, les drapeaux et la surface du lac, ou demande le vent par radio à un pilote posé. »
- `station_readings` montre quand même la balise non représentative la plus proche (`representative: false`), avec la raison dans `comment`.

### 12.4 Confiance (complète le §8.2)

`confidence = min(0,95 ; base(horizon) × f_dispersion × f_balise_déco × f_balise_atterro)`. Le plafond du mode mock ne change pas.
- `f_balise_déco` est inchangé : × 1,1 si cohérente, × 0,8 si contradictoire, × 1 si absente.
- `f_balise_atterro` :
  - représentative et cohérente : × 1 (pas de second bonus) ;
  - représentative et contradictoire (écart > 10 km/h ou > 45° avec un vent ≥ 8 km/h) : × 0,85, plus `BEACON_MISMATCH` en caution, avec la mention « à l'atterro » ;
  - absente : × 0,9 (horizons ≤ 1 h), × 0,95 (2 h), × 1 (≥ 8 h).
- Exemple (S29) : horizon 15m, balise du déco cohérente, aucune balise à l'atterro → 0,92 × 1,1 × 0,9 ≈ 0,91. Avec une balise d'atterro cohérente, on aurait min(0,95 ; 1,01) = 0,95.

### 12.5 Horizons ≤ 1 h : créneau, briefing et checklist

- **Créneau.** Le pilote est déjà au déco ou en train d'y monter. Le début du créneau est borné, et ne vient jamais moins de 10 min après `reference_time` :

  | Horizon | `window.start` |
  |---|---|
  | 15m | [cible − 10 min ; cible + 45 min] |
  | 30m | [cible − 15 min ; cible + 60 min] |
  | 1h | [cible − 30 min ; cible + 90 min] |

  Le décalage jusqu'à + 3 h du §9.4 ne s'applique pas ici.
- **Briefing.** `briefing[1]`, juste après le verdict, donne la lecture des balises. Exemple : « Balises (il y a 6 min) : déco ONO 12 km/h (raf. 16), stable ; atterro N 14 km/h (raf. 20), +7 km/h en 1 h, la brise forcit. » S'il n'y en a pas : « Pas de balise à l'atterro : … ».
- **Checklist.** Ajouter : « Regarder la manche à air de l'atterro avant de décoller (jumelles), ou demander le vent par radio. »

### 12.6 Décollage libre (vol rando, point cliqué, `mode = "custom_takeoff"`)

Personne n'a vérifié le terrain. On applique donc des seuils de vent plus bas que sur un site officiel, on lit la pente et l'orientation sur le MNT, et on affiche des contrôles terrain obligatoires.

**Niveaux**

| Niveau | Autorisé | Verdict au mieux | `FREE_TAKEOFF` |
|---|---|---|---|
| beginner | **non**, aucun plan. Raison : « Décollage libre non proposé au niveau élève : uniquement sous la responsabilité d'un moniteur présent sur place. » | — | danger |
| intermediate | oui | marginal | caution |
| advanced | oui | go | info |
| expert | oui | go | info |

Un décollage libre compte comme un site de difficulté intermediate : on a donc toujours `plan.difficulty ≥ intermediate`.

**Terrain.** La pente se mesure sur le MNT : pente moyenne sur les 150 m sous le point, dans la ligne de plus grande pente, avec un point tous les 50 m. L'orientation est la direction vers laquelle la pente fait face. Si le pilote ne donne pas `orientations`, on prend l'orientation ± 22,5°.

| Critère | Valeur | Hors limite |
|---|---|---|
| Pente minimale | 25 % (14°) sans vent ; 15 % (8,5°) avec au moins 10 km/h de vent de face | `FREE_TAKEOFF` danger : « pente trop faible pour décoller » |
| Pente idéale | 30-50 % (17-27°) | — |
| Pente maximale | intermediate 60 % (31°), advanced 70 % (35°), expert 80 % (39°) | `FREE_TAKEOFF` danger : « pente trop raide pour gonfler et courir en sécurité » |
| Profil dans l'axe | sur 300 m, aucun point du MNT au-dessus de la droite `alt_déco − d/6` | `FREE_TAKEOFF` danger : « bosse ou contre-pente dans l'axe de décollage » |
| Aire de gonflage | au moins 30 × 15 m dégagés. Le MNT ne permet pas de le vérifier : c'est un contrôle obligatoire | — |

**Vent au point** (interpolé à l'altitude du déco). Ces limites s'ajoutent aux contrôles habituels des §2 et §3.

| | intermediate | advanced | expert |
|---|---|---|---|
| Vent moyen max (km/h) | 15 | 20 | 25 |
| Rafale max (km/h) | 20 | 25 | 30 |
| Écart rafale − moyenne max (km/h) | 8 | 10 | 12 |
| Angle max entre le vent et la pente | 20° | 30° | 45° |
| Vent arrière | interdit dès 3 km/h (`TAILWIND` danger) | idem | idem |

- **Vent nul** (< 5 km/h) : accepté seulement si la pente fait au moins 25 %.
- **Angle vent/pente** : écart entre la direction d'où vient le vent et l'orientation de la pente, sans la tolérance de ± 11,25° des secteurs.
- **Dépassement** : `TAKEOFF_WIND`, `TAKEOFF_GUSTS` ou `CROSSWIND` en danger. Entre 80 et 100 % du seuil : caution.

**Contrôles obligatoires.** Ils figurent dans la `checklist` et dans le bloc Décollage du `briefing`.
1. **Réglementation** : autorisation du propriétaire ou de la commune. Pas de décollage en cœur de parc national, en réserve naturelle, sous arrêté de biotope ni dans une zone Biodiv'Sports active.
2. **Reconnaissance à pied** de l'aire et de l'axe : pierres, souches, clôtures, câbles, téléskis, lignes, randonneurs, bétail. Prévoir de quoi interrompre le décollage.
3. **Observer le vent 5 min** (manche, rubalise, herbes). Il doit être de face et régulier : ni rotor, ni dévent, ni cycles thermiques trop forts.
4. **Repérer l'atterro à vue avant de gonfler**, dans le cône de finesse, ainsi qu'un atterro de secours.
5. **Espaces aériens, NOTAM et zones sensibles** vérifiés. Prévenir un proche (point de décollage exact, heure, atterro prévu). Radio sur 143,9875.
6. **Matériel** (aile légère, secours, casque) et prévol complète après la marche. Penser à la sueur, à la fatigue et à l'hydratation.

**Avertissement** (Risk `FREE_TAKEOFF`, en tête du bloc Décollage) : « Décollage libre, hors site officiel : pente, obstacles et vent ne sont vérifiés par personne. Reconnais le terrain à pied, vérifie l'autorisation, et ne décolle qu'une fois tous les contrôles faits. »

### 12.7 Atterros non officiels (`community`, `field`)

**Catégories** (`LandingKind` du contrat) :
- `official` : atterro officiel ou référencé (FFVL, fixture, ParaglidingEarth validé).
- `community` : atterro utilisé par les pilotes mais non validé par la FFVL (ParaglidingEarth non officiel, OSM `free_flying:site=landing`, contribution).
- `field` : champ candidat détecté automatiquement (OSM + MNT), que personne n'a repéré.

**Niveaux autorisés.** On filtre d'abord par `landing_policy` : `official_only` garde les officiels, `include_community` ajoute les communautaires, `include_fields` ajoute les champs. On applique ensuite cette table :

| Catégorie | beginner | intermediate | advanced | expert |
|---|---|---|---|---|
| official | principal et secours | principal et secours | principal et secours | principal et secours |
| community | jamais | principal seulement si `community_usage = frequent`, sinon secours ; `UNOFFICIAL_LANDING` en caution | principal et secours ; `UNOFFICIAL_LANDING` en info | comme advanced |
| field | **jamais** | secours seulement, jamais principal | principal, mais au mieux marginal (`DETECTED_FIELD` en caution) ; en secours, info | comme advanced |

Pour un beginner, `landing_policy` est ramené à `official_only`, avec ce warning : « Élève : seuls les atterros officiels sont proposés. »

**Critères minimaux** (atterros non officiels seulement). Il manque un critère → le candidat est exclu, et on dit pourquoi.

| Critère | intermediate | advanced | expert |
|---|---|---|---|
| Longueur × largeur (longueur dans l'axe du vent à l'arrivée) | 150 × 50 m | 120 × 40 m | 100 × 30 m |
| Pente max | 8 % | 10 % | 12 % |
| Distance aux lignes électriques, téléphoniques et câbles | ≥ 150 m | ≥ 100 m | ≥ 100 m |
| Distance aux arbres et bâtiments (depuis le bord du champ) | ≥ 30 m | ≥ 25 m | ≥ 20 m |
| Distance à l'eau (lac, rivière, canal) | ≥ 100 m | ≥ 50 m | ≥ 50 m |
| Distance aux routes | ≥ 30 m | ≥ 30 m | ≥ 30 m |
| Finale | 150 m sans obstacle de plus de 10 m dans l'axe. Longueur utile = longueur − 5 × hauteur de l'obstacle en bout de finale | idem | idem |
| Angle entre l'axe du champ et le vent à l'arrivée | ≤ 45° | ≤ 45° | ≤ 45° |
| Marge de finesse supplémentaire (`required ≤ available × f`) | community f = 0,90 ; field f = 0,80 | idem | idem |
| Hauteur d'arrivée mini au-dessus du terrain | community 150 m ; field 200 m (secours) | community 120 m ; field 150 m | community 100 m ; field 150 m |

- **Obstacle non cartographié** (distance inconnue) : le candidat n'est pas exclu, mais son sous-score « obstacles » tombe à 50 et `warnings` le signale, par exemple « lignes électriques non cartographiées : à repérer en vol ».
- **Exclusions en plus des critères** : vent ou rafales à l'arrivée au-dessus du seuil du niveau ; terrain en cœur de parc national, en réserve ou dans une zone sensible active (`SENSITIVE_AREA`) ; ligne de plané coupée par le relief.
- **Glide du plan** : pour un atterro non officiel, `glide.available_ratio` inclut le facteur f.

**Classement des candidats** (`LandingCandidate.score`, de 0 à 100) : `score = Σ poids × sous-score + bonus de catégorie`, plafonné à 100. Le bonus vaut + 15 pour un officiel, + 5 pour un communautaire, 0 pour un champ : à conditions égales, un pilote prend toujours l'officiel.

| Sous-score | Poids | 100 = | 0 = |
|---|---|---|---|
| Marge de finesse `required / (available × f)` | 25 | ≤ 0,75 | 1,0 (courbe `glide_subscore_curve` du §11) |
| Obstacles (lignes, arbres, bâtiments, eau) | 20 | toutes les distances ≥ 2 × le minimum | une distance au minimum |
| Vent et brise à l'arrivée (vent, rafales, axe du champ) | 15 | < 50 % du seuil et axe ≤ 15° | au seuil, ou axe à 45° |
| Taille | 10 | ≥ 2 × le minimum | au minimum |
| Usage communautaire | 10 | official 100 · frequent 80 · occasional 50 · unknown 20 · field 0 | |
| Pente | 8 | ≤ 3 % | maximum du niveau |
| Accès (route ou parking) | 7 | ≤ 200 m | > 1 km (inconnu : 30) |
| Balise représentative | 5 | oui | non |

`reasons` explique les 2 ou 3 sous-scores qui ont décidé. Exemple : « 1,6 km, marge de finesse confortable (0,64) ; pré de 200 × 80 m ; route à 50 m ».

**Avertissements obligatoires.** Ils vont dans `LandingCandidate.warnings`, puis dans le Risk et dans le bloc Atterrissage du briefing.
- **community** : « Non officiel : repérage et autorisation du propriétaire à vérifier. Atterro utilisé par les pilotes, mais non validé par la FFVL : vérifie l'état du terrain (cultures, bétail, clôtures, lignes) et repère-le en vol avant de t'engager. »
- **field** : « Champ détecté automatiquement, jamais repéré : à vérifier sur place. Non officiel : repérage et autorisation du propriétaire à vérifier. Les lignes électriques, les clôtures, les cultures hautes et la pente ne sont pas toutes visibles sur la carte : survole-le à 150 m au moins et garde une autre option. »
- **field, de mai à septembre** : « Saison des cultures et des foins : on ne se pose pas dans un champ cultivé ou en herbe haute (dégâts, risque de culbute). »
- **Obstacle connu à moins de 2 fois la distance minimale** : par exemple « Ligne électrique à 160 m au sud-est du champ ». On l'inscrit dans `obstacles` et on le reprend dans `warnings`.

**Rejet expliqué.** Si aucun atterro autorisé n'est à portée, la raison de rejet nomme le meilleur candidat écarté et la cause, même quand le plan est déjà rejeté pour une autre raison (par exemple `FREE_TAKEOFF` pour un élève) :
- `[DETECTED_FIELD] Seul un champ détecté (jamais repéré) est à portée de plané : jamais proposé à ce niveau.` (danger, pour beginner et intermediate)
- `[UNOFFICIAL_LANDING] Seul un atterro communautaire est à portée : non proposé à un élève.`
- `[GLIDE_MARGIN] Aucun atterro à portée de plané avec la marge requise.`

### 12.8 Codes Risk de la section

| Code | Quand | Niveau | Titre |
|---|---|---|---|
| `WIND_INCREASING` | tendance d'une balise : hausse > 5 km/h/h (§12.2) | caution ; danger au-delà de 20 km/h/h | « Le vent forcit au déco » / « Le vent forcit à l'atterro » |
| `WIND_SHIFT` | rotation ≥ 60° ou bascule ≥ 120° en 1 h | caution ou danger (§12.2) | « Le vent tourne » |
| `NO_LANDING_BEACON` | aucune balise représentative à l'atterro, horizon ≤ 2 h | caution **non bloquante** ou info (§12.3) | « Pas de balise à l'atterro » |
| `BEACON_MISMATCH` | (existant) balise du déco ou de l'atterro qui contredit le modèle | caution | « Balises en désaccord avec la prévision » |
| `STALE_BEACONS` | (existant) balise rattachable périmée | info | « Balises anciennes » |
| `FREE_TAKEOFF` | `mode = custom_takeoff`, ou terrain hors limites | info, caution ou danger (§12.6) | « Décollage libre (hors site officiel) » |
| `UNOFFICIAL_LANDING` | atterro principal `community` ; seul atterro à portée pour un élève | caution (intermediate), info (advanced, expert) ; danger dans le cas élève (rejet) | « Atterro non officiel » |
| `DETECTED_FIELD` | atterro principal `field` (advanced, expert) ; seul atterro à portée (beginner, intermediate) ; champ en secours seulement | caution ; danger (rejet) ; info | « Champ détecté, jamais repéré » |

### 12.9 Valeurs pour `rules.py`

```yaml
# --- (a) balises, horizon 15 min, tendance ------------------------------------------------------------
horizon_minutes_add: {"15m": 15}                     # à ajouter à HORIZON_MINUTES (models.py)
horizon_beacon_weight:   {"15m": 0.85, "30m": 0.7, "1h": 0.5, "2h": 0.3, "8h": 0.1, "12h": 0, "24h": 0, "48h": 0}
horizon_base_confidence: {"15m": 0.92, "30m": 0.9, "1h": 0.85, "2h": 0.8, "8h": 0.7, "12h": 0.65, "24h": 0.55, "48h": 0.4}
beacon_weight_by_minutes: {0: 0.90, 15: 0.85, 30: 0.70, 60: 0.50, 120: 0.30, 480: 0.10, 720: 0.0}  # Δt depuis reference_time ; atterro : jusqu'à l'ARRIVÉE ; interpolation linéaire
beacon_gust_horizons: ["15m", "30m", "1h"]           # rafale retenue = max(rafale balise 10 min, rafale fusionnée)
nowcast_horizons: ["15m", "30m", "1h", "2h"]         # horizons où NO_LANDING_BEACON / STALE_BEACONS existent
nowcast_window_start_min: {"15m": [-10, 45], "30m": [-15, 60], "1h": [-30, 90]}   # bornes de window.start autour de la cible
nowcast_min_lead_min: 10                             # window.start ≥ reference_time + 10 min
beacon_freshness_min: {full_weight: 10, stale: 30, factor_at_stale: 0.3}           # > 30 min : périmée (poids 0)
beacon_representative_min_factor: 0.3                # f_distance × f_altitude × f_alt_inconnue × f_fraîcheur
beacon_suspect_model_min_kmh: 12                     # balise à 0 (rafale 0 ou nulle) et modèle ≥ 12 → poids 0
beacon_outlier: {deviation_kmh: 10, factor: 0.3}     # ≥ 2 balises représentatives : écart à la médiane > 10 km/h
takeoff_beacon_attach:
  distance_km: {full: 1.0, max: 5.0, factor_at_max: 0.4}
  alt_diff_m: {full: 100, reduced: 300, factor_at_reduced: 0.5, synoptic_max: 600, factor_synoptic: 0.3}  # 300-600 m : biais calculé au vent modèle à l'altitude de la balise
  name_bonus: {keywords: ["déco", "deco", "décollage", "decollage", "take off", "takeoff"], site_name: true, full_distance_km: 2.0}
  wrong_role: {keywords: ["atterro", "attero", "atterrissage", "landing"], max_alt_diff_m: 100}           # au-delà : non rattachée au déco
landing_beacon_attach:
  distance_km: {full: 1.5, max: 3.0, factor_at_max: 0.5}
  alt_diff_m: {full: 50, max: 150, factor_at_max: 0.5}
  name_bonus: {keywords: ["atterro", "attero", "atterrissage", "landing", "posé"], site_name: true, full_distance_km: 2.5, max_distance_km: 4.0, max_alt_diff_m: 200}
  wrong_role: {keywords: ["déco", "deco", "décollage", "sommet", "crête", "col", "top"], max_alt_diff_m: 50}
  same_valley_relief_margin_m: 100                   # aucun point MNT du segment au-dessus de max(alt balise, alt atterro) + 100 m
unknown_beacon_altitude:
  dem_factor: 0.8                                    # altitude prise sur le MNT
  no_dem_factor: 0.5
  no_dem_takeoff_max_distance_km: 2.0
  no_dem_landing: {requires_name_bonus: true, max_distance_km: 1.5}                # sinon non représentative
trend_1h:
  min_window_min: 45
  min_samples: 4
  wind_increase_kmh_per_h: {caution: 5, danger: 20}  # strictement supérieur ; r = speed_change × 60 / window_min
  caution_min_ratio_to_threshold: 0.5                # caution seulement si max(v_fusion, v_ext) ≥ 50 % du seuil du niveau, sinon info
  rotation: {caution_deg: 60, min_wind_kmh: 8}
  reversal: {deg: 120, min_wind_kmh: 10, level: {beginner: danger, intermediate: danger, advanced: caution, expert: caution}}
  gust_max_over_threshold_kmh: {caution: 0, danger: 10}   # gust_max_kmh > seuil rafale du niveau (+ 10 → danger)
  extrapolate_horizons: ["15m", "30m", "1h"]
  extrapolate_max_minutes: 60
  extrapolate_cap_kmh: 15
  extrapolate_down: false
trend_impact:                                        # niveau du Risk par horizon ; horizon absent = ignoré
  wind_increase:      {"15m": caution, "30m": caution, "1h": caution, "2h": info}
  wind_increase_high: {"15m": danger,  "30m": danger,  "1h": danger,  "2h": caution}
  rotation:           {"15m": caution, "30m": caution, "1h": info}
  reversal:           {"15m": by_level, "30m": by_level, "1h": caution, "2h": info}
  gust_max:           {"15m": caution, "30m": caution, "1h": caution, "2h": info}
  gust_max_high:      {"15m": danger,  "30m": danger,  "1h": caution, "2h": info}
no_landing_beacon:
  level: {"15m": caution, "30m": caution, "1h": caution, "2h": info}
  caution_legal_hours: [12, 18]                      # arrivée hors de cette plage → info
  blocking: false                                    # à ajouter à NON_BLOCKING_CAUTIONS
  landing_marginal_band_factor: {"15m": 0.9, "30m": 0.9, "1h": 0.9}   # bande marginale atterro dès 72 % ; seuil no-go inchangé
  confidence_factor: {"15m": 0.9, "30m": 0.9, "1h": 0.9, "2h": 0.95}
landing_beacon_confidence_factor: {coherent: 1.0, contradictory: 0.85}
risk_codes_add: [NO_LANDING_BEACON, WIND_SHIFT, FREE_TAKEOFF, UNOFFICIAL_LANDING, DETECTED_FIELD]
non_blocking_cautions_add: [NO_LANDING_BEACON]

# --- (b) décollage libre (mode custom_takeoff) --------------------------------------------------------
free_takeoff:
  allowed_levels: [intermediate, advanced, expert]   # jamais beginner
  site_difficulty: intermediate                      # plan.difficulty ≥ intermediate
  risk_level: {beginner: danger, intermediate: caution, advanced: info, expert: info}   # FREE_TAKEOFF
  best_verdict: {intermediate: marginal, advanced: go, expert: go}
  wind_max_kmh: {intermediate: 15, advanced: 20, expert: 25}
  gust_max_kmh: {intermediate: 20, advanced: 25, expert: 30}
  gust_spread_max_kmh: {intermediate: 8, advanced: 10, expert: 12}
  wind_slope_angle_max_deg: {intermediate: 20, advanced: 30, expert: 45}   # vent / orientation de la pente, sans tolérance de secteur
  tailwind_max_kmh: 3                                # vent arrière ≥ 3 km/h → TAILWIND danger
  calm_kmh: 5                                        # vent nul accepté seulement si pente ≥ min_without_headwind
  slope_pct:
    min: 15                                          # avec vent de face ≥ headwind_for_gentle_kmh
    min_without_headwind: 25
    headwind_for_gentle_kmh: 10
    ideal: [30, 50]
    max: {intermediate: 60, advanced: 70, expert: 80}
  slope_sampling: {downslope_m: 150, step_m: 50}
  axis_profile: {distance_m: 300, max_slope_line: 0.1667}   # aucun point MNT au-dessus de alt_déco − d/6
  orientation_halfwidth_deg: 22.5                    # orientations déduites de l'exposition MNT
  clear_area_m: {length: 30, width: 15}              # non vérifiable au MNT : contrôle obligatoire
  refusal_beginner: "Décollage libre non proposé au niveau élève : uniquement sous la responsabilité d'un moniteur présent sur place."
  warning: "Décollage libre, hors site officiel : pente, obstacles et vent ne sont vérifiés par personne. Reconnais le terrain à pied, vérifie l'autorisation, et ne décolle qu'une fois tous les contrôles faits."
  mandatory_checks:
    - "Autorisation du propriétaire ou de la commune ; pas de décollage en cœur de parc national, réserve naturelle, arrêté de biotope ou zone Biodiv'Sports active."
    - "Reconnaissance à pied de l'aire et de l'axe : pierres, souches, clôtures, câbles, téléskis, lignes, randonneurs, bétail ; prévoir de quoi interrompre le décollage."
    - "Observer le vent 5 min (manche, rubalise, herbes) : de face et régulier, ni rotor, ni dévent, ni cycles thermiques trop forts."
    - "Atterro repéré à vue avant de gonfler, dans le cône de finesse, plus un atterro de secours."
    - "Espaces aériens, NOTAM et zones sensibles vérifiés ; prévenir un proche (point exact, heure, atterro prévu) ; radio 143,9875."
    - "Matériel (aile légère, secours, casque) et prévol complète après la marche (sueur, fatigue, hydratation)."

# --- (c) atterros non officiels -----------------------------------------------------------------------
landing_policy_kinds:
  official_only: [official]
  include_community: [official, community]
  include_fields: [official, community, field]
beginner_landing_policy: official_only               # forcé, avec warning « Élève : seuls les atterros officiels sont proposés. »
landing_kind_use:                                    # main = principal possible ; alternate = secours seulement ; never
  official:  {beginner: main, intermediate: main, advanced: main, expert: main}
  community: {beginner: never, intermediate: main_if_frequent, advanced: main, expert: main}   # sinon alternate
  field:     {beginner: never, intermediate: alternate, advanced: main_marginal, expert: main_marginal}
unofficial_landing_min:                              # community et field ; un critère manquant → candidat exclu
  length_m: {intermediate: 150, advanced: 120, expert: 100}
  width_m:  {intermediate: 50,  advanced: 40,  expert: 30}
  slope_pct_max: {intermediate: 8, advanced: 10, expert: 12}
  power_line_clearance_m: {intermediate: 150, advanced: 100, expert: 100}
  tree_building_clearance_m: {intermediate: 30, advanced: 25, expert: 20}
  water_clearance_m: {intermediate: 100, advanced: 50, expert: 50}
  road_clearance_m: 30
  approach_free_m: 150                               # aucun obstacle > 10 m dans l'axe de finale
  approach_obstacle_length_factor: 5                 # longueur utile = longueur − 5 × hauteur de l'obstacle en bout de finale
  long_axis_vs_wind_max_deg: 45
  unknown_clearance_subscore: 50                     # obstacle non cartographié : pas d'exclusion, sous-score 50 + warning
unofficial_glide:
  available_factor: {community: 0.90, field: 0.80}   # required ≤ available × facteur (en plus de glide_k)
  arrival_height_min_m:
    community: {intermediate: 150, advanced: 120, expert: 100}
    field:     {intermediate: 200, advanced: 150, expert: 150}
landing_candidate_weights: {glide_margin: 25, obstacles: 20, wind_at_arrival: 15, size: 10, community_usage: 10, slope: 8, access: 7, beacon: 5}   # somme 100
landing_category_bonus: {official: 15, community: 5, field: 0}
community_usage_subscore: {official: 100, frequent: 80, occasional: 50, unknown: 20, field: 0}
access_subscore_by_road_m: {200: 100, 1000: 50}      # > 1000 m : 0 ; inconnu : 30
access_unknown_subscore: 30
size_subscore_full_at: 2.0                           # × dimensions minimales
obstacle_subscore_full_at: 2.0                       # × distances minimales
field_crop_season_months: [5, 6, 7, 8, 9]
unofficial_warnings:
  community: "Non officiel : repérage et autorisation du propriétaire à vérifier. Atterro utilisé par les pilotes, mais non validé par la FFVL : vérifie l'état du terrain (cultures, bétail, clôtures, lignes) et repère-le en vol avant de t'engager."
  field: "Champ détecté automatiquement, jamais repéré : à vérifier sur place. Non officiel : repérage et autorisation du propriétaire à vérifier. Les lignes électriques, les clôtures, les cultures hautes et la pente ne sont pas toutes visibles sur la carte : survole-le à 150 m au moins et garde une autre option."
  field_season: "Saison des cultures et des foins : on ne se pose pas dans un champ cultivé ou en herbe haute (dégâts, risque de culbute)."
  unknown_clearance: "Lignes électriques non cartographiées : à repérer en vol."
  beginner_policy: "Élève : seuls les atterros officiels sont proposés."
risk_levels:
  UNOFFICIAL_LANDING: {intermediate: caution, advanced: info, expert: info, only_reachable_beginner: danger}   # atterro principal community
  DETECTED_FIELD: {main: caution, only_reachable_beginner_intermediate: danger, alternate_only: info}
  FREE_TAKEOFF: {beginner: danger, intermediate: caution, advanced: info, expert: info}
```

### 12.10 Conduite à tenir (résumé)

1. **Balise d'atterro rattachée et fraîche** : vent d'arrivée = fusion (poids calculé sur l'heure d'arrivée), puis extrapolation de la tendance pour les horizons ≤ 1 h, plafonnée à + 15 km/h et jamais à la baisse. Valeur extrapolée au-delà du seuil du niveau, ou hausse de plus de 20 km/h/h → no-go. Hausse de plus de 5 km/h/h → `WIND_INCREASING` caution, au mieux marginal.
2. **Pas de balise représentative à l'atterro** : modèle × brise, `NO_LANDING_BEACON` (caution non bloquante pendant les heures de brise, info sinon), bande marginale à 72 % et confiance × 0,9. Ce n'est jamais un no-go à lui seul.
3. **Altitude de balise inconnue** : MNT × 0,8. Sans MNT : × 0,5, et à l'atterro seulement si la balise a le bonus de nom et se trouve à moins de 1,5 km.
4. **Atterro en rafales alors que le déco est calme** : c'est l'atterro qui décide (`LANDING_WIND`, selon le niveau).
5. **Décollage libre** : jamais pour un élève, au mieux marginal pour un brevet de pilote. Seuils de vent plus bas (15 / 20 / 25 km/h), pente de 25 % minimum (15 % avec au moins 10 km/h de face) à 60-80 % selon le niveau, aucun vent arrière, contrôles obligatoires affichés.
6. **Atterros non officiels** : jamais pour un élève ; un champ détecté n'est jamais l'atterro principal d'un brevet de pilote. Marges renforcées (finesse × 0,9 / × 0,8, hauteur d'arrivée 100 à 200 m), avertissement « Non officiel : … » toujours affiché dans `warnings`, dans les Risks et dans le briefing.

---

## 13. Résumé pour le développeur backend (11 lignes)

1. **Filtrer d'abord, scorer ensuite** : un seul no-go (§3) ou un seuil du niveau dépassé (§2) élimine le plan ; le score ne compense jamais la sécurité (`score ≤ 40 + min sous-score sécurité`).
2. **Vent au déco = vent interpolé à l'altitude réelle du déco**, moyenne/max sur 10 min pour les balises ; écart angulaire calculé par rapport au secteur `orientations` le plus proche.
3. **Le faux calme tue** : vent ≥ 15 km/h au niveau de la crête venant de l'arrière du déco = no-go, même si la balise du déco affiche une brise favorable.
4. **L'atterro se juge à l'heure d'arrivée**, avec la brise de vallée (×1,3 sur AROME entre 13h et 17h dans les grandes vallées) et une finesse de calcul sol = polaire × k(niveau) × (V_air + vent arrière)/V_air.
5. **Toujours un atterro identifié dans le cône de finesse**, vérifié tous les 500 m de route avec le profil de terrain ; publier l'altitude de sécurité = points de décision.
6. **Fenêtre thermique en heure solaire** selon saison (§4.1) et orientation de face (§4.2) ; dernier atterrissage pour un GO = `min(convection_end + 30 min, surdév − 1 h, coucher − 30 min)` ; atterrissage après le coucher = no-go.
7. **Routes de cross** : face au vent d'abord, points sur faces ensoleillées à l'ETA, transitions au plus étroit, jamais sous le vent / en venturi ; `V_eff = V_xc − W²/V_xc` en circuit fermé.
8. **Espaces aériens en 3D** convertis en AMSL, plafond FL115 (~3500 m), R/ZRT au statut inconnu = caution ; parcs nationaux, réserves et zones rapaces = zones à éviter.
9. **Pondération balises/modèles décroissante avec l'horizon** (0,85 à 15 min, 0,7 à 30 min → 0 à 12 h) et confiance = base(horizon) × dispersion inter-modèles × cohérence balises ; mode mock affiché en clair.
10. **La `difficulty` du plan = le plus petit niveau dont tous les seuils passent** (et ≥ difficulté du site / du type de vol) ; diversifier les résultats (≤ 2 plans par déco) et expliquer chaque `marginal`.
11. **Nowcasting et hors-site (§12)** : balise d'atterro pondérée sur l'heure d'arrivée et tendance extrapolée (≤ 1 h, jamais à la baisse) ; absence de balise d'atterro = `NO_LANDING_BEACON` non bloquant, jamais un no-go ; décollage libre interdit à l'élève, atterros `community`/`field` filtrés par niveau, avec marges renforcées et avertissement « Non officiel » systématique.
