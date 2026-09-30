"""Historique des grilles de prix et choix du tarif applicable à une date donnée.

Pourquoi ce fichier existe : EDF publie parfois sa nouvelle grille AVANT sa date
d'entrée en vigueur (« Applicable à compter du 15 septembre »). Le PDF téléchargé
contient alors déjà les prix futurs. Pour ne les appliquer qu'à la bonne date, on
garde en mémoire (sur le disque de HA) chaque grille vue avec sa date d'effet, et on
choisit celle qui est en vigueur AUJOURD'HUI.

Ce fichier ne dépend pas de Home Assistant : il ne fait que manipuler des données.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .const import MAX_GRILLES


@dataclass(frozen=True)
class Grille:
    """Une grille de prix lue dans un PDF.

    date_effet : date à partir de laquelle elle s'applique (None si le PDF ne la donne pas)
    tarifs     : {option: {puissance_kVA: {"abonnement": 15.86, "prix_kwh": 19.25, ...}}}
                 abonnement en euros TTC par mois, prix du kWh en centimes d'euro TTC.
    """

    date_effet: date | None
    tarifs: dict


@dataclass(frozen=True)
class Selection:
    """Le tarif à utiliser aujourd'hui pour une option et une puissance données."""

    tarif: dict  # {"abonnement": ..., "prix_kwh": ...}
    date_effet: date | None  # date d'entrée en vigueur du tarif utilisé
    provisoire: bool  # True si ce tarif n'est pas encore en vigueur (voir choisir_tarif)
    suivant: dict | None  # prochain tarif déjà publié, ou None
    suivant_date: date | None  # sa date d'entrée en vigueur


def _date_pour_tri(grille: Grille) -> date:
    """Une grille sans date est considérée comme la plus ancienne."""
    return grille.date_effet or date.min


def ajouter_grille(historique: tuple[Grille, ...], grille: Grille) -> tuple[Grille, ...]:
    """Ajoute une grille à l'historique.

    Si une grille de même date existe déjà, elle est REMPLACÉE (EDF corrige parfois une
    coquille sans changer la date). On ne garde que les MAX_GRILLES plus récentes.
    """
    autres = [g for g in historique if g.date_effet != grille.date_effet]
    triees = sorted([*autres, grille], key=_date_pour_tri)
    return tuple(triees[-MAX_GRILLES:])


def choisir_tarif(
    historique: tuple[Grille, ...], aujourdhui: date, option: str, puissance: int
) -> Selection | None:
    """Choisit le tarif en vigueur à la date `aujourdhui`.

    Règles :
      - on ne regarde que les grilles qui contiennent cette option ET cette puissance
        (si EDF retire une puissance d'une nouvelle grille, on garde l'ancienne valeur) ;
      - parmi elles, on prend la plus récente dont la date d'effet est déjà passée ;
      - une grille future n'est JAMAIS utilisée tant que sa date n'est pas arrivée...
      - ...sauf s'il n'existe aucune grille en vigueur (première installation faite entre
        la publication d'une grille et son entrée en vigueur) : on utilise alors la plus
        proche, marquée « provisoire », faute de mieux.
    """
    candidates = sorted(
        (g for g in historique if puissance in g.tarifs.get(option, {})),
        key=_date_pour_tri,
    )
    if not candidates:
        return None

    en_vigueur = [g for g in candidates if _date_pour_tri(g) <= aujourdhui]
    futures = [g for g in candidates if _date_pour_tri(g) > aujourdhui]

    if en_vigueur:
        courante, provisoire, suivantes = en_vigueur[-1], False, futures
    else:
        courante, provisoire, suivantes = futures[0], True, futures[1:]

    suivante = suivantes[0] if suivantes else None
    return Selection(
        tarif=courante.tarifs[option][puissance],
        date_effet=courante.date_effet,
        provisoire=provisoire,
        suivant=suivante.tarifs[option][puissance] if suivante else None,
        suivant_date=suivante.date_effet if suivante else None,
    )


# --- Sauvegarde sur disque (JSON) ---------------------------------------------------
# JSON ne sait pas écrire de dates ni de clés numériques : on convertit dans les deux
# sens (date <-> "2026-08-01", puissance 6 <-> "6").


def historique_vers_json(historique: tuple[Grille, ...]) -> list[dict]:
    return [
        {
            "date_effet": g.date_effet.isoformat() if g.date_effet else None,
            "tarifs": {
                option: {str(puissance): valeurs for puissance, valeurs in lignes.items()}
                for option, lignes in g.tarifs.items()
            },
        }
        for g in historique
    ]


def historique_depuis_json(donnees: list[dict]) -> tuple[Grille, ...]:
    return tuple(
        Grille(
            date_effet=date.fromisoformat(d["date_effet"]) if d["date_effet"] else None,
            tarifs={
                option: {int(puissance): valeurs for puissance, valeurs in lignes.items()}
                for option, lignes in d["tarifs"].items()
            },
        )
        for d in donnees
    )
