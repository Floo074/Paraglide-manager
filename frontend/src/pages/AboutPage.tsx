import { Link } from "react-router-dom";
import { Disclaimer } from "../components/layout/Disclaimer";
import { Card } from "../components/ui/Card";
import { DIFFICULTIES } from "../config/labels";
import { LANDING_WIND_MAX, RIDGE_WIND_MAX, TAKEOFF_GUST_MAX, TAKEOFF_WIND_MAX, WIND_ALOFT_MAX } from "../config/thresholds";

export function AboutPage() {
  return (
    <div className="page page--narrow prose">
      <h1>À propos et méthode</h1>
      <Disclaimer />
      <Card title="À quoi sert Paraglide Manager ?">
        <p>
          Pour une zone choisie sur la carte (ou un décollage libre posé sur la carte) et un horizon (15 min à 48 h), l'outil propose les vols les plus adaptés à ton niveau et à tes envies, avec un
          briefing complet, la carte des conditions et les fichiers GPX / XCTrack. Il croise ce que les outils existants séparent : <em>site</em> (orientations,
          consignes) × <em>vent au déco à l'heure du vol</em> × <em>aérologie</em> (fenêtre thermique, plafond, surdéveloppement) × <em>brise à l'atterro à
          l'arrivée</em> × <em>niveau du pilote</em> × <em>espaces aériens et zones sensibles</em>.
        </p>
      </Card>
      <Card title="Comment les plans sont calculés">
        <ol>
          <li>
            <strong>Candidats</strong> : décollages de la zone et leurs atterrissages associés.
          </li>
          <li>
            <strong>Météo à l'heure cible</strong> (maintenant + horizon) : modèles AROME, ICON-D2, ECMWF ; vent interpolé à l'altitude réelle du déco ; plafond,
            base, vario. Jusqu'à 2 h, correction par les balises rattachées au déco et à l'atterro (nowcasting, tendance sur 1 h) ; jusqu'à 1 h,
            les « Balises en direct » passent en tête de la fiche.
          </li>
          <li>
            <strong>Décollage libre</strong> (vol rando) : point choisi sur la carte, altitude et orientation déduites du relief si besoin ; recherche des
            atterrissages dans le cône de finesse (vent compris) parmi les officiels, puis, si tu l'acceptes, les atterros communautaires et les champs
            détectés. Les atterrissages non officiels sont à repérer et l'autorisation du propriétaire est à vérifier ; jamais proposés aux élèves.
          </li>
          <li>
            <strong>Filtres de sécurité d'abord</strong> : pluie, orage, vent hors limites, vent de travers ou arrière, dévent, base trop basse, vent fort en
            altitude, coucher du soleil, site fermé, espace aérien… Un seul critère suffit à écarter un vol : la liste « Pourquoi pas ces sites ? » l'explique.
          </li>
          <li>
            <strong>Routage</strong> : plouf, local thermique, soaring ou cross (premier côté face au vent), en restant dans le cône de finesse d'un atterrissage
            identifié, avec une finesse de calcul prudente selon le niveau.
          </li>
          <li>
            <strong>Score non compensatoire</strong> : un bon score thermique ne rattrape jamais un vent au déco limite (le score est plafonné à 40 + le plus faible
            des critères de sécurité). Verdict GO / LIMITE / NO-GO et niveau de confiance (qui baisse avec l'horizon).
          </li>
          <li>
            <strong>Briefing</strong> dans l'ordre d'un moniteur : verdict, créneau, situation, vent, aérologie, décollage, itinéraire, atterrissage, espaces
            aériens, risques, logistique.
          </li>
        </ol>
        <p className="small muted">Les heures sont affichées en heure légale française (Europe/Paris) ; les règles aérologiques sont calculées en heure solaire.</p>
      </Card>
      <Card title="Niveaux et seuils de vent par défaut">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Niveau</th>
                <th className="num">Déco moy./raf.</th>
                <th className="num">Soaring max</th>
                <th className="num">1500 / 2000 / 3000 m</th>
                <th className="num">Atterro</th>
              </tr>
            </thead>
            <tbody>
              {DIFFICULTIES.map((d) => (
                <tr key={d.value}>
                  <td>
                    <strong>{d.label}</strong>
                    <div className="tiny faint">{d.description}</div>
                  </td>
                  <td className="num nowrap">
                    {TAKEOFF_WIND_MAX[d.value]} / {TAKEOFF_GUST_MAX[d.value]}
                  </td>
                  <td className="num">{RIDGE_WIND_MAX[d.value]}</td>
                  <td className="num nowrap">
                    {WIND_ALOFT_MAX[1500][d.value]} / {WIND_ALOFT_MAX[2000][d.value]} / {WIND_ALOFT_MAX[3000][d.value]}
                  </td>
                  <td className="num">{LANDING_WIND_MAX[d.value]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">
          km/h. Couleurs sur la carte et dans les fiches : vert sous 80 % du seuil de ton niveau, orange entre 80 et 100 %, rouge au-delà. Seuils réglables côté
          serveur.
        </p>
      </Card>
      <Card title="Règles de priorité (rappel)">
        <ul>
          <li>Croisement face à face : chacun s'écarte vers la droite.</li>
          <li>Le long d'une pente : priorité au pilote qui a la pente à sa droite ; on ne dépasse jamais entre un pilote et le relief.</li>
          <li>En thermique : le premier entré donne le sens de rotation.</li>
          <li>Pilote le plus bas / en approche finale prioritaire. Pas de vol dans les nuages : 300 m sous la base, 1,5 km des nuages.</li>
        </ul>
      </Card>
      <Card title="Données et licences">
        <ul>
          <li>Prévisions : Open-Meteo (AROME France HD, ICON-D2, ECMWF IFS), altitude Open-Meteo.</li>
          <li>Sites : ParaglidingEarth (et autres sources configurées côté serveur) ; balises : © contributeurs OpenWindMap / Pioupiou.</li>
          <li>Espaces aériens : OpenAIP ou fichiers OpenAir locaux ; zones sensibles : Biodiv'Sports, cœurs de parcs nationaux.</li>
          <li>Fonds de carte : © contributeurs OpenStreetMap, OpenTopoMap (CC-BY-SA), imagerie Esri World Imagery.</li>
          <li>Hotspots thermiques (option) : thermal.kk7.ch (CC BY-NC-SA 4.0).</li>
        </ul>
        <p className="small">
          L'état de chaque source est visible sur la page <Link to="/sources">Sources & statut</Link>.
        </p>
      </Card>
      <Card title="Limites">
        <p>
          Les modèles lissent le relief et sous-estiment les brises ; les balises peuvent être mal exposées ; les activations d'espaces aériens (NOTAM, SUP AIP,
          AZBA) ne sont pas toujours connues. L'outil ne voit ni le ciel, ni la manche à air, ni les autres ailes : la décision finale t'appartient, sur place.
        </p>
      </Card>
    </div>
  );
}
