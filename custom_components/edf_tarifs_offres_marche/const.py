"""Constantes de l'intégration EDF Offres Marché.

Ce fichier ne contient que des DONNÉES, jamais de logique. Chaque valeur est écrite
une seule fois ici, puis importée par les autres fichiers : une faute de frappe est
alors détectée tout de suite par Python (NameError) au lieu de produire un bug
silencieux (par exemple "hc_hp" écrit "hp_hc" dans un autre fichier).

Les tarifs réglementés (Tarif Bleu : Base / HPHC / Tempo) ne sont volontairement pas
gérés ici : l'intégration « hass-tarif-edf » s'en occupe déjà très bien.
"""

# Identifiant unique de l'intégration. Il doit être IDENTIQUE à trois endroits :
#   1. le nom du dossier custom_components/<DOMAIN>/
#   2. la clé "domain" de manifest.json
#   3. cette constante
DOMAIN = "edf_tarifs_offres_marche"

# Noms des champs du formulaire de configuration (config_flow.py).
# HA range les réponses de l'utilisateur dans entry.data sous ces mêmes clés :
# c'est ce que sensor.py et coordinator.py relisent ensuite.
CONF_OFFRE = "offre"
CONF_OPTION = "option_tarifaire"
CONF_PUISSANCE = "puissance"

# --- Options tarifaires ------------------------------------------------------------
# Une "option" est la façon dont le prix du kWh est structuré à l'intérieur d'une offre
# (prix unique, heures creuses / pleines, week-end...). Ces valeurs servent à la fois de
# clés dans les données lues dans les PDF et de valeurs stockées par le formulaire.
OPTION_BASE = "base"
OPTION_HC_HP = "hc_hp"
OPTION_WEEK_END = "week_end"
OPTION_HC_WEEK_END = "hc_week_end"
OPTION_FLEX = "flex"
OPTION_WE_JOUR = "we_jour"
OPTION_HC_WE_JOUR = "hc_we_jour"
OPTION_SUPER_CREUSES = "super_creuses"

# Pour chaque option :
#   libelle  : texte affiché dans le formulaire
#   titre    : version courte, utilisée dans le nom de l'appareil
#   prix     : clés des prix du kWh, DANS L'ORDRE des colonnes du PDF EDF
#   croissant: paires (petit, grand) qui doivent vérifier petit <= grand. C'est un
#              garde-fou : si EDF change l'ordre des colonnes, un prix "heures creuses"
#              se retrouverait plus grand que le prix "heures pleines" et la lecture
#              échouerait bruyamment au lieu d'afficher de mauvais tarifs.
OPTIONS = {
    OPTION_BASE: {
        "libelle": "Base",
        "titre": "Base",
        "prix": ("prix_kwh",),
        "croissant": (),
    },
    OPTION_HC_HP: {
        "libelle": "Heures Creuses / Heures Pleines",
        "titre": "HC/HP",
        "prix": ("prix_kwh_hp", "prix_kwh_hc"),
        "croissant": (("prix_kwh_hc", "prix_kwh_hp"),),
    },
    OPTION_WEEK_END: {
        "libelle": "Week-End",
        "titre": "Week-End",
        "prix": ("prix_kwh_semaine", "prix_kwh_weekend"),
        "croissant": (("prix_kwh_weekend", "prix_kwh_semaine"),),
    },
    OPTION_HC_WEEK_END: {
        "libelle": "Heures Creuses + Week-End",
        "titre": "HC + Week-End",
        "prix": (
            "prix_kwh_hp_semaine",
            "prix_kwh_hc_semaine",
            "prix_kwh_hp_weekend",
            "prix_kwh_hc_weekend",
        ),
        "croissant": (
            ("prix_kwh_hc_semaine", "prix_kwh_hp_semaine"),
            ("prix_kwh_hc_weekend", "prix_kwh_hp_weekend"),
            ("prix_kwh_hp_weekend", "prix_kwh_hp_semaine"),
            ("prix_kwh_hc_weekend", "prix_kwh_hc_semaine"),
        ),
    },
    OPTION_FLEX: {
        "libelle": "Flex (jours Éco / Sobriété)",
        "titre": "Flex",
        "prix": (
            "prix_kwh_hc_eco",
            "prix_kwh_hp_eco",
            "prix_kwh_hc_sobriete",
            "prix_kwh_hp_sobriete",
        ),
        "croissant": (
            ("prix_kwh_hc_eco", "prix_kwh_hp_eco"),
            ("prix_kwh_hc_sobriete", "prix_kwh_hp_sobriete"),
            ("prix_kwh_hp_eco", "prix_kwh_hp_sobriete"),
        ),
    },
    OPTION_WE_JOUR: {
        "libelle": "Week-End + jour choisi",
        "titre": "Week-End + jour",
        "prix": ("prix_kwh_semaine", "prix_kwh_weekend", "prix_kwh_jour"),
        "croissant": (
            ("prix_kwh_weekend", "prix_kwh_semaine"),
            ("prix_kwh_jour", "prix_kwh_semaine"),
        ),
    },
    OPTION_HC_WE_JOUR: {
        "libelle": "Heures Creuses + Week-End + jour choisi",
        "titre": "HC + Week-End + jour",
        "prix": (
            "prix_kwh_hp_semaine",
            "prix_kwh_hc_semaine",
            "prix_kwh_hp_weekend",
            "prix_kwh_hc_weekend",
            "prix_kwh_hp_jour",
            "prix_kwh_hc_jour",
        ),
        "croissant": (
            ("prix_kwh_hc_semaine", "prix_kwh_hp_semaine"),
            ("prix_kwh_hc_weekend", "prix_kwh_hp_weekend"),
            ("prix_kwh_hc_jour", "prix_kwh_hp_jour"),
            ("prix_kwh_hp_weekend", "prix_kwh_hp_semaine"),
            ("prix_kwh_hp_jour", "prix_kwh_hp_semaine"),
        ),
    },
    OPTION_SUPER_CREUSES: {
        "libelle": "Heures super creuses (été / hiver)",
        "titre": "Super creuses",
        "prix": (
            "prix_kwh_hsc_ete",
            "prix_kwh_hc_ete",
            "prix_kwh_hp_ete",
            "prix_kwh_hsc_hiver",
            "prix_kwh_hc_hiver",
            "prix_kwh_hp_hiver",
        ),
        "croissant": (
            ("prix_kwh_hsc_ete", "prix_kwh_hc_ete"),
            ("prix_kwh_hc_ete", "prix_kwh_hp_ete"),
            ("prix_kwh_hsc_hiver", "prix_kwh_hc_hiver"),
            ("prix_kwh_hc_hiver", "prix_kwh_hp_hiver"),
        ),
    },
}

# --- Offres --------------------------------------------------------------------------
# Pour chaque offre :
#   nom     : nom affiché
#   url     : grille de prix publique (PDF), lue sans connexion
#   options : {option: motif} où le motif est une expression régulière qui reconnaît le
#             TITRE du tableau de cette option dans le PDF. Le texte est d'abord
#             normalisé : minuscules, sans accents, "week-end" écrit "weekend",
#             espaces simplifiés. L'ordre compte : le 1er motif qui correspond gagne.
OFFRES = {
    "ZEN_ONLINE": {
        "nom": "Zen Online",
        "url": "https://particulier.edf.fr/content/dam/2-Actifs/Documents/Offres/grille-prix-zen-online.pdf",
        "options": {
            OPTION_BASE: r"option base",
            OPTION_HC_HP: r"option heures creuses",
        },
    },
    "ZEN_FIXE": {
        "nom": "Zen Fixe",
        "url": "https://particulier.edf.fr/content/dam/2-Actifs/Documents/Offres/Grille-prix-zen-fixe.pdf",
        "options": {
            OPTION_BASE: r"option base",
            OPTION_HC_HP: r"option heures creuses",
        },
    },
    # L'option Flex fait partie de l'offre Zen Week-End (même PDF, page « Zen Flex »).
    "ZEN_WEEK_END": {
        "nom": "Zen Week-End",
        "url": "https://particulier.edf.fr/content/dam/2-Actifs/Documents/Offres/grille-prix-zen-week-end.pdf",
        "options": {
            OPTION_WEEK_END: r"option (?:we|weekend)\b(?! \+)",
            OPTION_HC_WEEK_END: r"option heures creuses \+ (?:we|weekend)\b",
            OPTION_FLEX: r"option flex",
        },
    },
    "ZEN_WEEK_END_PLUS": {
        "nom": "Zen Week-End Plus",
        "url": "https://particulier.edf.fr/content/dam/2-Actifs/Documents/Offres/grille-prix-zen-week-end-plus.pdf",
        "options": {
            OPTION_WE_JOUR: r"option (?:we|weekend) \+ jour",
            OPTION_HC_WE_JOUR: r"option heures creuses \+ (?:we|weekend) \+ jour",
        },
    },
    "ZEN_ESTIVAL": {
        "nom": "Zen Estival",
        "url": "https://particulier.edf.fr/content/dam/2-Actifs/Documents/Offres/grille-prix-zen-estival.pdf",
        "options": {
            OPTION_SUPER_CREUSES: r"super creuses",
        },
    },
    "VERT_ELECTRIQUE": {
        "nom": "Vert Électrique",
        "url": "https://particulier.edf.fr/content/dam/2-Actifs/Documents/Offres/grille-prix-vert-electrique.pdf",
        "options": {
            OPTION_BASE: r"option base",
            OPTION_HC_HP: r"option heures creuses",
        },
    },
    "VERT_ELECTRIQUE_WEEK_END": {
        "nom": "Vert Électrique Week-End",
        "url": "https://particulier.edf.fr/content/dam/2-Actifs/Documents/Offres/grille-prix-vert-electrique-weekend.pdf",
        "options": {
            OPTION_WEEK_END: r"option (?:we|weekend)\b(?! \+)",
            OPTION_HC_WEEK_END: r"option heures creuses \+ (?:we|weekend)\b",
        },
    },
    "VERT_ELECTRIQUE_AUTO": {
        "nom": "Vert Électrique Auto",
        "url": "https://particulier.edf.fr/content/dam/2-Actifs/Documents/Offres/grille-prix-vert-electrique-auto.pdf",
        "options": {
            OPTION_HC_HP: r"option heures creuses",
        },
    },
    "VERT_ELECTRIQUE_REGIONAL": {
        "nom": "Vert Électrique Régional",
        "url": "https://particulier.edf.fr/content/dam/2-Actifs/Documents/Offres/grille-prix-vert-electrique-regional.pdf",
        "options": {
            OPTION_BASE: r"option base",
            OPTION_HC_HP: r"option heures creuses",
        },
    },
}

# --- Lecture des PDF -----------------------------------------------------------------
# Garde-fous de plausibilité : une valeur hors de ces bornes signale une mauvaise
# lecture du PDF (colonne décalée, virgule perdue...) et fait échouer la lecture.
ABONNEMENT_MIN, ABONNEMENT_MAX = 3.0, 150.0  # euros TTC par mois
PRIX_KWH_MIN, PRIX_KWH_MAX = 1.0, 150.0  # centimes d'euro TTC par kWh

# Si le PDF EDF est illisible ou injoignable, on continue d'utiliser les derniers
# tarifs enregistrés pendant ce nombre de jours, puis les capteurs deviennent
# "indisponibles" (mieux vaut ne rien afficher que des tarifs trop anciens).
PEREMPTION_JOURS = 14

# Nombre de grilles de prix gardées en mémoire (l'actuelle, les anciennes, les futures).
MAX_GRILLES = 8

# --- Abonnement dans le tableau Énergie de Home Assistant ----------------------------
# Le tableau Énergie ne sait pas afficher un abonnement. On triche proprement : un
# compteur d'énergie fictif avance de KWH_PAR_JOUR_ABONNEMENT kWh toutes les 24 h, et un
# "prix du kWh" égal à (abonnement du jour / cette valeur) est associé : le coût affiché
# par jour est alors exactement le prix de l'abonnement, sur une ligne à part.
# On garde une valeur minuscule (0,001 kWh par jour) pour ne pas fausser les totaux de
# consommation du réseau (avec 1 kWh par jour, on ajouterait ~1 kWh fictif à chaque jour).
KWH_PAR_JOUR_ABONNEMENT = 0.001
