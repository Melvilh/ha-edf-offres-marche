"""Calculs autour de l'abonnement (pour le tableau Énergie de Home Assistant).

Fichier sans dépendance à Home Assistant : uniquement des calculs, faciles à tester.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime

from .const import KWH_PAR_JOUR_ABONNEMENT


def abonnement_par_jour(mensuel: float, jour: date) -> float:
    """Prix de l'abonnement pour UN jour, en euros.

    EDF facture l'abonnement à l'année (12 mensualités) puis au prorata des jours :
    on divise donc le total annuel par le nombre de jours de l'année (365 ou 366).
    """
    jours_dans_l_annee = 366 if calendar.isleap(jour.year) else 365
    return mensuel * 12 / jours_dans_l_annee


def prix_energie_de_l_abonnement(mensuel: float, jour: date) -> float:
    """« Prix du kWh » à associer au compteur fictif dans le tableau Énergie.

    Le compteur avance de KWH_PAR_JOUR_ABONNEMENT kWh par jour, donc pour que le coût
    d'un jour soit égal au prix de l'abonnement d'un jour : prix = prix_du_jour / kWh_par_jour.
    """
    return abonnement_par_jour(mensuel, jour) / KWH_PAR_JOUR_ABONNEMENT


def compteur_kwh(maintenant: datetime, origine: datetime) -> float:
    """Valeur du compteur d'énergie fictif.

    Il vaut 0 à `origine` (la création de l'intégration) et avance de
    KWH_PAR_JOUR_ABONNEMENT toutes les 24 h, de façon continue et sans jamais reculer
    (le tableau Énergie exige un compteur qui ne décroît pas).
    """
    jours_ecoules = (maintenant - origine).total_seconds() / 86400
    return max(jours_ecoules, 0.0) * KWH_PAR_JOUR_ABONNEMENT
