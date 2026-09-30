import copy
from datetime import date

import pytest

from custom_components.edf_tarifs_offres_marche.const import OFFRES
from custom_components.edf_tarifs_offres_marche.parsers import (
    _normaliser,
    _reconnaitre_option,
    extraire_date_effet,
    grille_depuis_tables,
    parse_pdf,
)

from .helpers import (
    EXPECTED_ZEN_ESTIVAL,
    EXPECTED_ZEN_FIXE,
    EXPECTED_ZEN_ONLINE,
    EXPECTED_ZEN_WEEK_END,
    EXPECTED_ZEN_WEEK_END_PLUS,
    REAL_ZEN_ESTIVAL,
    REAL_ZEN_FIXE,
    REAL_ZEN_ONLINE,
    REAL_ZEN_WEEK_END,
    REAL_ZEN_WEEK_END_PLUS,
    SYNTH_TITRES,
    build_pdf,
    faux_tableau,
    valeurs_valides,
)


# --- Vrais tableaux EDF (sortie de pdfplumber sur le PC de l'utilisateur) ---------------
def test_zen_online_reel():
    grille = grille_depuis_tables("ZEN_ONLINE", REAL_ZEN_ONLINE)
    assert grille.tarifs == EXPECTED_ZEN_ONLINE
    assert len(grille.tarifs["base"]) == 9 and len(grille.tarifs["hc_hp"]) == 8


def test_zen_fixe_reel_avec_cellules_fusionnees():
    """Les None du PDF (cellules fusionnées) sont complétés avec le dernier prix connu."""
    grille = grille_depuis_tables("ZEN_FIXE", REAL_ZEN_FIXE)
    assert grille.tarifs == EXPECTED_ZEN_FIXE
    assert grille.tarifs["base"][6]["prix_kwh"] == 18.47  # complété depuis la ligne 3 kVA
    assert grille.tarifs["base"][36]["prix_kwh"] == 18.35  # complété depuis la ligne 9 kVA
    assert grille.tarifs["hc_hp"][36]["prix_kwh_hc"] == 15.07


@pytest.mark.parametrize(
    ("offre", "tables", "attendu"),
    [
        ("ZEN_WEEK_END", REAL_ZEN_WEEK_END, EXPECTED_ZEN_WEEK_END),
        ("ZEN_WEEK_END_PLUS", REAL_ZEN_WEEK_END_PLUS, EXPECTED_ZEN_WEEK_END_PLUS),
        ("ZEN_ESTIVAL", REAL_ZEN_ESTIVAL, EXPECTED_ZEN_ESTIVAL),
    ],
)
def test_tableaux_en_blocs_multi_lignes_reels(offre, tables, attendu):
    """PDF réels où tout le tableau tient en une ligne aux cellules multi-lignes."""
    assert grille_depuis_tables(offre, tables).tarifs == attendu


def test_bloc_multi_lignes_aux_colonnes_inegales_refuse():
    """Une colonne plus courte que les autres = valeurs décalées possibles : on refuse."""
    tables = copy.deepcopy(REAL_ZEN_ESTIVAL)
    ligne = tables[1][1][3]
    ligne[2] = "\n".join(ligne[2].split("\n")[:-1])  # 8 prix au lieu de 9
    with pytest.raises(ValueError, match="même nombre de valeurs"):
        grille_depuis_tables("ZEN_ESTIVAL", tables)


def test_ordre_des_tableaux_sans_importance():
    assert grille_depuis_tables("ZEN_ONLINE", list(reversed(REAL_ZEN_ONLINE))).tarifs == EXPECTED_ZEN_ONLINE


# --- Erreurs : mieux vaut échouer bruyamment que afficher de faux tarifs -----------------
def test_aucun_tableau_reconnu():
    with pytest.raises(ValueError, match="Aucun tableau"):
        grille_depuis_tables("ZEN_ONLINE", [("", [['', '']])])
    with pytest.raises(ValueError, match="Aucun tableau"):
        grille_depuis_tables("ZEN_ONLINE", [])


def test_prix_manquant_sur_la_premiere_ligne():
    tables = copy.deepcopy(REAL_ZEN_ONLINE)
    tables[1][1][2] = ['3', None, None, '12,13', None, None, None, None, None]  # 1re ligne de données
    with pytest.raises(ValueError, match="sans ligne précédente"):
        grille_depuis_tables("ZEN_ONLINE", tables)


def test_trop_de_valeurs():
    tables = copy.deepcopy(REAL_ZEN_ONLINE)
    tables[1][1][3] = ['3', '12,13', '19,25', '19,25']
    with pytest.raises(ValueError, match="valeurs attendues"):
        grille_depuis_tables("ZEN_ONLINE", tables)


def test_colonnes_heures_creuses_inversees_detectees():
    tables = copy.deepcopy(REAL_ZEN_ONLINE)
    for ligne in tables[2][1][3:]:
        ligne[2], ligne[3] = ligne[3], ligne[2]  # HP et HC échangés
    with pytest.raises(ValueError, match="colonnes peut-être décalées"):
        grille_depuis_tables("ZEN_ONLINE", tables)


def test_valeurs_invraisemblables():
    tables = copy.deepcopy(REAL_ZEN_ONLINE)
    tables[1][1][3] = ['3', None, None, '1213', None, None, '19,25', None, None]  # virgule perdue
    with pytest.raises(ValueError, match="abonnement invraisemblable"):
        grille_depuis_tables("ZEN_ONLINE", tables)


# --- Date d'entrée en vigueur ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("Applicable à compter du 1er aout 2026 pour toute nouvelle souscription", date(2026, 8, 1)),
        ("Applicable à compter du 1 er août 2026", date(2026, 8, 1)),
        ("Applicable à compter du 1\ner\naout 2026 pour toute", date(2026, 8, 1)),
        ("Applicable au 15 septembre 2026 pour toute nouvelle souscription", date(2026, 9, 15)),
        ("APPLICABLE À COMPTER DU 1ER FÉVRIER 2027", date(2027, 2, 1)),
        ("Applicable au 1er décembre 2026", date(2026, 12, 1)),
        ("Applicable à compter du 31 février 2026", None),  # date impossible
        ("Grille de prix sans date", None),
        ("", None),
    ],
)
def test_extraire_date_effet(texte, attendu):
    assert extraire_date_effet(texte) == attendu


def test_la_date_est_portee_par_la_grille():
    texte = "Grille ... Applicable à compter du 15 septembre 2026 pour toute nouvelle souscription"
    assert grille_depuis_tables("ZEN_ONLINE", REAL_ZEN_ONLINE, texte).date_effet == date(2026, 9, 15)
    assert grille_depuis_tables("ZEN_ONLINE", REAL_ZEN_ONLINE).date_effet is None


# --- Toutes les offres (titres d'après la description des PDF : à valider avec les vrais) ---
def test_toutes_les_offres_ont_des_titres_de_test():
    assert set(SYNTH_TITRES) == set(OFFRES)
    for offre, definition in OFFRES.items():
        assert set(SYNTH_TITRES[offre]) == set(definition["options"]), offre


def test_chaque_titre_ne_correspond_qu_a_une_seule_option():
    """Aucune ambiguïté : le titre d'une option ne doit pas déclencher le motif d'une autre."""
    import re

    for offre, definition in OFFRES.items():
        for option, titre in SYNTH_TITRES[offre].items():
            normalise = _normaliser(titre)
            correspondances = [o for o, motif in definition["options"].items() if re.search(motif, normalise)]
            assert correspondances == [option], (offre, option, titre, correspondances)


@pytest.mark.parametrize("titre_dans_le_tableau", [True, False])
@pytest.mark.parametrize("offre", list(OFFRES))
def test_lecture_de_toutes_les_offres(offre, titre_dans_le_tableau):
    tables = [
        faux_tableau(option, titre, titre_dans_le_tableau)
        for option, titre in SYNTH_TITRES[offre].items()
    ]
    grille = grille_depuis_tables(offre, [("", [['', '']]), *tables])
    assert set(grille.tarifs) == set(OFFRES[offre]["options"])
    for option, lignes in grille.tarifs.items():
        assert sorted(lignes) == [6, 9, 12, 36]
        # chaque prix est rangé sous la bonne clé, dans l'ordre des colonnes du PDF
        assert lignes[6] == {"abonnement": 16.0, **valeurs_valides(option)}


def test_titre_coupe_en_deux_cellules():
    lignes = [['Option Heures Cre', 'uses (TTC)', None, None], ['6', '15,86', '20,59', '15,31']]
    grille = grille_depuis_tables("ZEN_ONLINE", [("", lignes)])
    assert grille.tarifs == {"hc_hp": {6: {"abonnement": 15.86, "prix_kwh_hp": 20.59, "prix_kwh_hc": 15.31}}}


def test_reconnaissance_par_le_texte_au_dessus_du_tableau():
    motifs = OFFRES["VERT_ELECTRIQUE_AUTO"]["options"]
    lignes = [["Puissance", "Abonnement"], ["6", "15,00", "20,00", "15,00"]]
    assert _reconnaitre_option(motifs, "Option Heures Creuses (TTC)", lignes) == "hc_hp"
    assert _reconnaitre_option(motifs, "Autre chose", lignes) is None


# --- Lecture d'un vrai fichier PDF (fabriqué avec reportlab) ---------------------------------
@pytest.mark.parametrize("titre_au_dessus", [False, True])
def test_pdf_de_bout_en_bout(titre_au_dessus):
    pdf = build_pdf(
        {
            "base": {p: {"abonnement": a, "prix_kwh": k} for p, (a, k) in {6: (15.86, 19.25), 9: (19.88, 19.09)}.items()},
            "hc_hp": {p: {"abonnement": a, "prix_kwh_hp": 20.59, "prix_kwh_hc": 15.31} for p, a in {6: 15.86, 9: 19.88}.items()},
        },
        titre_au_dessus=titre_au_dessus,
    )
    grille = parse_pdf("ZEN_ONLINE", pdf)
    assert grille.date_effet == date(2026, 8, 1)  # « 1<super>er</super> août » bien lu
    assert grille.tarifs["base"] == {6: {"abonnement": 15.86, "prix_kwh": 19.25}, 9: {"abonnement": 19.88, "prix_kwh": 19.09}}
    assert grille.tarifs["hc_hp"][9] == {"abonnement": 19.88, "prix_kwh_hp": 20.59, "prix_kwh_hc": 15.31}


def test_pdf_sans_date_donne_une_date_vide():
    pdf = build_pdf({"base": {6: {"abonnement": 15.86, "prix_kwh": 19.25}}}, phrase="Prix valables pour toute souscription")
    assert parse_pdf("ZEN_ONLINE", pdf).date_effet is None


def test_pdf_autre_offre_avec_titres_au_dessus():
    """Vert Électrique Auto : un seul tableau, dont le titre est un paragraphe au-dessus."""
    titres = SYNTH_TITRES["VERT_ELECTRIQUE_AUTO"]
    pdf = build_pdf(
        {"hc_hp": {6: {"abonnement": 16.0, "prix_kwh_hp": 21.0, "prix_kwh_hc": 12.0}}},
        phrase="Applicable à compter du 15 septembre 2026 pour toute nouvelle souscription",
        titres=titres,
        titre_au_dessus=True,
    )
    grille = parse_pdf("VERT_ELECTRIQUE_AUTO", pdf)
    assert grille.date_effet == date(2026, 9, 15)
    assert grille.tarifs == {"hc_hp": {6: {"abonnement": 16.0, "prix_kwh_hp": 21.0, "prix_kwh_hc": 12.0}}}
