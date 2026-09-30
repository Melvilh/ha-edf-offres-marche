"""Lecture des grilles de prix EDF (PDF publics).

Un seul moteur de lecture pour toutes les offres : ce qui change d'une offre à l'autre
(titres des tableaux, ordre des colonnes de prix) est décrit dans const.py.
Ce fichier ne fait AUCUN accès réseau : il reçoit le PDF déjà téléchargé (en bytes).

Deux étapes :
  1. parse_pdf() ouvre le PDF et en sort les tableaux bruts (dépend de pdfplumber) ;
  2. grille_depuis_tables() transforme ces tableaux en tarifs (fonction pure, testable
     sans avoir besoin d'un vrai fichier PDF).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from .const import (
    ABONNEMENT_MAX,
    ABONNEMENT_MIN,
    OFFRES,
    OPTIONS,
    PRIX_KWH_MAX,
    PRIX_KWH_MIN,
)
from .historique import Grille

MOIS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12,
}  # fmt: skip

# Ex. « Applicable à compter du 1er août 2026 » ou « Applicable au 15 septembre 2026 ».
# Le texte est normalisé avant (sans accents, espaces simplifiés) ; le "1er" du PDF peut
# sortir de la lecture sous la forme "1er", "1 er" ou "1 er" selon la mise en page.
_MOTIF_DATE = re.compile(
    r"applicable\s+(?:a\s+compter\s+du|au|des\s+le)\s+(\d{1,2})\s*(?:er|ere)?\s+("
    + "|".join(MOIS)
    + r")\s+(\d{4})"
)


def _normaliser(texte: str) -> str:
    """Minuscules, sans accents, « week-end » écrit « weekend », espaces simplifiés."""
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c)
    )
    texte = sans_accents.lower().replace("’", "'")
    texte = re.sub(r"week[\s-]?end", "weekend", texte)
    return re.sub(r"\s+", " ", texte).strip()


def extraire_date_effet(texte: str) -> date | None:
    """Trouve la date d'entrée en vigueur dans le texte du PDF (None si absente)."""
    trouve = _MOTIF_DATE.search(_normaliser(texte))
    if not trouve:
        return None
    jour, mois, annee = trouve.groups()
    try:
        return date(int(annee), MOIS[mois], int(jour))
    except ValueError:  # ex. 31 février : date incohérente, on l'ignore
        return None


def _nombre(texte: str) -> float:
    """Convertit un nombre écrit à la française ("15,86") en float (15.86)."""
    return float(texte.replace(",", ".").strip())


def _cellules_utiles(ligne: list) -> list[str]:
    """Retire les cases vides d'une ligne de tableau.

    pdfplumber renvoie None (ou "") pour les cellules fusionnées ou vides, et leur
    position change d'une ligne à l'autre (ex. ['', '18', '', '', '31,14', ...]).
    On ne se fie donc jamais à la position d'une colonne : on garde seulement les
    vraies valeurs, dans l'ordre où elles apparaissent.
    """
    return [cellule for cellule in ligne if cellule not in (None, "")]


def _reconnaitre_option(motifs: dict, contexte: str, lignes: list) -> str | None:
    """Trouve à quelle option correspond un tableau, d'après son titre.

    Le titre est soit dans la 1re ligne du tableau, soit juste au-dessus (`contexte`).
    """
    premiere_ligne = _cellules_utiles(lignes[0]) if lignes else []
    # Un titre long peut être coupé en deux cellules ("Option Heures Cre" + "uses (TTC)") :
    # on essaie donc les cellules séparées par un espace, puis recollées.
    candidats = [
        _normaliser(separateur.join([*premiere_ligne, contexte]))
        for separateur in (" ", "")
    ]
    for option, motif in motifs.items():
        if any(re.search(motif, candidat) for candidat in candidats):
            return option
    return None


def _lire_lignes(option: str, lignes: list) -> dict:
    """Lit les lignes de données d'un tableau : {puissance: {"abonnement": ..., prix...}}."""
    cles_prix = OPTIONS[option]["prix"]
    colonnes_attendues = 1 + len(cles_prix)  # abonnement + prix
    resultat: dict[int, dict] = {}
    derniers_prix: list[float] | None = None

    for ligne in lignes:
        cellules = _cellules_utiles(ligne)

        # Une vraie ligne de donnée commence par la puissance (un entier).
        # Titre, en-têtes et lignes vides échouent ici et sont simplement ignorés.
        try:
            puissance = int(cellules[0])
        except (ValueError, IndexError):
            continue

        valeurs = [_nombre(cellule) for cellule in cellules[1:]]
        if not 1 <= len(valeurs) <= colonnes_attendues:
            raise ValueError(
                f"Ligne {puissance} kVA ({option}) : entre 1 et {colonnes_attendues} "
                f"valeurs attendues, {len(valeurs)} trouvées ({cellules})"
            )

        abonnement, prix = valeurs[0], valeurs[1:]

        # Cellules fusionnées : quand le même prix vaut pour plusieurs puissances, le PDF
        # ne l'écrit que sur la 1re ligne du groupe (les autres cases sont vides). On
        # complète alors avec les derniers prix connus ("forward fill").
        if len(prix) < len(cles_prix):
            if derniers_prix is None:
                raise ValueError(
                    f"Ligne {puissance} kVA ({option}) : prix manquant sans ligne "
                    f"précédente pour le compléter ({cellules})"
                )
            prix = prix + derniers_prix[len(prix):]
        derniers_prix = prix

        resultat[puissance] = _verifier(
            option, puissance, {"abonnement": abonnement, **dict(zip(cles_prix, prix, strict=True))}
        )

    return resultat


def _verifier(option: str, puissance: int, valeurs: dict) -> dict:
    """Garde-fous : refuse des valeurs invraisemblables plutôt que d'afficher de faux tarifs."""
    abonnement = valeurs["abonnement"]
    if not ABONNEMENT_MIN <= abonnement <= ABONNEMENT_MAX:
        raise ValueError(f"{puissance} kVA ({option}) : abonnement invraisemblable ({abonnement})")
    for cle in OPTIONS[option]["prix"]:
        if not PRIX_KWH_MIN <= valeurs[cle] <= PRIX_KWH_MAX:
            raise ValueError(f"{puissance} kVA ({option}) : {cle} invraisemblable ({valeurs[cle]})")
    for petit, grand in OPTIONS[option]["croissant"]:
        if valeurs[petit] > valeurs[grand]:
            raise ValueError(
                f"{puissance} kVA ({option}) : {petit} ({valeurs[petit]}) devrait être "
                f"inférieur à {grand} ({valeurs[grand]}) : colonnes peut-être décalées"
            )
    return valeurs


def grille_depuis_tables(offre: str, tables: list, texte: str = "") -> Grille:
    """Transforme les tableaux d'un PDF en Grille.

    tables : liste de (contexte, lignes) ; `contexte` est le texte juste au-dessus du
             tableau (souvent son titre) et `lignes` les lignes du tableau.
    texte  : texte complet du PDF, utilisé pour trouver la date d'entrée en vigueur.
    """
    motifs = OFFRES[offre]["options"]
    tarifs: dict[str, dict] = {}

    for contexte, lignes in tables:
        # On reconnaît un tableau à son TITRE plutôt qu'à sa position dans la page :
        # si EDF ajoute un tableau, rien ne se décale. Les tableaux inconnus (le PDF
        # contient un tableau parasite [['', '']]) sont ignorés.
        option = _reconnaitre_option(motifs, contexte, lignes)
        if option is None:
            continue
        lues = _lire_lignes(option, lignes)
        if lues:
            tarifs[option] = lues

    if not tarifs:
        raise ValueError(
            f"Aucun tableau de tarifs reconnu dans le PDF {OFFRES[offre]['nom']} "
            "(la mise en page a peut-être changé)"
        )

    return Grille(date_effet=extraire_date_effet(texte), tarifs=tarifs)


def extraire_tables_et_texte(pdf_bytes: bytes) -> tuple[list[tuple[str, list]], str]:
    """Ouvre le PDF et en sort ce que pdfplumber y voit : (tableaux, texte complet).

    Chaque tableau est un couple (contexte, lignes) : `lignes` est le contenu du tableau et
    `contexte` le texte situé juste au-dessus (où se trouve parfois son titre).
    Fonction bloquante (lecture de PDF) : elle est appelée dans un thread séparé.
    """
    # Import "local" : pdfplumber est lourd, il n'est chargé que quand on lit un PDF.
    import io

    import pdfplumber

    tables: list[tuple[str, list]] = []
    textes: list[str] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            textes.append(page.extract_text() or "")

            x0, haut_page, x1, _ = page.bbox
            limite_haute = haut_page
            for tableau in page.find_tables():
                haut, bas = tableau.bbox[1], tableau.bbox[3]

                # Texte situé juste au-dessus du tableau (entre le tableau précédent et
                # celui-ci) : c'est là que peut se trouver son titre. On ne garde que les
                # 3 dernières lignes, les plus proches du tableau.
                contexte = ""
                if haut - limite_haute > 1:
                    zone = page.crop((x0, limite_haute, x1, haut))
                    contexte = "\n".join((zone.extract_text() or "").splitlines()[-3:])
                limite_haute = bas

                tables.append((contexte, tableau.extract()))

    return tables, "\n".join(textes)


def parse_pdf(offre: str, pdf_bytes: bytes) -> Grille:
    """Lit le PDF d'une offre et renvoie tous ses tarifs (toutes puissances, toutes options).

    C'est sensor.py qui choisira ensuite la ligne correspondant à la configuration.
    """
    tables, texte = extraire_tables_et_texte(pdf_bytes)
    return grille_depuis_tables(offre, tables, texte)
