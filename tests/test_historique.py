from datetime import date

from custom_components.edf_tarifs_offres_marche.const import MAX_GRILLES
from custom_components.edf_tarifs_offres_marche.historique import (
    Grille,
    ajouter_grille,
    choisir_tarif,
    historique_depuis_json,
    historique_vers_json,
)


def grille(jour, abo=15.0, kwh=20.0, puissances=(6,), option="base"):
    return Grille(
        jour,
        {option: {p: {"abonnement": abo, "prix_kwh": kwh} for p in puissances}},
    )


ANCIENNE = grille(date(2026, 2, 1), abo=15.0, kwh=20.0)
NOUVELLE = grille(date(2026, 8, 1), abo=16.0, kwh=21.0)
FUTURE = grille(date(2027, 2, 1), abo=17.0, kwh=22.0)


def test_le_tarif_futur_n_est_pas_applique_avant_sa_date():
    h = (ANCIENNE, NOUVELLE, FUTURE)
    s = choisir_tarif(h, date(2027, 1, 31), "base", 6)
    assert s.tarif["abonnement"] == 16.0 and s.date_effet == date(2026, 8, 1)
    assert not s.provisoire
    # ...mais il est annoncé
    assert s.suivant["abonnement"] == 17.0 and s.suivant_date == date(2027, 2, 1)


def test_le_tarif_futur_s_applique_le_jour_de_sa_date():
    h = (ANCIENNE, NOUVELLE, FUTURE)
    s = choisir_tarif(h, date(2027, 2, 1), "base", 6)
    assert s.tarif["abonnement"] == 17.0 and s.suivant is None


def test_avant_la_premiere_grille_on_prend_la_plus_proche_en_provisoire():
    s = choisir_tarif((NOUVELLE, FUTURE), date(2026, 7, 1), "base", 6)
    assert s.provisoire and s.tarif["abonnement"] == 16.0
    assert s.suivant["abonnement"] == 17.0  # la suivante reste annoncée


def test_grille_sans_date_est_toujours_applicable_mais_la_plus_ancienne():
    sans_date = grille(None, abo=14.0)
    s = choisir_tarif((sans_date,), date(2026, 5, 1), "base", 6)
    assert s.tarif["abonnement"] == 14.0 and not s.provisoire and s.date_effet is None
    s = choisir_tarif((sans_date, NOUVELLE), date(2026, 9, 1), "base", 6)
    assert s.tarif["abonnement"] == 16.0  # la grille datée prend le relais


def test_puissance_retiree_d_une_grille_on_garde_l_ancienne_valeur():
    ancienne = grille(date(2026, 2, 1), abo=50.0, puissances=(6, 36))
    nouvelle = grille(date(2026, 8, 1), abo=16.0, puissances=(6,))  # 36 kVA supprimé
    assert choisir_tarif((ancienne, nouvelle), date(2026, 9, 1), "base", 6).tarif["abonnement"] == 16.0
    s = choisir_tarif((ancienne, nouvelle), date(2026, 9, 1), "base", 36)
    assert s.tarif["abonnement"] == 50.0 and s.date_effet == date(2026, 2, 1)


def test_option_ou_puissance_inconnue():
    assert choisir_tarif((NOUVELLE,), date(2026, 9, 1), "base", 99) is None
    assert choisir_tarif((NOUVELLE,), date(2026, 9, 1), "hc_hp", 6) is None
    assert choisir_tarif((), date(2026, 9, 1), "base", 6) is None


def test_ajouter_remplace_la_grille_de_meme_date_et_trie():
    h = ajouter_grille((NOUVELLE,), ANCIENNE)
    assert [g.date_effet for g in h] == [date(2026, 2, 1), date(2026, 8, 1)]
    corrigee = grille(date(2026, 8, 1), abo=16.5)
    h = ajouter_grille(h, corrigee)
    assert len(h) == 2 and h[1].tarifs["base"][6]["abonnement"] == 16.5


def test_ajouter_limite_le_nombre_de_grilles():
    h = ()
    for mois in range(1, 13):
        h = ajouter_grille(h, grille(date(2026, mois, 1)))
    assert len(h) == MAX_GRILLES
    assert h[-1].date_effet == date(2026, 12, 1) and h[0].date_effet == date(2026, 12 - MAX_GRILLES + 1, 1)


def test_aller_retour_json():
    h = (grille(None), ANCIENNE, grille(date(2026, 8, 1), puissances=(6, 36), option="hc_hp"))
    import json

    assert historique_depuis_json(json.loads(json.dumps(historique_vers_json(h)))) == h
