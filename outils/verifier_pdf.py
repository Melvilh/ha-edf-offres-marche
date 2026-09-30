"""Vérifie que l'intégration sait lire les vraies grilles de prix EDF.

À lancer depuis la racine du projet, avec le venv activé (pdfplumber et requests installés) :

    python outils/verifier_pdf.py                # les 9 offres (téléchargement)
    python outils/verifier_pdf.py ZEN_FIXE       # une seule offre
    python outils/verifier_pdf.py --hors-ligne   # relit les PDF déjà enregistrés (sans réseau)

Ce que fait l'outil, pour chaque offre :
  1. télécharge le PDF (et l'enregistre dans outils/pdf/), sauf avec --hors-ligne ;
  2. lit le PDF avec EXACTEMENT le même code que l'intégration (parsers.py) ;
  3. affiche un résumé (OK / ERREUR) et écrit un rapport détaillé dans
     outils/sortie_verification.txt : tableaux bruts vus par pdfplumber, date d'entrée
     en vigueur trouvée, tarifs lus. Ce rapport permet de corriger la lecture d'une offre
     quand sa mise en page n'est pas celle qu'on avait prévue.

Rien n'est envoyé nulle part : les PDF sont publics et restent sur ton disque.
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
import traceback
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_PDF = Path(__file__).resolve().parent / "pdf"
RAPPORT = Path(__file__).resolve().parent / "sortie_verification.txt"


def charger_modules():
    """Charge parsers.py et const.py SANS Home Assistant.

    Importer le paquet normalement exécuterait __init__.py, qui a besoin de Home Assistant.
    On déclare donc deux « faux » paquets vides qui pointent vers les vrais dossiers : Python
    trouve alors parsers.py et const.py sans jamais lancer __init__.py.
    """
    for nom, chemin in (
        ("custom_components", RACINE / "custom_components"),
        ("custom_components.edf_tarifs_offres_marche", RACINE / "custom_components" / "edf_tarifs_offres_marche"),
    ):
        faux_paquet = types.ModuleType(nom)
        faux_paquet.__path__ = [str(chemin)]
        sys.modules[nom] = faux_paquet
    base = "custom_components.edf_tarifs_offres_marche"
    return importlib.import_module(f"{base}.parsers"), importlib.import_module(f"{base}.const")


def recuperer_pdf(offre: str, url: str, hors_ligne: bool) -> bytes:
    fichier = DOSSIER_PDF / f"{offre}.pdf"
    if hors_ligne:
        return fichier.read_bytes()
    import requests

    reponse = requests.get(url, timeout=30)
    reponse.raise_for_status()
    DOSSIER_PDF.mkdir(exist_ok=True)
    fichier.write_bytes(reponse.content)
    return reponse.content


def decrire_tables(tables: list) -> list[str]:
    lignes = []
    for i, (contexte, rows) in enumerate(tables):
        lignes.append(f"  Tableau {i} : {len(rows)} lignes")
        lignes.append(f"    texte juste au-dessus : {contexte!r}")
        for r, ligne in enumerate(rows[:5]):
            lignes.append(f"    ligne {r}: {ligne}")
        if len(rows) > 5:
            lignes.append("    ...")
            lignes.append(f"    ligne {len(rows) - 1}: {rows[-1]}")
    return lignes


def verifier(offre: str, definition: dict, parsers, hors_ligne: bool) -> tuple[bool, str, list[str]]:
    """Renvoie (succès, résumé d'une ligne, détails pour le rapport)."""
    details = [f"=== {offre} — {definition['nom']}", f"URL : {definition['url']}"]
    try:
        pdf = recuperer_pdf(offre, definition["url"], hors_ligne)
    except Exception as err:  # noqa: BLE001
        details.append(f"ÉCHEC du téléchargement : {err!r}")
        return False, f"ERREUR  {offre:26} téléchargement impossible : {err}", details
    details.append(f"PDF : {len(pdf)} octets")

    try:
        tables, texte = parsers.extraire_tables_et_texte(pdf)
    except Exception as err:  # noqa: BLE001
        details += ["ÉCHEC de la lecture du PDF :", traceback.format_exc()]
        return False, f"ERREUR  {offre:26} PDF illisible : {err}", details

    phrase = re.search(r"(?i)applicable[^\n]{0,90}", texte)
    details.append(f"Phrase de date trouvée : {phrase.group(0)!r}" if phrase else "Phrase de date : AUCUNE trouvée")
    details.append(f"Date d'effet lue : {parsers.extraire_date_effet(texte)}")
    details += ["Tableaux vus par pdfplumber :", *decrire_tables(tables)]
    details += ["Début du texte de la 1re page :", *("    " + ligne for ligne in texte.splitlines()[:25])]

    try:
        grille = parsers.grille_depuis_tables(offre, tables, texte)
    except Exception as err:  # noqa: BLE001
        details += ["ÉCHEC de l'interprétation des tableaux :", f"    {err}"]
        return False, f"ERREUR  {offre:26} {err}", details

    resume_options = ", ".join(f"{o}: {len(lignes)} puissances" for o, lignes in grille.tarifs.items())
    details.append("Tarifs lus :")
    for option, lignes in grille.tarifs.items():
        details.append(f"  option {option}")
        for puissance, valeurs in sorted(lignes.items()):
            details.append(f"    {puissance:>2} kVA : {valeurs}")
    manquantes = set(definition["options"]) - set(grille.tarifs)
    date_txt = grille.date_effet.isoformat() if grille.date_effet else "DATE NON TROUVÉE"
    alerte = f"  ATTENTION options prévues mais absentes : {sorted(manquantes)}" if manquantes else ""
    return not manquantes and grille.date_effet is not None, (
        f"{'OK     ' if not manquantes and grille.date_effet else 'A VOIR '} {offre:26} "
        f"date d'effet : {date_txt:16} {resume_options}{alerte}"
    ), details


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Vérifie la lecture des grilles de prix EDF")
    parser.add_argument("offres", nargs="*", help="noms d'offres (par défaut : toutes)")
    parser.add_argument("--hors-ligne", action="store_true", help="relit outils/pdf/ sans réseau")
    args = parser.parse_args()

    parsers, const = charger_modules()
    noms = args.offres or list(const.OFFRES)
    inconnues = [n for n in noms if n not in const.OFFRES]
    if inconnues:
        print(f"Offres inconnues : {inconnues}. Choix possibles : {list(const.OFFRES)}")
        return 2

    resumes, rapport, tout_ok = [], [], True
    for offre in noms:
        ok, resume, details = verifier(offre, const.OFFRES[offre], parsers, args.hors_ligne)
        print(resume)
        resumes.append(resume)
        rapport += [*details, ""]
        tout_ok &= ok

    RAPPORT.write_text("RÉSUMÉ\n" + "\n".join(resumes) + "\n\n" + "\n".join(rapport), encoding="utf-8")
    print(f"\nRapport détaillé : {RAPPORT}")
    print("Tout est bon." if tout_ok else "Certaines offres sont à regarder : envoie-moi le rapport.")
    return 0 if tout_ok else 1


if __name__ == "__main__":
    sys.exit(main())
