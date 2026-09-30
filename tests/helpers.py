"""Données de test.

- REAL_* : tableaux EXACTS affichés par page.extract_tables() sur le PC de l'utilisateur
  (Zen Online et Zen Fixe, PDF EDF réels).
- SYNTH_TITRES : titres de tableaux des autres offres, d'après la DESCRIPTION de leur
  structure (je n'ai pas pu télécharger ces PDF) : hypothèses à valider avec le vrai PDF.
- build_pdf : fabrique un PDF factice (reportlab) pour tester la lecture de bout en bout.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# --- Zen Online (PDF réel) ---------------------------------------------------------
REAL_ZEN_ONLINE = [
    ("", [['', '']]),
    ("", [['Option Base (TTC)', None, None, None, None, None, None, None, None],
          ['Puissance\nSouscrite\n(kVA)', None, None, 'Abonnement\nmensuel\n(€ TTC/mois)', None, None, 'Prix du kWh\n(cts € TTC/kWh)', None, None],
          ['3', None, None, '12,13', None, None, '19,25', None, None],
          ['6', None, None, '15,86', None, None, '19,25', None, None],
          ['9', None, None, '19,88', None, None, '19,09', None, None],
          ['12', None, None, '23,76', None, None, '19,09', None, None],
          ['15', None, None, '27,40', None, None, '19,09', None, None],
          ['', '18', '', '', '31,14', '', '', '19,09', ''],
          ['', '24', '', '', '39,14', '', '', '19,09', ''],
          ['', '30', '', '', '46,47', '', '', '19,09', ''],
          ['', '36', '', '', '53,88', '', '', '19,09', '']]),
    ("", [['Option Heures Creuses (TTC)', None, None, None],
          ['Puissance\nSouscrite\n(kVA)', 'Abonnement\nmensuel\n(€ TTC/mois)', 'Prix du kWh\n(cts € TTC/kWh)', None],
          [None, None, 'Heures\nPleines', 'Heures\nCreuses'],
          ['6', '15,86', '20,59', '15,31'],
          ['9', '19,88', '20,59', '15,31'],
          ['12', '23,76', '20,59', '15,31'],
          ['15', '27,40', '20,59', '15,31'],
          ['18', '31,14', '20,59', '15,31'],
          ['24', '39,14', '20,59', '15,31'],
          ['30', '46,47', '20,59', '15,31'],
          ['36', '53,88', '20,59', '15,31']]),
]  # fmt: skip

_ABO = {3: 12.13, 6: 15.86, 9: 19.88, 12: 23.76, 15: 27.4, 18: 31.14, 24: 39.14, 30: 46.47, 36: 53.88}
_KWH = {3: 19.25, 6: 19.25, 9: 19.09, 12: 19.09, 15: 19.09, 18: 19.09, 24: 19.09, 30: 19.09, 36: 19.09}
EXPECTED_ZEN_ONLINE = {
    "base": {p: {"abonnement": _ABO[p], "prix_kwh": _KWH[p]} for p in _ABO},
    "hc_hp": {
        p: {"abonnement": _ABO[p], "prix_kwh_hp": 20.59, "prix_kwh_hc": 15.31}
        for p in _ABO if p >= 6
    },
}  # fmt: skip

# --- Zen Fixe (PDF réel, avec cellules fusionnées = valeurs None à compléter) --------
REAL_ZEN_FIXE = [
    ("", [['', '']]),
    ("", [['Option Base (TTC)', None, None, None],
          ['Puissance\nSouscrite\n(kVA)', None, 'Abonnement\nmensuel', 'Prix du kWh'],
          [None, None, '(€ TTC/mois)', '(cts € TTC/kWh)'],
          ['3', None, '12,67', '18,47'],
          ['6', None, '17,22', None],
          ['9', None, '23,92', '18,35'],
          ['12', None, '29,70', None],
          ['15', None, '34,00', None],
          ['18', '', '39,24', None],
          ['24', '', '49,77', None],
          ['30', '', '57,76', None],
          ['36', '', '68,88', None]]),
    ("", [['Option Heures Creuses (TTC)', None, None, None],
          ['Puissance\nSouscrite\n(kVA)', 'Abonnement\nmensuel\n(€ TTC/mois)', 'Prix du kWh', None],
          [None, None, '(cts € TTC/kWh)', None],
          [None, None, 'Heures\nPleines', 'Heures\nCreuses'],
          ['6', '18,36', '19,66', '15,07'],
          ['9', '24,77', None, None],
          ['12', '30,91', None, None],
          ['15', '35,02', None, None],
          ['18', '40,51', None, None],
          ['24', '51,74', None, None],
          ['30', '62,38', None, None],
          ['36', '70,36', None, None]]),
]  # fmt: skip

_ABO_FIXE = {3: 12.67, 6: 17.22, 9: 23.92, 12: 29.7, 15: 34.0, 18: 39.24, 24: 49.77, 30: 57.76, 36: 68.88}
_ABO_FIXE_HC = {6: 18.36, 9: 24.77, 12: 30.91, 15: 35.02, 18: 40.51, 24: 51.74, 30: 62.38, 36: 70.36}
EXPECTED_ZEN_FIXE = {
    "base": {p: {"abonnement": a, "prix_kwh": 18.47 if p <= 6 else 18.35} for p, a in _ABO_FIXE.items()},
    "hc_hp": {p: {"abonnement": a, "prix_kwh_hp": 19.66, "prix_kwh_hc": 15.07} for p, a in _ABO_FIXE_HC.items()},
}  # fmt: skip

# --- Autres offres : titres décrits (à valider avec les vrais PDF) ---------------------
# {offre: {option: titre du tableau}}
SYNTH_TITRES = {
    "ZEN_ONLINE": {"base": "Option Base (TTC)", "hc_hp": "Option Heures Creuses (TTC)"},
    "ZEN_FIXE": {"base": "Option Base (TTC)", "hc_hp": "Option Heures Creuses (TTC)"},
    "ZEN_WEEK_END": {
        "week_end": "Option Week-End (TTC)",
        "hc_week_end": "Option Heures Creuses + WE (TTC)",
        "flex": "Option Flex (TTC)",
    },
    "ZEN_WEEK_END_PLUS": {
        "we_jour": "Option WE + jour choisi* (TTC)",
        "hc_we_jour": "Option Heures Creuses + WE + jour choisi* (TTC)",
    },
    "ZEN_ESTIVAL": {
        "super_creuses": "Les grilles de prix de l'offre « Zen Estival » - HEURES SUPER CREUSES ÉTÉ HIVER (TTC)"
    },
    "VERT_ELECTRIQUE": {"base": "Option Base (TTC)", "hc_hp": "Option Heures Creuses (TTC)"},
    "VERT_ELECTRIQUE_WEEK_END": {
        "week_end": "Option Week-End (TTC)",
        "hc_week_end": "Option Heures Creuses + Week-End (TTC)",
    },
    "VERT_ELECTRIQUE_AUTO": {
        "hc_hp": "La grille de prix de l'offre de fourniture d'électricité « Vert Électrique Auto » - Option Heures Creuses (TTC)"
    },
    "VERT_ELECTRIQUE_REGIONAL": {"base": "Option Base (TTC)", "hc_hp": "Option Heures Creuses (TTC)"},
}  # fmt: skip

PUISSANCES_TEST = [6, 9, 12, 36]


def valeurs_valides(option: str) -> dict[str, float]:
    """Prix plausibles pour chaque colonne d'une option, qui respectent ses garde-fous
    « petit <= grand » (ex. heures creuses < heures pleines)."""
    from custom_components.edf_tarifs_offres_marche.const import OPTIONS

    cles = OPTIONS[option]["prix"]
    rang = {c: 0 for c in cles}
    for _ in cles:
        for petit, grand in OPTIONS[option]["croissant"]:
            rang[grand] = max(rang[grand], rang[petit] + 1)
    return {c: 10.5 + 5 * rang[c] for c in cles}


def faux_tableau(option: str, titre: str, titre_dans_le_tableau: bool = True) -> tuple[str, list]:
    """Tableau factice à la manière de pdfplumber : (contexte, lignes)."""
    valeurs = valeurs_valides(option)
    nb_prix = len(valeurs)
    lignes = []
    if titre_dans_le_tableau:
        lignes.append([titre] + [None] * (1 + nb_prix))
    lignes.append(["Puissance\nSouscrite\n(kVA)", "Abonnement\nmensuel"] + ["Prix du kWh"] * nb_prix)
    for p in PUISSANCES_TEST:
        lignes.append(
            [str(p), f"{p + 10},00"] + [f"{v:.2f}".replace(".", ",") for v in valeurs.values()]
        )
    return ("" if titre_dans_le_tableau else titre), lignes


# --- PDF factice ------------------------------------------------------------------------
def build_pdf(
    tarifs: dict,
    phrase: str = "Applicable à compter du 1<super>er</super> août 2026 pour toute nouvelle souscription",
    titres: dict | None = None,
    titre_au_dessus: bool = False,
) -> bytes:
    """Fabrique un PDF factice avec des tableaux à traits, comme la grille EDF.

    tarifs : {option: {puissance: {"abonnement": x, cle_prix: y, ...}}} (prix en centimes)
    titres : {option: titre du tableau} (par défaut, ceux de Zen Online)
    titre_au_dessus : True = le titre est un paragraphe AU-DESSUS du tableau (pas dans une cellule)
    """
    from custom_components.edf_tarifs_offres_marche.const import OPTIONS

    titres = titres or SYNTH_TITRES["ZEN_ONLINE"]
    styles = getSampleStyleSheet()
    elements = [Paragraph("Grille de prix de l'offre de fourniture d'électricité", styles["Title"]),
                Paragraph(phrase, styles["Normal"]), Spacer(1, 20)]
    style = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)])

    def fr(x: float) -> str:
        return f"{x:.2f}".replace(".", ",")

    for option, lignes in tarifs.items():
        cles = OPTIONS[option]["prix"]
        donnees = []
        if titre_au_dessus:
            elements.append(Paragraph(titres[option], styles["Heading3"]))
        else:
            donnees.append([titres[option]] + [""] * (1 + len(cles)))
        donnees.append(["Puissance (kVA)", "Abonnement mensuel"] + ["Prix du kWh"] * len(cles))
        for puissance, valeurs in lignes.items():
            donnees.append([str(puissance), fr(valeurs["abonnement"])] + [fr(valeurs[c]) for c in cles])
        elements += [Table(donnees, colWidths=[130] * (2 + len(cles)), style=style), Spacer(1, 25)]

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4).build(elements)
    return buf.getvalue()
