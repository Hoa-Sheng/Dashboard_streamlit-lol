# Document de cadrage — Dashboard Méta League of Legends

*MD4 — Dashboards & Data Visualisation*

**Titre du dashboard** : ⚔️ Ban ou pick ? Ce que cache la méta

## Message clé

> Être Tier S/SS ou très banni ne veut pas dire gagner plus souvent : sur la
> saison 12, les champions Tier D gagnent en moyenne 47,7 % de leurs parties
> et les Tier SS 50,5 %, soit un écart d'environ 3 points (entre 2,4 et
> 4,3 points selon le patch). La corrélation entre ban rate et win rate est
> nulle (≈ 0,00 sur la saison, entre −0,11 et +0,07 selon le patch).

Le tier et le ban rate mesurent la **pression perçue** d'un champion (peur,
popularité), pas sa probabilité réelle de victoire : le pick/ban des joueurs
ramène presque tout le monde vers 50 %.

## Audience cible

Des **joueurs classés (ranked)** qui préparent leur stratégie de pick/ban en
phase de draft, et qui ont tendance à se fier aux tier listes ou au ban rate
communautaire pour juger la force d'un champion. Le dashboard ne suppose pas
de maîtriser le vocabulaire : un onglet **Lexique** traduit et définit chaque
terme technique.

## KPIs retenus

| KPI | Où ? | Vanity ou actionable ? | Justification |
|---|---|---|---|
| Win rate moyen de la sélection, comparé à la moyenne de la saison | Vue d'ensemble | **Actionable** | Dit si le rôle/tier filtré est réellement favorable *ce patch-ci* — utile pour composer une équipe. |
| Champion le plus craint (le plus banni parmi ceux sous 50 % de victoires) | Classements | **Actionable** | Évite de bannir « par réflexe » un champion redouté mais qui perd — un ban est une ressource limitée en draft. |
| Champion le moins craint mais redoutable (meilleur win rate parmi les moins bannis) | Classements | **Actionable** | Signale un pick sûr que l'adversaire ne pense pas à bannir. |
| Champion le plus joué | Vue d'ensemble | Contexte | Situe la popularité : le plus joué n'est ni le plus banni ni le plus gagnant. |
| Champions analysés | Vue d'ensemble | Vanity (assumé) | Ne guide aucune décision, mais indique sur combien de lignes portent les chiffres après filtrage. |

Les deux KPIs de contexte sont volontairement placés à côté du win rate
moyen, en appui, et non mis en avant comme des indicateurs de décision.

## Règles de calcul

- **Classements** : règles simples sur les pourcentages réels du patch,
  lisibles directement dans le titre des graphiques.
  - *Très bannis… mais ils perdent* : Win % < 50, tri par Ban % décroissant.
  - *Ils gagnent… sans être bannis* : Ban % sous la médiane de la sélection,
    tri par Win % décroissant.
- **Off-roles** : sur un patch, un rôle secondaire joué dans moins de 1 % des
  parties est exclu des vues (win rate peu fiable, doublon), sauf dans le
  profil champion où il reste consultable avec un avertissement.
- **Tier SS** : correspond au tier « God » de la source, renommé pour s'adapter à un nom plus "neutre".

## Choix d'interaction — sélecteurs du profil champion

Le profil champion se pilote avec deux sélecteurs (champion, puis rôle) qui
doivent rester cohérents quand l'utilisateur déplace le curseur de patch.
Trois problèmes se posaient, avec les réponses retenues.

**1. La sélection était perdue à chaque changement de patch.** Streamlit
identifie un menu par ses paramètres : si la liste des options change, il le
considère comme un nouveau menu et revient au premier élément. La liste des
champions, construite patch par patch, changeait donc en permanence. Elle
couvre désormais toute la saison et ne bouge plus ; le filtre par patch est
appliqué après, sur les données. Si le champion choisi n'existe pas sur le
patch affiché, un message le signale à la place de la fiche.

**2. Les off-roles n'étaient proposés nulle part.** Ils étaient supprimés au
chargement. Ils sont maintenant marqués (colonne `off_role`) au lieu d'être
retirés : seul le profil champion reçoit les données complètes, les autres
onglets gardent la version filtrée. Dans le sélecteur de rôle, le rôle
principal vient en premier, les off-roles ensuite, signalés par la mention
« (off-role) » et par une infobulle qui rappelle le seuil de 1 %. Choisir un
off-role affiche un avertissement avec son pick rate exact, car ses
statistiques reposent sur peu de parties.

**3. Le rôle choisi devait survivre au changement de patch.** Les rôles
disponibles varient d'un patch à l'autre, ce qui recrée le sélecteur. Le
dernier rôle choisi est donc mémorisé et réappliqué s'il existe encore ;
sinon, la fiche repart du rôle principal.

**Comparaisons.** Les écarts affichés sous chaque indicateur (« −2,4 vs
SUPPORT ») et la courbe de référence sont calculés sans les off-roles, même
quand la fiche en affiche un : la comparaison reste ainsi cohérente avec le
reste du dashboard.

## Structure

- **En-tête** — titre et phrase d'accroche chiffrée sur le patch sélectionné.
- **Zone filtres** (sidebar) — Rôle, Tier, Patch : appliqués à tous les onglets.
- **Zone détail**, organisée en 5 onglets :
  1. *📊 Vue d'ensemble* (accueil) — présentation du dashboard, 3 chiffres
     clés, nuage de points Win % / Ban % (le graphique qui porte le message)
     et répartition des champions par tier.
  2. *🏆 Classements* — champion le plus craint / le moins craint, puis les
     deux classements en barres Win % (vert) et Ban % (rouge), avec portraits.
  3. *🗂️ Tier liste* — tous les champions rangés de SS à D ; chaque case
     (photo, nom, rôle) ouvre le profil du champion.
  4. *🧑‍🎤 Profil champion* — sélecteur de champion et de rôle (off-roles
     compris), portrait, 5 indicateurs comparés à la moyenne du rôle, chacun
     avec un bouton qui affiche sa courbe sur les 23 patchs.
  5. *📖 Lexique* — termes techniques avec traduction, définition et recherche.

## Parcours utilisateur type

1. L'accueil pose la question et montre, sur le nuage de points, que ban
   rate et win rate ne sont pas liés.
2. Les Classements donnent les noms concrets : qui ne pas bannir par
   réflexe, quel pick sûr exploiter.
3. La Tier liste permet de comparer avec la perception « officielle », puis
   d'ouvrir d'un clic le profil d'un champion.
4. Le Profil champion vérifie dans le détail, rôle par rôle et patch par
   patch.
5. Le Lexique est disponible à tout moment pour un terme inconnu.
