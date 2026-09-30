from datetime import date, datetime, timedelta, timezone

import pytest

from custom_components.edf_tarifs_offres_marche.abonnement import (
    abonnement_par_jour,
    compteur_kwh,
    prix_energie_de_l_abonnement,
)
from custom_components.edf_tarifs_offres_marche.const import KWH_PAR_JOUR_ABONNEMENT


def test_abonnement_par_jour_annee_normale_et_bissextile():
    assert abonnement_par_jour(15.86, date(2026, 6, 1)) == pytest.approx(15.86 * 12 / 365)
    assert abonnement_par_jour(15.86, date(2028, 6, 1)) == pytest.approx(15.86 * 12 / 366)


def test_365_jours_d_abonnement_font_douze_mensualites():
    total = sum(abonnement_par_jour(15.86, date(2026, 1, 1) + timedelta(days=i)) for i in range(365))
    assert total == pytest.approx(15.86 * 12)


def test_cout_d_un_jour_dans_le_tableau_energie_egale_l_abonnement_du_jour():
    """kWh fictifs d'un jour × « prix du kWh » = abonnement d'un jour."""
    jour = date(2026, 6, 1)
    assert KWH_PAR_JOUR_ABONNEMENT * prix_energie_de_l_abonnement(15.86, jour) == pytest.approx(
        abonnement_par_jour(15.86, jour)
    )


def test_compteur_part_de_zero_avance_de_facon_continue_et_ne_recule_jamais():
    origine = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    assert compteur_kwh(origine, origine) == 0
    assert compteur_kwh(origine + timedelta(hours=12), origine) == pytest.approx(KWH_PAR_JOUR_ABONNEMENT / 2)
    assert compteur_kwh(origine + timedelta(hours=24), origine) == pytest.approx(KWH_PAR_JOUR_ABONNEMENT)
    assert compteur_kwh(origine + timedelta(days=30), origine) == pytest.approx(30 * KWH_PAR_JOUR_ABONNEMENT)
    assert compteur_kwh(origine - timedelta(hours=1), origine) == 0  # jamais négatif
    valeurs = [compteur_kwh(origine + timedelta(minutes=15 * i), origine) for i in range(500)]
    assert valeurs == sorted(valeurs)
