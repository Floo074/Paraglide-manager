# Cahier des charges pilote — Paraglide Manager

> Rédigé du point de vue d'un moniteur fédéral FFVL / pilote cross & compétition (Alpes du Nord et du Sud).
> Destinataires : backend (`engine/rules.py`, scoring, routage, briefing) et frontend (carte, fiche plan).
> Unités = celles du contrat d'API : km/h, m AMSL (sauf `_agl`), m/s, degrés « d'où vient le vent ».
> Tous les seuils ci-dessous sont des **valeurs par défaut réglables** : ils doivent vivre dans `rules.py`, nulle part ailleurs.

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
| **Facteur de rafale max** (rafale/moyenne, si moyenne ≥ 10) | 1,4 | 1,5 | 1,6 | 1,7 |
| **Vent de travers max** (écart angulaire) | 30° | 45° | 60° | 75° |
| ↳ composante de travers max (`v·sin(écart)`) | 6 km/h | 10 km/h | 13 km/h | 16 km/h |
| **Vent arrière** | Interdit (seul vent nul < 5 km/h accepté) | Interdit (vent nul < 5 km/h seulement) | ≤ 5 km/h, déco pentu uniquement | ≤ 8 km/h, déco pentu uniquement |
| **Vent max à 1500 m** | 15 km/h | 20 km/h | 25 km/h | 30 km/h |
| **Vent max à 2000 m** | 20 km/h | 25 km/h | 30 km/h | 35 km/h |
| **Vent max à 3000 m** | 25 km/h (rarement atteint) | 30 km/h | 35 km/h | 40 km/h |
| **Vent max à l'atterro (brise incluse)** | 15 km/h, rafales 20 | 20 km/h, rafales 25 | 25 km/h, rafales 30 | 28 km/h, rafales 35 |
| **Vario thermique moyen max** (`thermal_strength_ms`) | 1,5 m/s | 2,5 m/s | 3,5 m/s | 5,0 m/s (au-delà : caution) |
| **Gradient de vent** déco → déco+1000 m (Δ vitesse) | ≤ 10 km/h | ≤ 15 km/h | ≤ 20 km/h | ≤ 25 km/h |
| **Rotation du vent** déco → plafond (si vents ≥ 10 km/h) | ≤ 45° | ≤ 60° | ≤ 90° | ≤ 120° |
| **Cisaillement local** (Δ vitesse sur 300 m, typiquement à l'inversion) | ≤ 8 km/h | ≤ 12 km/h | ≤ 15 km/h | ≤ 20 km/h |
| **Plafond utile mini au-dessus du déco — vol local thermique** | +700 m (et vario ≤ 1,5) | +600 m | +400 m | +300 m |
| **Plafond utile mini — cross** | — (pas de cross) | déco +1200 m ET relief max de la route +500 m | déco +1000 m ET relief max +400 m | déco +800 m ET relief max +300 m |
| **Coefficient finesse de calcul** `k` (finesse_calcul = polaire × k) | 0,50 (→ 4,3 pour 8,5) | 0,60 (→ 5,1) | 0,65 (→ 5,5) | 0,70 (→ 6,0) |
| **Marge d'arrivée au-dessus de l'atterro** (entrée dans l'approche) | 200 m | 150 m | 120 m | 100 m |
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
- Exemple : polaire 8,5, intermediate → 5,1 ; vent de face 15 km/h → 5,1 × 22/37 = **3,0**. C'est réaliste : face à une brise de 15 km/h, on « ne va nulle part ».
- Ajouter **−10 %** sur la finesse de calcul si la ligne de plané passe sous le vent d'un relief ou dans une vallée en brise descendante.

---

## 3. Critères no-go absolus (tous niveaux)

| # | Critère | Règle chiffrée (no-go) | Marginal (caution) |
|---|---|---|---|
| 1 | **Pluie** | `precipitation_mm_h ≥ 0,2` sur le créneau ±1 h au déco OU sur la route ; ou pluie ≥ 1 mm dans les 3 h précédant le déco (aile mouillée → risque de parachutale, sol froid) | 0,05-0,2 mm/h ; averses possibles dans la zone |
| 2 | **Orage** | `CAPE ≥ 800 J/kg ET LI ≤ −2` ; ou `CAPE ≥ 1500` quel que soit LI ; ou précipitations convectives prévues < 30 km dans les 2 h après l'atterrissage prévu | `CAPE 300-800 ET LI ≤ 0` → fin de créneau avancée à 14h solaire |
| 3 | **Surdéveloppement** | `overdevelopment_risk = "high"` ET créneau du vol après l'heure de surdév estimée | `moderate` → fin du créneau = heure surdév − 1 h |
| 4 | **Foehn** | Vent ≥ 40 km/h à 700 hPa (~3000 m) perpendiculaire à la crête principale (Alpes du Nord : secteur S-SW ; Alpes du Sud / Briançonnais : N-NW) ; ou Δ pression ≥ 4 hPa entre versants (ex. Turin−Genève) ; ou lenticulaires / mur de foehn | Vent 25-40 km/h à 700 hPa dans ces secteurs ; air anormalement sec et chaud en vallée sous le vent (T +4 °C vs prévision, HR < 40 %) |
| 5 | **Vent régional** (mistral, tramontane, bise) | Mistral/bise ≥ 30 km/h au sol en vallée du Rhône / bassin genevois → no-go dans la zone d'influence | 20-30 km/h |
| 6 | **Base des nuages / visibilité** | `cloud_base_m < alt_déco + 200` ; nuages bas ≥ 80 % avec base < déco + 300 ; brouillard/stratus sur l'atterro ; visibilité < 5 km ; `T − Td < 1,5 °C` au déco | base < déco + 500 (pas de thermique exploitable) |
| 7 | **Vent fort en altitude** | Vent ≥ 45 km/h à un niveau atteint par le vol (déco → plafond utile + 300 m) ; ou ≥ 50 km/h à 3000 m en montagne même si le plafond est plus bas (turbulence descend) | 35-45 km/h |
| 8 | **Vent météo opposé (dévent)** | Vent au niveau des crêtes ≥ 15 km/h venant d'un secteur à plus de 120° de l'axe du déco (le déco est sous le vent) — **même si la balise du déco indique une brise favorable** | 10-15 km/h opposé ; vent météo de travers ≥ 20 km/h |
| 9 | **Vent au déco hors limites** | Vent moyen > 30 km/h ou rafales > 35 km/h (tous niveaux) ; écart rafale-moyenne > 15 km/h | cf. tableau §2 par niveau |
| 10 | **Atterrissage** | Vent à l'atterro > 28 km/h ou rafales > 35 km/h à l'heure d'arrivée ; aucun atterro accessible avec la finesse de calcul | brise > seuil du niveau − 20 % |
| 11 | **Jour aéronautique** | Atterrissage estimé après le coucher du soleil (le vol libre se pratique de jour) | atterrissage < 30 min avant coucher |
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
| 30 min | 0,7 (persistance + tendance 60 min) | 0,3 | AROME | 0,90 |
| 1 h | 0,5 | 0,5 | AROME (+ICON-D2) | 0,85 |
| 2 h | 0,3 | 0,7 | AROME + ICON-D2 | 0,80 |
| 8 h | 0,1 (correction de biais du matin uniquement) | 0,9 | AROME + ICON-D2 | 0,70 |
| 12 h | 0 | 1 | AROME + ICON-D2 + ECMWF | 0,65 |
| 24 h | 0 | 1 | AROME + ICON-D2 + ECMWF | 0,55 |
| 48 h | 0 | 1 | ECMWF (+ AROME si dispo) | 0,40 |

Règles :
- **Ne corriger par les balises que si le régime diurne est le même** : une balise à 9h (brise descendante) ne corrige pas une prévision à 11h (brise montante). Corriger la composante synoptique (vent de crête) plutôt que le vent de fond de vallée.
- Balise utilisable si : distance < 5 km du site ET |Δalt| < 300 m (sinon poids divisé par 2), fraîcheur < 30 min.
- Tendance : si la moyenne 10 min a augmenté de > 5 km/h sur la dernière heure → extrapoler pour 30 min-1 h et ajouter un risque « vent qui forcit ».
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
| `landing` (vent/brise à l'heure d'arrivée, marge de finesse, atterros de secours) | 15 | brise < 50 % du seuil, `required ≤ 0,7 × available` | au seuil / marge nulle |
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

- **go** : aucun no-go, score ≥ 65, tous les critères de sécurité (`takeoff_wind`, `wind_aloft`, `landing`, `convective_stability`) ≥ 50, confiance ≥ 0,5.
- **marginal** : aucun no-go, mais score 45-65, ou un critère de sécurité dans la zone 80-100 % du seuil, ou confiance < 0,5. **Toujours dire pourquoi** (risque `caution` correspondant).
- **no_go** : un no-go absolu, un seuil du niveau dépassé, ou score < 45.
- **`difficulty` du plan** = max(difficulté du site, plus petit niveau dont tous les seuils §2 passent, niveau mini du type de vol : cross ≥ intermediate, distance libre ≥ expert, triangle FAI ≥ advanced). Si `difficulty` > niveau demandé → plan rejeté (raison : « conditions trop fortes pour ton niveau, OK pour brevet confirmé »).
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
8. **Inventer un atterrissage** dans un champ quelconque : seuls les atterros officiels/identifiés comptent.
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
gust_factor_max:             {beginner: 1.4, intermediate: 1.5, advanced: 1.6, expert: 1.7}
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
glide_k:                     {beginner: 0.50, intermediate: 0.60, advanced: 0.65, expert: 0.70}
landing_arrival_margin_m:    {beginner: 200, intermediate: 150, advanced: 120, expert: 100}
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
verdict: {go_min_score: 65, go_min_safety_subscore: 50, go_min_confidence: 0.5, nogo_max_score: 45}
weights: {takeoff_wind: 25, wind_aloft: 15, landing: 15, thermal_match: 15, duration_match: 10, convective_stability: 10, data_confidence: 5, site_fit: 5}
horizon_beacon_weight: {"30m": 0.7, "1h": 0.5, "2h": 0.3, "8h": 0.1, "12h": 0, "24h": 0, "48h": 0}
horizon_base_confidence: {"30m": 0.9, "1h": 0.85, "2h": 0.8, "8h": 0.7, "12h": 0.65, "24h": 0.55, "48h": 0.4}
xc_speed_kmh_by_vario:   # vario m/s -> km/h (aile EN-B ; ×1.15 si finesse ≥ 9.5)
  intermediate: {1: 8,  2: 14, 3: 19}
  advanced:     {1: 10, 2: 17, 3: 23, 4: 27}
  expert:       {1: 12, 2: 20, 3: 27, 4: 32, 5: 36}
turnpoint_radius_m: 400
goal_radius_m: 300
```

---

## 12. Résumé pour le développeur backend (10 lignes)

1. **Filtrer d'abord, scorer ensuite** : un seul no-go (§3) ou un seuil du niveau dépassé (§2) élimine le plan ; le score ne compense jamais la sécurité (`score ≤ 40 + min sous-score sécurité`).
2. **Vent au déco = vent interpolé à l'altitude réelle du déco**, moyenne/max sur 10 min pour les balises ; écart angulaire calculé par rapport au secteur `orientations` le plus proche.
3. **Le faux calme tue** : vent ≥ 15 km/h au niveau de la crête venant de l'arrière du déco = no-go, même si la balise du déco affiche une brise favorable.
4. **L'atterro se juge à l'heure d'arrivée**, avec la brise de vallée (×1,3 sur AROME entre 13h et 17h dans les grandes vallées) et une finesse de calcul sol = polaire × k(niveau) × (V_air + vent arrière)/V_air.
5. **Toujours un atterro identifié dans le cône de finesse**, vérifié tous les 500 m de route avec le profil de terrain ; publier l'altitude de sécurité = points de décision.
6. **Fenêtre thermique en heure solaire** selon saison (§4.1) et orientation de face (§4.2) ; créneau fermé par `min(convection_end, surdév − 1 h, coucher − 30 min)`.
7. **Routes de cross** : face au vent d'abord, points sur faces ensoleillées à l'ETA, transitions au plus étroit, jamais sous le vent / en venturi ; `V_eff = V_xc − W²/V_xc` en circuit fermé.
8. **Espaces aériens en 3D** convertis en AMSL, plafond FL115 (~3500 m), R/ZRT au statut inconnu = caution ; parcs nationaux, réserves et zones rapaces = zones à éviter.
9. **Pondération balises/modèles décroissante avec l'horizon** (0,7 à 30 min → 0 à 12 h) et confiance = base(horizon) × dispersion inter-modèles × cohérence balises ; mode mock affiché en clair.
10. **La `difficulty` du plan = le plus petit niveau dont tous les seuils passent** (et ≥ difficulté du site / du type de vol) ; diversifier les résultats (≤ 2 plans par déco) et expliquer chaque `marginal`.
