from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #

DATA_DIR = Path(__file__).parent / "data"
PATCH_FILE_PATTERN = re.compile(r"Stats 12\.(\d+)\.csv$")

# Ordres "métier" (pas alphabétiques) pour que filtres, légendes et axes
# restent dans un ordre qui a du sens pour un joueur.
TIER_ORDER = ["D", "C", "B", "A", "S", "SS"]
ROLE_ORDER = ["TOP", "JUNGLE", "MID", "ADC", "SUPPORT"]

# Palette : une seule teinte (or, discret clin d'œil LoL) déclinée en
# intensité croissante avec le tier. Un seul canal de couleur à lire,
# cohérent avec le principe de hiérarchie visuelle vu en cours.
TIER_COLORS = {
    "D": "#E7E1D3",
    "C": "#D8C69A",
    "B": "#C9A968",
    "A": "#B8862E",
    "S": "#8C6522",
    "SS": "#5C4116",
}

COLOR_FEARED = "#922B21"      # champion craint / surcoté
COLOR_UNDERRATED = "#1A5276"  # champion sous-coté / à exploiter
COLOR_NEUTRAL = "#5B5A56"
COLOR_WIN = "#1E8449"          # victoires : toujours vert
COLOR_BAN = "#C0392B"          # bans : toujours rouge

# Rôles secondaires d'un champion multi-rôles retirés sous ce pick rate (%)
MIN_PICK_MULTI_ROLE = 1.0

PROFILE_TAB = "🧑‍🎤 Profil champion"

# Images des champions : Community Dragon (ressource communautaire basée sur
# les fichiers officiels Riot, cf. cadrage). Aucune clé API requise.
CHAMPION_SUMMARY_URL = (
    "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/"
    "global/default/v1/champion-summary.json"
)
# Notre dataset et Community Dragon nomment ce champion différemment ;
# tous les autres noms correspondent exactement d'une source à l'autre.
CHAMPION_NAME_ALIASES = {"Nunu": "Nunu & Willump"}


# --------------------------------------------------------------------------- #
# Chargement & préparation des données (exécuté une seule fois grâce au cache)
# --------------------------------------------------------------------------- #

@st.cache_data(show_spinner="Chargement des 23 patchs de la saison 12…")
def load_data(data_dir: Path) -> pd.DataFrame:
    """Charge tous les CSV de patch, les nettoie et ajoute les colonnes dérivées.

    Chaque fichier `League of Legends Champion Stats 12.X.csv` correspond à
    un patch. Une ligne = un champion dans un rôle donné (les champions
    multi-rôles, ex. Akali TOP/MID, apparaissent donc plusieurs fois).
    """
    frames = []
    for csv_path in sorted(data_dir.glob("*.csv")):
        match = PATCH_FILE_PATTERN.search(csv_path.name)
        if not match:
            continue
        # Le numéro de patch est gardé en entier (1, 2, ..., 10, ..., 23) et
        # non converti en flottant : 12.1 et 12.10 donneraient sinon la même
        # valeur (12.1) et fusionneraient deux patchs différents.
        patch_num = int(match.group(1))
        frame = pd.read_csv(csv_path, sep=";")
        frame["patch_num"] = patch_num
        frames.append(frame)

    df = pd.concat(frames, ignore_index=True)
    df["Patch"] = "12." + df["patch_num"].astype(str)

    # Les taux sont fournis en texte ("49.97%") -> conversion en float exploitable
    for col in ["Win %", "Role %", "Pick %", "Ban %"]:
        df[col] = df[col].astype(str).str.rstrip("%").astype(float)

    # La source nomme « God » le tier le plus haut ; renommé SS, plus usuel.
    df["Tier"] = df["Tier"].replace({"God": "SS"})
    df["Tier"] = pd.Categorical(df["Tier"], categories=TIER_ORDER, ordered=True)
    df["Role"] = pd.Categorical(df["Role"], categories=ROLE_ORDER, ordered=True)
    df["label"] = df["Name"] + " (" + df["Role"].astype(str) + ")"

    # Champions multi-rôles : patch par patch, un rôle joué dans moins de 1 %
    # des parties est marqué « off-role » (win rate peu fiable, doublon). Si tous
    # les rôles d'un champion sont sous 1 %, son rôle le plus joué reste principal
    # pour qu'il ne disparaisse pas du patch. Les off-roles sont exclus de toutes
    # les vues sauf le profil champion, où l'on peut les consulter.
    per_champion = df.groupby(["patch_num", "Name"])["Pick %"]
    is_multi_role = per_champion.transform("size") >= 2
    is_main_role = df["Pick %"] == per_champion.transform("max")
    df["off_role"] = is_multi_role & (df["Pick %"] < MIN_PICK_MULTI_ROLE) & ~is_main_role

    # --- Colonnes dérivées ---
    # Rang percentile (0-100) par patch : place chaque champion par rapport
    # aux autres champions du même patch, sur une échelle comparable.
    df["ban_rank_pct"] = df.groupby("patch_num")["Ban %"].rank(pct=True) * 100
    df["win_rank_pct"] = df.groupby("patch_num")["Win %"].rank(pct=True) * 100

    # fear_gap > 0 : banni bien plus que son win rate ne le justifie (il fait
    # peur). fear_gap < 0 : gagne beaucoup sans qu'on s'en méfie (pick sûr,
    # sous le radar). C'est la mesure centrale du message du dashboard.
    df["fear_gap"] = df["ban_rank_pct"] - df["win_rank_pct"]

    # Trend (fourni par la source, non documenté en unité) -> tendance lisible
    df["trend_label"] = pd.cut(
        df["Trend"],
        bins=[-float("inf"), -2, 2, float("inf")],
        labels=["↓", "→", "↑"],
    )

    return df


@st.cache_data(show_spinner=False, ttl=3600)
def load_champion_ids() -> dict[str, int]:
    """Associe chaque nom de champion à son id .

    Sert uniquement à construire les URLs d'images.
    """
    try:
        response = requests.get(CHAMPION_SUMMARY_URL, timeout=5)
        response.raise_for_status()
        entries = response.json()
    except (requests.RequestException, ValueError):
        return {}
    return {entry["name"]: entry["id"] for entry in entries if 0 < entry["id"] < 10000}


def champion_image_url(name: str, image_ids: dict[str, int], variant: str = "square") -> str | None:
    """URL publique de l'image d'un champion, ou None si introuvable / hors-ligne.

    `variant` : "square" (icône, listes/classements) ou "splash-art/centered"
    (portrait large, page profil).
    """
    champion_id = image_ids.get(CHAMPION_NAME_ALIASES.get(name, name))
    if champion_id is None:
        return None
    return f"https://cdn.communitydragon.org/latest/champion/{champion_id}/{variant}"


# --------------------------------------------------------------------------- #
# Petits utilitaires
# --------------------------------------------------------------------------- #

def base_scatter_figure(df: pd.DataFrame, title: str) -> go.Figure:
    """Nuage de points Win% / Ban%, cœur visuel du message du dashboard."""
    fig = px.scatter(
        df,
        x="Win %",
        y="Ban %",
        size="Pick %",
        color="Tier",
        category_orders={"Tier": TIER_ORDER},
        color_discrete_map=TIER_COLORS,
        hover_name="label",
        hover_data={"Win %": ":.1f", "Ban %": ":.1f", "Pick %": ":.1f", "Tier": True},
        title=title,
        template="plotly_white",
    )
    fig.add_vline(
        x=50, line_dash="dot", line_color=COLOR_NEUTRAL,
        annotation_text="50 % de victoires", annotation_position="top left",
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=60, b=10),
        legend_title_text="Tier",
        font_family="sans-serif",
    )
    return fig


# --------------------------------------------------------------------------- #
# Mise en page Streamlit
# --------------------------------------------------------------------------- #

def render_sidebar(df: pd.DataFrame) -> tuple[list[str], list[str], int]:
    st.sidebar.header("⚔️ Filtres")

    roles = st.sidebar.multiselect(
        "Rôle", options=ROLE_ORDER, default=ROLE_ORDER,
        help="Filtre appliqué à toutes les vues du dashboard.",
    )

    tiers = st.sidebar.multiselect(
        "Tier", options=TIER_ORDER, default=TIER_ORDER,
        help="S et SS concentrent les champions jugés les plus puissants par la source.",
    )

    patch_options = sorted(df["patch_num"].unique())
    patch_num = st.sidebar.select_slider(
        "Patch (saison 12)",
        options=patch_options,
        value=patch_options[-1],
        format_func=lambda n: f"12.{n}",
        help="Patch analysé dans les KPI, la vue d'ensemble et les classements.",
    )

    st.sidebar.caption(
        "La vue **Évolution de la saison** ignore ce curseur : elle affiche "
        "les 23 patchs pour montrer une tendance dans le temps."
    )

    return roles, tiers, patch_num


def render_header(df_patch_role: pd.DataFrame, patch_num: int) -> None:
    n_champs = len(df_patch_role)
    top_tier_share = (df_patch_role["Tier"].isin(["S", "SS"]).mean() * 100) if n_champs else 0
    win_rate_span = (
        df_patch_role.groupby("Tier", observed=True)["Win %"].mean().max()
        - df_patch_role.groupby("Tier", observed=True)["Win %"].mean().min()
    ) if n_champs else 0

    st.title("⚔️ Ban ou pick ? Ce que cache la méta")
    st.caption(
        f"Méta League of Legends — saison 12, patch **12.{patch_num}**. "
        f"{top_tier_share:.0f}% des champions affichés sont Tier S ou SS, "
        f"alors que l'écart de win rate moyen entre le tier le plus faible et "
        f"le plus fort n'est que de **{win_rate_span:.1f} points**."
    )


def render_overview_tab(df_scope: pd.DataFrame, df_season_role: pd.DataFrame, patch_num: int) -> None:
    st.markdown(
        """
**Bienvenue !** Ce dashboard analyse la méta de la saison 12 de League of Legends
pour répondre à une question simple : *les champions que tout le monde bannit
sont-ils vraiment ceux qui gagnent le plus ?*

- **🏆 Classements** : les champions très bannis qui perdent, et ceux qui
  gagnent sans être bannis.
- **🗂️ Tier liste** : tous les champions du patch, rangés de SS à D.
- **🧑‍🎤 Profil champion** : la fiche détaillée d'un champion et son historique.

Utilisez les filtres à gauche (rôle, tier, patch) : toutes les vues se mettent à jour.
"""
    )

    if df_scope.empty:
        st.warning("Aucun champion ne correspond à cette combinaison de filtres.")
        return

    most_picked = df_scope.loc[df_scope["Pick %"].idxmax()]
    scope_wr = df_scope["Win %"].mean()
    season_wr = df_season_role["Win %"].mean() if len(df_season_role) else float("nan")
    # Chiffres clés centrés dans leur colonne : bloc centré (horizontal_alignment)
    # + texte centré à l'intérieur (CSS limité à ce conteneur via sa clé).
    st.markdown(
        """<style>
        .st-key-overview_kpis [data-testid="stMetric"],
        .st-key-overview_kpis [data-testid="stMetric"] > div,
        .st-key-overview_kpis [data-testid="stMetricLabel"],
        .st-key-overview_kpis [data-testid="stMetricValue"],
        .st-key-overview_kpis [data-testid="stMetricDelta"] {
            justify-content: center; text-align: center; align-items: center;
        }
        </style>""",
        unsafe_allow_html=True,
    )
    kpis = [
        dict(
            label="Win rate moyen (sélection)",
            value=f"{scope_wr:.1f} %",
            delta=f"{scope_wr - season_wr:+.1f} pts vs moyenne saison",
            help="Moyenne du filtre actuel comparée à la moyenne de la saison entière pour les mêmes rôles.",
        ),
        dict(
            label="Champions analysés", value=len(df_scope),
            help="Une ligne = un champion dans un rôle (un champion multi-rôles compte plusieurs fois).",
        ),
        dict(
            label="🎮 Le plus joué", value=most_picked["label"],
            delta=f"{most_picked['Pick %']:.1f} % de pick", delta_color="off",
        ),
    ]
    with st.container(key="overview_kpis"):
        for col, kpi in zip(st.columns(len(kpis)), kpis):
            with col, st.container(horizontal_alignment="center"):
                st.metric(**kpi, width="content")

    st.divider()
    fig = base_scatter_figure(
        df_scope,
        title=f"Patch 12.{patch_num} — win rate et ban rate ne racontent pas la même histoire",
    )
    st.plotly_chart(fig, width="stretch")

    correlation = df_scope["Win %"].corr(df_scope["Ban %"])
    st.success(
        f"**À retenir :** sur cette sélection, la corrélation entre ban rate et "
        f"win rate est de **{correlation:+.2f}** (proche de 0 = quasi nulle). "
        f"La taille des points suit le pick rate : les gros points en bas à droite "
        f"sont les vrais champions forts et populaires, pas ceux du haut du graphique."
    )

    tier_counts = (
        df_scope["Tier"].astype(str).value_counts()
        .reindex(TIER_ORDER[::-1]).dropna().reset_index()
    )
    tier_counts.columns = ["Tier", "Champions"]
    fig = px.bar(
        tier_counts, x="Tier", y="Champions", color="Tier", text="Champions",
        color_discrete_map=TIER_COLORS, template="plotly_white",
        title="Combien de champions dans chaque tier ?",
    )
    fig.update_layout(showlegend=False, xaxis_title="", margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, width="stretch")


def _percentage_ranking_figure(
    df_subset: pd.DataFrame, title: str, emphasis: str
) -> go.Figure:
    """Bar chart horizontal Ban % / Win % en valeurs réelles. Couleurs fixes
    (victoires en vert, bans en rouge) ; l'indicateur qui porte le classement
    est affiché en premier.
    """
    other = "Win %" if emphasis == "Ban %" else "Ban %"
    long_df = df_subset.melt(
        id_vars="label", value_vars=["Ban %", "Win %"],
        var_name="Indicateur", value_name="Valeur",
    )
    fig = px.bar(
        long_df, x="Valeur", y="label", color="Indicateur",
        orientation="h", barmode="group",
        text=long_df["Valeur"].map(lambda v: f"{v:.1f} %"),
        category_orders={"label": df_subset["label"].tolist(), "Indicateur": [emphasis, other]},
        color_discrete_map={"Win %": COLOR_WIN, "Ban %": COLOR_BAN},
        title=title, template="plotly_white",
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(
        xaxis_title="Pourcentage (%)", yaxis_title="", legend_title_text="",
        margin=dict(l=10, r=30, t=50, b=10),
    )
    return fig


def _render_champion_strip(df_subset: pd.DataFrame, image_ids: dict[str, int]) -> None:
    """Petite galerie d'icônes pour reconnaître visuellement les champions du classement."""
    if df_subset.empty:
        return
    cols = st.columns(len(df_subset))
    for col, (_, row) in zip(cols, df_subset.iterrows()):
        with col:
            url = champion_image_url(row["Name"], image_ids)
            if url:
                st.image(url, width=56)
            st.caption(
                f"**{row['Name']}** ({row['Role']})  \n"
                f"{row['Win %']:.1f}% V · {row['Ban %']:.1f}% B"
            )


def render_rankings_tab(df_scope: pd.DataFrame, patch_num: int, image_ids: dict[str, int]) -> None:
    if df_scope.empty:
        st.warning("Aucun champion ne correspond à cette combinaison de filtres.")
        return

    median_ban = df_scope["Ban %"].median()
    st.caption(
        f"Patch 12.{patch_num}, rôles et tiers sélectionnés. Gauche : champions sous "
        f"50 % de victoires, du plus banni au moins banni. Droite : champions bannis "
        f"moins de {median_ban:.1f} % du temps (la médiane de la sélection), du "
        f"meilleur win rate au moins bon."
    )
    top_feared = df_scope[df_scope["Win %"] < 50].nlargest(8, "Ban %")
    top_underrated = df_scope[df_scope["Ban %"] < median_ban].nlargest(8, "Win %")

    col_left, col_right = st.columns(2)
    with col_left:
        if not top_feared.empty:
            feared = top_feared.iloc[0]
            st.metric(
                "Le champion le plus craint",
                feared["label"],
                delta=f"Banni {feared['Ban %']:.1f} % pour {feared['Win %']:.1f} % de victoires",
                delta_color="inverse",
                help="Le plus banni des champions sous 50 % de victoires.",
            )
    with col_right:
        if not top_underrated.empty:
            underrated = top_underrated.iloc[0]
            st.metric(
                "Le champion le moins craint mais redoutable",
                underrated["label"],
                delta=f"{underrated['Win %']:.1f} % de victoires pour {underrated['Ban %']:.1f} % de bans",
                help="Meilleur win rate parmi les champions peu bannis : un pick sûr, sous le radar adverse.",
            )

    with col_left:
        # Tri croissant : Plotly dessine la première catégorie en bas, le n°1 finit donc en haut.
        if top_feared.empty:
            st.info("Aucun champion sous 50 % de victoires dans cette sélection.")
        else:
            fig = _percentage_ranking_figure(
                top_feared.iloc[::-1], "Très bannis… mais ils perdent plus qu'ils ne gagnent",
                emphasis="Ban %",
            )
            st.plotly_chart(fig, width="stretch")
            _render_champion_strip(top_feared.head(4), image_ids)

    with col_right:
        if top_underrated.empty:
            st.info("Aucun champion peu banni dans cette sélection.")
        else:
            fig = _percentage_ranking_figure(
                top_underrated.iloc[::-1], "Ils gagnent le plus… et presque personne ne les bannit",
                emphasis="Win %",
            )
            st.plotly_chart(fig, width="stretch")
            _render_champion_strip(top_underrated.head(4), image_ids)


def open_champion_profile(name: str, role: str) -> None:
    """Callback : sélectionne le champion/rôle et bascule sur l'onglet Profil."""
    st.session_state["profile_champion"] = name
    st.session_state["profile_role"] = role
    st.session_state["main_tab"] = PROFILE_TAB


def _render_tier_card(row: pd.Series, image_ids: dict[str, int]) -> None:
    """Case cliquable d'un champion (photo + nom + rôle) qui ouvre son profil.

    Toute la case est un bouton : son libellé Markdown contient l'image, le nom
    en gras et le rôle en italique, empilés verticalement par le CSS de la tier liste.
    """
    role = str(row["Role"])
    name = row["Name"]
    url = champion_image_url(name, image_ids)
    # Échappe les caractères qui seraient interprétés comme du Markdown.
    safe_name = re.sub(r"([\\`*_\[\]()#+!])", r"\\\1", name)
    image = f"![{safe_name}]({url}) " if url else ""
    st.button(
        f"{image}**{safe_name}** *{role}*",
        key=f"tier_card_{name}_{role}",
        help=f"{row['Win %']:.1f} % V · {row['Ban %']:.1f} % B · {row['Pick %']:.1f} % J. "
             "Cliquer pour ouvrir son profil.",
        on_click=open_champion_profile,
        args=(name, role),
        width=96,
    )


TIER_LIST_CSS = """<style>
.st-key-tier_list button {
    height: 118px; padding: 6px 4px; border-radius: 8px;
}
.st-key-tier_list button p {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 2px; margin: 0; line-height: 1.15; white-space: normal; text-align: center;
}
.st-key-tier_list button img {
    height: 56px !important; width: 56px !important; max-height: none !important;
    border-radius: 6px; margin: 0 0 2px 0;
}
.st-key-tier_list button strong { font-size: 12px; }
.st-key-tier_list button em { font-size: 10px; font-style: normal; opacity: .65; }
/* La case du tier (SS, S…) occupe toute la hauteur de sa ligne. Streamlit
   l'enveloppe dans plusieurs div (avec leurs marges) : on étire la première
   et on y positionne le badge en absolu, les div intermédiaires sont ignorées. */
[class*="st-key-tier_row_"] > div:has(.tier-badge) {
    align-self: stretch !important; position: relative; min-height: 72px;
}
[class*="st-key-tier_row_"] > div div:has(.tier-badge) { position: static; }
.tier-badge {
    position: absolute; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; box-sizing: border-box;
}
</style>"""


def render_tier_list_tab(df_scope: pd.DataFrame, patch_num: int, image_ids: dict[str, int]) -> None:
    """Tier liste façon « tiermaker » : une ligne par tier, du SS au D."""
    if df_scope.empty:
        st.warning("Aucun champion ne correspond à cette combinaison de filtres.")
        return

    st.caption(
        f"Tier liste du patch 12.{patch_num} pour les rôles et tiers sélectionnés, "
        "d'après le tier attribué par la source. Dans chaque tier, les champions "
        "sont triés par score. Survolez une case pour voir ses statistiques, "
        "cliquez dessus pour ouvrir son profil."
    )

    st.markdown(TIER_LIST_CSS, unsafe_allow_html=True)
    tier_list = st.container(key="tier_list")
    for tier in TIER_ORDER[::-1]:
        champions = df_scope[df_scope["Tier"] == tier].sort_values("Score", ascending=False)
        if champions.empty:
            continue
        text_color = "#FFFFFF" if tier in ("A", "S", "SS") else "#2B2B2B"
        with tier_list, st.container(
            border=True, horizontal=True, gap="small", vertical_alignment="center", key=f"tier_row_{tier}"
        ):
            with st.container(width=72, key=f"tier_label_{tier}"):
                st.markdown(
                    f'<div class="tier-badge" style="background:{TIER_COLORS[tier]};color:{text_color};font-weight:700;'
                    'border-radius:6px;text-align:center;padding:10px 10px">'
                    f'<div style="font-size:26px;line-height:1.1">{tier}</div>'
                    f'<div style="font-size:11px">{len(champions)} champ.</div></div>',
                    unsafe_allow_html=True,
                )
            with st.container(horizontal=True, wrap=True, gap="small"):
                for _, row in champions.iterrows():
                    _render_tier_card(row, image_ids)


def render_profile_tab(df: pd.DataFrame, patch_num: int, image_ids: dict[str, int]) -> None:
    """Page dynamique « un champion, une histoire » : un sélecteur remplace ici
    ce qui serait 160+ pages statiques quasi identiques — plus simple à
    maintenir et cohérent avec l'usage habituel de Streamlit.
    """
    df_patch = df[df["patch_num"] == patch_num]
    # Liste fixe (toute la saison) + clé : si les options changeaient avec le
    # patch, Streamlit recréerait le widget et la sélection serait perdue.
    champion_names = sorted(df["Name"].unique())
    selected_name = st.selectbox("Choisir un champion", options=champion_names, key="profile_champion")
    champion_rows = df_patch[df_patch["Name"] == selected_name]
    if champion_rows.empty:
        st.info(f"{selected_name} n'apparaît pas dans les données du patch 12.{patch_num}.")
        return

    if len(champion_rows) > 1:
        # Rôle principal (le plus joué) en premier, off-roles ensuite.
        champion_rows = champion_rows.sort_values(["off_role", "Pick %"], ascending=[True, False])
        role_choices = champion_rows["Role"].astype(str).tolist()
        off_roles = set(champion_rows.loc[champion_rows["off_role"], "Role"].astype(str))
        # Les rôles disponibles varient selon le patch : on réapplique le
        # dernier rôle choisi s'il existe encore sur ce patch.
        previous_role = st.session_state.get("profile_role")
        default_index = role_choices.index(previous_role) if previous_role in role_choices else 0
        selected_role = st.radio(
            "Rôle", options=role_choices, index=default_index, horizontal=True,
            format_func=lambda r: f"{r} (off-role)" if r in off_roles else r,
            help="Off-role : rôle secondaire joué dans moins de "
                 f"{MIN_PICK_MULTI_ROLE:g} % des parties, absent des autres onglets.",
        )
        st.session_state["profile_role"] = selected_role
        row = champion_rows[champion_rows["Role"].astype(str) == selected_role].iloc[0]
    else:
        row = champion_rows.iloc[0]

    if row["off_role"]:
        st.warning(
            f"**Off-role** : {row['Name']} n'est joué {row['Role']} que dans "
            f"{row['Pick %']:.2f} % des parties. Ces statistiques reposent sur peu "
            "de parties et sont à prendre avec prudence."
        )

    # Moyennes de référence calculées sans les off-roles, comme dans le reste du dashboard.
    df_patch_main = df_patch[~df_patch["off_role"]]
    role_avg = df_patch_main[df_patch_main["Role"] == row["Role"]].mean(numeric_only=True)

    image_col, info_col = st.columns([1, 2])
    with image_col:
        splash_url = champion_image_url(selected_name, image_ids, variant="splash-art/centered")
        if splash_url:
            st.image(splash_url, width="stretch")
        else:
            st.info("🖼️ Image indisponible (nécessite une connexion internet).")

    with info_col:
        st.subheader(f"{row['Name']} — {row['Role']}")
        class_label = row["Class"] if pd.notna(row["Class"]) else "—"
        st.markdown(
            f"Tier **{row['Tier']}**  ·  Tendance **{row['trend_label']}**  ·  Classe *{class_label}*"
        )

        gap = row["fear_gap"]
        if gap > 15:
            verdict = "banni bien plus que ce que justifie son win rate : ne le bannissez pas les yeux fermés."
        elif gap < -15:
            verdict = "peu banni malgré un bon win rate : un pick sûr, sous le radar adverse."
        else:
            verdict = "banni à peu près à la hauteur de sa force réelle."
        st.write(
            f"Avec **{row['Win %']:.1f}%** de victoires pour **{row['Ban %']:.1f}%** de bans "
            f"(et {row['Pick %']:.1f}% de pick), ce champion est {verdict}"
        )

    st.divider()
    # Chaque indicateur est cliquable : le bouton sous la carte choisit la courbe affichée.
    # (libellé, colonne, unité, couleur de la courbe)
    metrics = [
        ("Win rate", "Win %", "%", COLOR_WIN),
        ("Pick rate", "Pick %", "%", COLOR_NEUTRAL),
        ("Ban rate", "Ban %", "%", COLOR_BAN),
        ("KDA", "KDA", "", COLOR_NEUTRAL),
        ("Score", "Score", "", COLOR_NEUTRAL),
    ]
    selected_column = st.session_state.setdefault("profile_metric", "Win %")
    for col, (label, column, unit, _) in zip(st.columns(len(metrics)), metrics):
        value, avg = row[column], role_avg.get(column)
        is_selected = column == selected_column
        with col:
            delta = f"{value - avg:+.1f} vs {row['Role']}" if pd.notna(avg) else None
            st.metric(label, f"{value:.1f}{unit}", delta=delta, border=is_selected)
            st.button(
                "📈 Courbe affichée" if is_selected else "📈 Voir la courbe",
                key=f"profile_metric_{column}",
                type="primary" if is_selected else "secondary",
                width="stretch",
                on_click=st.session_state.__setitem__, args=("profile_metric", column),
            )

    st.divider()
    label, column, unit, color = next(m for m in metrics if m[1] == selected_column)
    history = (
        df[(df["Name"] == selected_name) & (df["Role"] == row["Role"])]
        .sort_values("patch_num")
    )
    if len(history) > 1:
        # Repère : moyenne du même rôle à chaque patch.
        role_history = (
            df[(df["Role"] == row["Role"]) & ~df["off_role"]].groupby("patch_num")[column].mean()
            .reindex(history["patch_num"])
        )
        fig = go.Figure()
        fig.add_scatter(
            x=history["patch_num"], y=history[column], mode="lines+markers",
            name=selected_name, line=dict(color=color, width=3),
        )
        fig.add_scatter(
            x=role_history.index, y=role_history.values, mode="lines",
            name=f"Moyenne {row['Role']}", line=dict(color=COLOR_NEUTRAL, dash="dot"),
        )
        fig.update_layout(
            title=f"{label} de {selected_name} ({row['Role']}) sur la saison 12",
            template="plotly_white",
            xaxis_title="Patch (12.x)", yaxis_title=f"{label} ({unit})" if unit else label,
            legend_title_text="", margin=dict(l=10, r=10, t=50, b=10),
        )
        st.plotly_chart(fig, width="stretch")
    else:
        st.caption("Ce champion n'apparaît que sur un seul patch de la saison : pas d'historique à afficher.")


TIER_GAP_METRICS = [
    ("Win rate", "Win %", " %"),
    ("Pick rate", "Pick %", " %"),
    ("Ban rate", "Ban %", " %"),
    ("KDA", "KDA", ""),
    ("Score", "Score", ""),
]


def render_tier_gap(df_season_scope: pd.DataFrame) -> None:
    """KPI « tier le plus haut vs tier le plus bas » (SS vs D par défaut) :
    montre que l'écart est énorme en popularité/bans mais minime en victoires.
    """
    present = [t for t in TIER_ORDER if t in set(df_season_scope["Tier"].astype(str))]
    if len(present) < 2:
        st.info("Sélectionnez au moins deux tiers pour comparer le haut et le bas du classement.")
        return
    low, high = present[0], present[-1]

    st.subheader(f"Tier {high} vs Tier {low} — moyenne sur la saison")
    by_tier = df_season_scope.groupby(df_season_scope["Tier"].astype(str)).mean(numeric_only=True)
    cols = st.columns(len(TIER_GAP_METRICS))
    for col, (label, column, unit) in zip(cols, TIER_GAP_METRICS):
        high_val, low_val = by_tier.loc[high, column], by_tier.loc[low, column]
        with col:
            st.metric(
                f"{label} (Tier {high})",
                f"{high_val:.1f}{unit}",
                delta=f"{high_val - low_val:+.1f} vs Tier {low} ({low_val:.1f}{unit})",
                delta_color="off" if column == "Ban %" else "normal",
            )

    # Écart patch par patch, en points : Ban % vs Win % sur le même axe.
    per_patch = (
        df_season_scope[df_season_scope["Tier"].isin([low, high])]
        .groupby(["patch_num", df_season_scope["Tier"].astype(str)])[["Win %", "Ban %", "Pick %"]]
        .mean()
        .unstack("Tier")
    )
    gap = (per_patch.xs(high, axis=1, level="Tier") - per_patch.xs(low, axis=1, level="Tier")).dropna()
    if gap.empty:
        return
    gap_long = gap.reset_index().melt(id_vars="patch_num", var_name="Indicateur", value_name="Écart")
    fig = px.line(
        gap_long, x="patch_num", y="Écart", color="Indicateur", markers=True,
        color_discrete_map={"Ban %": COLOR_FEARED, "Win %": COLOR_UNDERRATED, "Pick %": COLOR_NEUTRAL},
        title=f"Écart Tier {high} − Tier {low} par patch : énorme en bans, minime en victoires",
        template="plotly_white",
    )
    fig.add_hline(y=0, line_dash="dot", line_color=COLOR_NEUTRAL)
    fig.update_layout(
        xaxis_title="Patch (12.x)", yaxis_title=f"Écart {high} − {low} (points de %)",
        legend_title_text="", margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig, width="stretch")


# (catégorie, terme utilisé, traduction française, définition)
GLOSSARY = [
    # --- Statistiques ---
    ("Statistiques", "Win rate (Win %)", "Taux de victoire",
     "Part des parties gagnées par un champion quand il est joué. 50 % = autant de victoires que de défaites."),
    ("Statistiques", "Ban rate (Ban %)", "Taux de bannissement",
     "Part des parties où le champion est banni pendant la draft, donc interdit pour les deux équipes."),
    ("Statistiques", "Pick rate (Pick %)", "Taux de sélection",
     "Part des parties où le champion est choisi par un joueur. Mesure sa popularité."),
    ("Statistiques", "Role %", "Part du rôle",
     "Part des parties du champion jouées dans ce rôle précis (ex. Akali jouée à 70 % au MID)."),
    ("Statistiques", "KDA", "Éliminations / Morts / Assistances",
     "Ratio (éliminations + assistances) ÷ morts. Plus il est élevé, plus le champion contribue sans mourir."),
    ("Statistiques", "Score", "Score de puissance",
     "Note globale calculée par la source (méthode non publiée) ; elle détermine le tier."),
    ("Statistiques", "Trend", "Tendance",
     "Évolution récente du champion selon la source : ↑ en hausse, → stable, ↓ en baisse."),
    ("Statistiques", "Pts (points)", "Points de pourcentage",
     "Écart entre deux pourcentages : passer de 48 % à 50 % = +2 pts."),
    # --- Classement des champions ---
    ("Classement", "Tier", "Rang / palier",
     "Catégorie de puissance d'un champion. Du plus fort au plus faible : SS, S, A, B, C, D."),
    ("Classement", "SS", "Tier le plus haut",
     "Champions jugés les plus puissants du patch (appelé « God » dans la source)."),
    ("Classement", "Tier liste", "Classement par paliers",
     "Tableau qui range tous les champions par tier, du SS au D."),
    ("Classement", "Craint", "Redouté",
     "Champion très banni : les joueurs préfèrent l'interdire plutôt que de l'affronter."),
    ("Classement", "Sous-coté", "Sous-estimé",
     "Champion qui gagne beaucoup mais que presque personne ne bannit."),
    ("Classement", "Pick sûr", "Choix fiable",
     "Champion performant et rarement banni, donc facile à obtenir en draft."),
    # --- Jeu ---
    ("Jeu", "League of Legends (LoL)", "—",
     "Jeu vidéo en ligne où deux équipes de 5 joueurs s'affrontent pour détruire la base adverse."),
    ("Jeu", "Champion", "Personnage",
     "Personnage jouable, chacun avec ses compétences propres (plus de 160 dans le jeu)."),
    ("Jeu", "Méta", "Stratégies dominantes",
     "Ensemble des champions et stratégies les plus efficaces à un moment donné."),
    ("Jeu", "Patch", "Mise à jour",
     "Mise à jour du jeu (ex. 12.23) qui renforce ou affaiblit des champions. Environ toutes les 2 semaines."),
    ("Jeu", "Saison", "Année de jeu",
     "Cycle annuel du jeu. La saison 12 correspond à 2022 et compte 23 patchs."),
    ("Jeu", "Draft", "Phase de sélection",
     "Étape avant la partie où chaque équipe bannit puis choisit ses champions."),
    ("Jeu", "Pick", "Sélection",
     "Choisir un champion pendant la draft."),
    ("Jeu", "Ban", "Bannissement",
     "Interdire un champion pendant la draft : personne ne pourra le jouer dans la partie."),
    ("Jeu", "Buff / Nerf", "Renforcement / Affaiblissement",
     "Modification d'un champion par un patch pour le rendre plus fort (buff) ou plus faible (nerf)."),
    ("Jeu", "Counter", "Contre",
     "Champion efficace contre un autre ; « contrer » = choisir ce champion en réponse."),
    ("Jeu", "Splash art", "Illustration",
     "Image officielle en grand format d'un champion (visible dans l'onglet Profil)."),
    # --- Rôles ---
    ("Rôles", "TOP", "Voie du haut",
     "Joueur de la voie du haut, souvent un combattant ou un tank résistant."),
    ("Rôles", "JUNGLE", "Jungle",
     "Joueur qui circule entre les voies, tue les monstres neutres et aide ses alliés."),
    ("Rôles", "MID", "Voie du milieu",
     "Joueur de la voie centrale, souvent un mage ou un assassin."),
    ("Rôles", "ADC", "Tireur (Attack Damage Carry)",
     "Joueur de la voie du bas qui inflige des dégâts physiques à distance."),
    ("Rôles", "SUPPORT", "Soutien",
     "Joueur qui accompagne l'ADC, protège et soigne ses alliés."),
    ("Rôles", "Off-role", "Rôle secondaire",
     "Rôle rarement joué par un champion (moins de 1 % des parties). Consultable uniquement dans le profil champion."),
    ("Rôles", "Carry", "Porteur",
     "Joueur ou champion chargé de faire gagner la partie grâce à ses dégâts."),
    # --- Classes de champions ---
    ("Classes", "Fighter", "Combattant", "Champion de corps à corps, équilibré entre dégâts et résistance."),
    ("Classes", "Mage", "Mage", "Champion qui inflige des dégâts magiques avec ses sorts."),
    ("Classes", "Marksman", "Tireur", "Champion qui attaque à distance avec des dégâts constants."),
    ("Classes", "Tank", "Tank", "Champion très résistant qui encaisse les dégâts pour son équipe."),
    ("Classes", "Assassin", "Assassin", "Champion mobile capable d'éliminer rapidement une cible fragile."),
    ("Classes", "Support", "Soutien", "Champion qui soigne, protège ou gêne les adversaires."),
]
def render_glossary_tab() -> None:
    st.caption(
        "Tous les termes techniques du dashboard, avec leur traduction et une "
        "définition simple. Tapez un mot pour le retrouver."
    )
    query = st.text_input("🔎 Rechercher un terme", placeholder="ex. ban, tier, KDA…").strip().lower()

    glossary = pd.DataFrame(GLOSSARY, columns=["Catégorie", "Terme", "Traduction", "Définition"])
    if query:
        mask = glossary[["Terme", "Traduction", "Définition"]].apply(
            lambda col: col.str.lower().str.contains(query, regex=False)
        ).any(axis=1)
        glossary = glossary[mask]
        if glossary.empty:
            st.info("Aucun terme ne correspond à cette recherche.")
            return

    # st.table (et non st.dataframe) : le texte long revient à la ligne au lieu
    # d'être coupé. Largeurs de colonnes fixes, limitées à ce conteneur.
    st.markdown(
        """<style>
        .st-key-glossary table { table-layout: fixed; width: 100%; }
        .st-key-glossary th, .st-key-glossary td { white-space: normal; word-wrap: break-word; vertical-align: top; }
        .st-key-glossary th:nth-child(1), .st-key-glossary td:nth-child(1) { width: 20%; font-weight: 600; }
        .st-key-glossary th:nth-child(2), .st-key-glossary td:nth-child(2) { width: 22%; }
        </style>""",
        unsafe_allow_html=True,
    )
    with st.container(key="glossary"):
        for category, terms in glossary.groupby("Catégorie", sort=False):
            st.subheader(category)
            st.table(terms.drop(columns="Catégorie"), hide_index=True)


def main() -> None:
    st.set_page_config(
        page_title="Méta LoL",
        page_icon="⚔️",
        layout="wide",
    )

    df_all = load_data(DATA_DIR)  # avec off-roles : réservé au profil champion
    df = df_all[~df_all["off_role"]]
    image_ids = load_champion_ids()
    roles, tiers, patch_num = render_sidebar(df)

    # Trois portées de filtrage, du plus large au plus étroit :
    #  - par rôle uniquement (sert de référence "moyenne de saison")
    #  - par rôle + patch (sert à l'accroche, stable même si l'utilisateur change le tier)
    #  - par rôle + tier + patch (portée réellement affichée dans les graphiques)
    df_season_role = df[df["Role"].isin(roles)]
    df_season_scope = df_season_role[df_season_role["Tier"].isin(tiers)]
    df_patch_role = df_season_role[df_season_role["patch_num"] == patch_num]
    df_scope = df_patch_role[df_patch_role["Tier"].isin(tiers)]

    render_header(df_patch_role, patch_num)

    st.divider()

    # Onglets pilotables (clé + on_change) : la tier liste peut ouvrir le profil.
    tab_overview, tab_rankings, tab_tier_list, tab_profile, tab_glossary = st.tabs(
        ["📊 Vue d'ensemble", "🏆 Classements", "🗂️ Tier liste", PROFILE_TAB, "📖 Lexique"],
        key="main_tab", on_change="rerun",
    )
    with tab_overview:
        render_overview_tab(df_scope, df_season_role, patch_num)
    with tab_rankings:
        render_rankings_tab(df_scope, patch_num, image_ids)
    with tab_tier_list:
        render_tier_list_tab(df_scope, patch_num, image_ids)
    with tab_profile:
        render_profile_tab(df_all, patch_num, image_ids)
    with tab_glossary:
        render_glossary_tab()



if __name__ == "__main__":
    main()
