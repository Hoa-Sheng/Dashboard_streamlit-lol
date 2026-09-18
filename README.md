# ⚔️ Ban ou pick ? Ce que cache la méta

Dashboard Streamlit sur la méta de la saison 12 de League of Legends, réalisé
dans le cadre du cours *Dashboards & Data Visualisation* (MD4). Le cadrage complet (message, audience, KPIs) est détaillé dans
[cadrage.md](cadrage.md).

**Message clé** : sur la saison 12, être Tier S/SS ou très banni ne veut pas
dire gagner plus souvent. Le ban rate reflète la peur ou la popularité d'un
champion, pas sa force réelle : la régulation naturelle du pick/ban ramène
presque tous les champions autour de 50 % de victoires.

## Aperçu du dashboard

- **En-tête** : titre et phrase d'accroche calculée sur le patch choisi
  (part de champions Tier S/SS, écart de win rate entre le tier le plus
  faible et le plus fort).
- **Filtres (sidebar)** : rôle, tier, patch — appliqués à tous les onglets.
- **📊 Vue d'ensemble** (accueil)
  - texte de bienvenue qui présente la question et chaque onglet ;
  - 3 chiffres clés : win rate moyen de la sélection (vs moyenne de la
    saison), nombre de champions analysés, champion le plus joué ;
  - nuage de points win rate / ban rate (taille = pick rate, couleur = tier)
    et corrélation entre les deux ;
  - nombre de champions dans chaque tier.
- **🏆 Classements**
  - *Le champion le plus craint* et *le moins craint mais redoutable* (n°1 de
    chaque classement) ;
  - **Très bannis… mais ils perdent** : champions sous 50 % de victoires,
    triés du plus banni au moins banni ;
  - **Ils gagnent le plus… et presque personne ne les bannit** : champions
    moins bannis que la médiane de la sélection, triés par win rate ;
  - barres Win % (toujours vert) et Ban % (toujours rouge), icônes des
    4 premiers.
- **🗂️ Tier liste** : tous les champions du patch rangés de SS à D, triés
  par score dans chaque tier. Chaque case (photo, nom, rôle) est cliquable et
  ouvre le profil du champion.
- **🧑‍🎤 Profil champion**
  - portrait, tier, tendance, classe et verdict craint / sous-coté ;
  - 5 indicateurs (Win rate, Pick rate, Ban rate, KDA, Score) comparés à la
    moyenne du rôle ; un bouton sous chaque indicateur choisit la courbe ;
  - courbe de l'indicateur choisi sur les 23 patchs, avec la moyenne du rôle
    en pointillés.
- **📖 Lexique** : les termes techniques du dashboard (statistiques,
  classement, jeu, rôles, classes) avec traduction et définition simple.

## Structure du projet

```
Projet lol/
├── app.py                     # Dashboard Streamlit (point d'entrée)
├── data/                      # 23 CSV, un par patch (12.1 à 12.23)
├── .streamlit/
│   └── config.toml            # Thème visuel (palette, police)
├── cadrage.md                 # Document de cadrage (livrable du brief)
├── requirements.txt
└── README.md
```

## Installation

```bash
python -m venv env
# Windows
env\Scripts\activate
# macOS / Linux
source env/bin/activate

pip install -r requirements.txt
```

Streamlit **1.64 ou plus récent** est nécessaire (onglets pilotables par le
code, conteneurs horizontaux, `st.table` sans index).

## Lancer le dashboard

```bash
streamlit run app.py
```

Les données sont déjà présentes dans `data/` : chiffres, filtres et
graphiques fonctionnent hors-ligne. Seuls les portraits de champions ont
besoin d'une connexion internet ; sans réseau, le dashboard reste utilisable,
avec des cases sans image.

## Données

- **Source** : [League of Legends Champion Stats](https://www.kaggle.com/datasets/vivovinco/league-of-legends-champion-stats)
  (Kaggle, auteur *vivovinco*), licence MIT.
- **Contenu** : un fichier CSV par patch de la saison 12 (12.1 à 12.23).
  Chaque ligne décrit un champion dans un rôle donné (`Name`, `Class`,
  `Role`, `Tier`, `Score`, `Trend`, `Win %`, `Role %`, `Pick %`, `Ban %`,
  `KDA`).
- **Préparation** (dans `load_data`, mise en cache avec `@st.cache_data`) :
  - les pourcentages texte (`"49.97%"`) sont convertis en nombres ;
  - le tier `God` de la source est renommé **SS** ;
  - **off-roles** : pour un champion joué dans plusieurs rôles sur un même
    patch, un rôle à moins de 1 % de pick est marqué `off_role` (win rate
    peu fiable). Si tous ses rôles sont sous 1 %, le plus joué reste
    principal pour que le champion ne disparaisse pas. Les off-roles sont
    exclus de toutes les vues sauf le profil champion. Seuil réglable :
    `MIN_PICK_MULTI_ROLE`.
  - `fear_gap` : rang percentile du ban rate − rang percentile du win rate,
    par patch. Sert au verdict « craint / sous-coté » du profil champion.
  - `trend_label` : traduction lisible (↑ / → / ↓) de la colonne `Trend`.
- **Images des champions** : chargées depuis [Community Dragon](https://www.communitydragon.org/)
  (ressource communautaire basée sur les fichiers officiels Riot), sans clé
  API.

**Limites connues** : `Score`, `Tier` et `Trend` sont calculés par la source
selon une méthode non publiée ; la granularité est « champion × rôle », donc
un champion multi-rôles compte plusieurs fois dans les totaux.

## Choix techniques

- **Un seul fichier `app.py`**, organisé en fonctions par responsabilité
  (chargement, graphiques, un `render_…_tab` par onglet).
- **Couleurs constantes** : Win % toujours en vert, Ban % toujours en rouge ;
  les tiers suivent une seule teinte dorée (rappelant le jeu), de plus en plus foncée du D au SS.
- **Classements sur les pourcentages réels** plutôt qu'un score calculé :
  la règle de tri se lit dans le titre de chaque graphique.
- **Page « Profil champion » dynamique** plutôt que 160+ pages statiques :
  un sélecteur parcourt tous les champions avec le même gabarit. La liste
  couvre toute la saison pour que la sélection survive au changement de patch.
- **Onglets avec clé (`st.tabs(key=…, on_change="rerun")`)** : un clic dans
  la tier liste sélectionne le champion et bascule sur son profil.
- **CSS ciblé** via les clés de conteneur (`.st-key-…`) uniquement là où
  Streamlit ne suffit pas : centrage des chiffres clés, cases de la tier
  liste, retour à la ligne du lexique.
- **Images via URL directe**, affichées par le navigateur : pas de stockage
  local de 160+ images.
