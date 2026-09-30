import copy
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.edf_tarifs_offres_marche.abonnement import abonnement_par_jour
from custom_components.edf_tarifs_offres_marche.const import (
    DOMAIN,
    KWH_PAR_JOUR_ABONNEMENT,
    OFFRES,
    OPTIONS,
)
from custom_components.edf_tarifs_offres_marche.coordinator import cle_stockage

from .helpers import EXPECTED_ZEN_ONLINE, SYNTH_TITRES, build_pdf, valeurs_valides

PARIS = ZoneInfo("Europe/Paris")
URL_ONLINE = OFFRES["ZEN_ONLINE"]["url"]
PHRASE_AOUT = "Applicable à compter du 1<super>er</super> août 2026 pour toute nouvelle souscription"


def phrase(jour: str) -> str:
    return f"Applicable à compter du {jour} pour toute nouvelle souscription"


def pdf_online(phrase_date: str = PHRASE_AOUT, modifs: dict | None = None) -> bytes:
    """PDF Zen Online factice ; `modifs` = {(option, puissance): {cle: valeur}} à changer."""
    tarifs = copy.deepcopy(EXPECTED_ZEN_ONLINE)
    for (option, puissance), valeurs in (modifs or {}).items():
        if valeurs is None:
            del tarifs[option][puissance]
        else:
            tarifs[option][puissance].update(valeurs)
    return build_pdf(tarifs, phrase=phrase_date)


class Edf:
    """Simule le site d'EDF : on choisit ce que renvoie chaque PDF."""

    def __init__(self, aioclient_mock):
        self.mock = aioclient_mock
        self.reponses: dict[str, dict] = {}

    def sert(self, offre: str, contenu: bytes | None = None, status: int = 200):
        self.reponses[offre] = {"content": contenu, "status": status}
        self.mock.clear_requests()
        for cle, rep in self.reponses.items():
            if rep["status"] == 200:
                self.mock.get(OFFRES[cle]["url"], content=rep["content"])
            else:
                self.mock.get(OFFRES[cle]["url"], status=rep["status"])


@pytest.fixture
def edf(aioclient_mock):
    return Edf(aioclient_mock)


@pytest.fixture(autouse=True)
async def fuseau_france(hass):
    await hass.config.async_set_time_zone("Europe/Paris")


@pytest.fixture
def maintenant(freezer):
    """Fige l'horloge au 1er septembre 2026, midi à Paris."""
    freezer.move_to(datetime(2026, 9, 1, 12, 0, tzinfo=PARIS))
    return freezer


async def avancer(hass, freezer, **delta):
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def aller_a(hass, freezer, quand: datetime):
    freezer.move_to(quand)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def _choix(result) -> list[str]:
    """Valeurs proposées par la liste déroulante d'un formulaire."""
    selecteur = next(iter(result["data_schema"].schema.values()))
    return [o["value"] for o in selecteur.config["options"]]


async def creer(hass, offre="ZEN_ONLINE", option="base", puissance=6):
    """Parcourt le formulaire en entier ; renvoie le résultat final."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"offre": offre})
    if result["type"] is FlowResultType.FORM and result["step_id"] == "option":
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"option_tarifaire": option}
        )
    if result["type"] is FlowResultType.FORM and result["step_id"] == "puissance":
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"puissance": str(puissance)}
        )
    await hass.async_block_till_done()
    return result


def etat(hass, entry, cle):
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{cle}")
    assert entity_id is not None, f"capteur {cle} non créé"
    return hass.states.get(entity_id)


def valeur(hass, entry, cle) -> float:
    return float(etat(hass, entry, cle).state)


def cles_capteurs(hass, entry) -> set[str]:
    reg = er.async_get(hass)
    prefixe = f"{entry.entry_id}_"
    return {e.unique_id.removeprefix(prefixe) for e in er.async_entries_for_config_entry(reg, entry.entry_id)}


# ------------------------------------------------------------------------------------------
# Formulaire
# ------------------------------------------------------------------------------------------
async def test_formulaire_propose_tous_les_contrats(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", pdf_online())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert set(_choix(result)) == set(OFFRES) and len(OFFRES) == 9


async def test_les_choix_dependent_du_contrat_et_de_l_option(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", pdf_online())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"offre": "ZEN_ONLINE"})
    assert result["step_id"] == "option" and _choix(result) == ["base", "hc_hp"]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"option_tarifaire": "base"})
    assert result["step_id"] == "puissance"
    assert _choix(result) == ["3", "6", "9", "12", "15", "18", "24", "30", "36"]

    # Retour en arrière impossible dans un flow : on en recommence un pour HC/HP.
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"offre": "ZEN_ONLINE"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"option_tarifaire": "hc_hp"})
    assert _choix(result) == ["6", "9", "12", "15", "18", "24", "30", "36"]  # pas de 3 kVA en HC/HP


async def test_offre_a_option_unique_saute_la_question(hass, edf, maintenant):
    tarifs = {"hc_hp": {p: {"abonnement": 16.0, **valeurs_valides("hc_hp")} for p in (6, 9)}}
    edf.sert("VERT_ELECTRIQUE_AUTO", build_pdf(tarifs, titres=SYNTH_TITRES["VERT_ELECTRIQUE_AUTO"], titre_au_dessus=True, phrase=phrase("15 septembre 2026")))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"offre": "VERT_ELECTRIQUE_AUTO"})
    assert result["step_id"] == "puissance" and _choix(result) == ["6", "9"]


async def test_erreurs_du_formulaire_puis_reprise(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", status=500)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"offre": "ZEN_ONLINE"})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "cannot_connect"}

    edf.sert("ZEN_ONLINE", b"ceci n'est pas un pdf")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"offre": "ZEN_ONLINE"})
    assert result["errors"] == {"base": "pdf_illisible"}

    edf.sert("ZEN_ONLINE", pdf_online())
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"offre": "ZEN_ONLINE"})
    assert result["step_id"] == "option"


async def test_doublon_refuse_mais_autre_combinaison_possible(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", pdf_online())
    await creer(hass, "ZEN_ONLINE", "base", 6)
    result = await creer(hass, "ZEN_ONLINE", "base", 6)
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert (await creer(hass, "ZEN_ONLINE", "hc_hp", 6))["type"] is FlowResultType.CREATE_ENTRY
    assert (await creer(hass, "ZEN_ONLINE", "base", 9))["type"] is FlowResultType.CREATE_ENTRY
    assert len(hass.config_entries.async_entries(DOMAIN)) == 3


# ------------------------------------------------------------------------------------------
# Capteurs
# ------------------------------------------------------------------------------------------
async def test_zen_online_base_6kva(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", pdf_online())
    result = await creer(hass, "ZEN_ONLINE", "base", 6)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"offre": "ZEN_ONLINE", "option_tarifaire": "base", "puissance": 6}
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED and entry.title == "Zen Online 6 kVA (Base)"
    assert cles_capteurs(hass, entry) == {
        "abonnement", "prix_kwh", "abonnement_jour", "abonnement_prix_energie", "abonnement_compteur",
    }

    abo, kwh = etat(hass, entry, "abonnement"), etat(hass, entry, "prix_kwh")
    assert float(abo.state) == 15.86 and abo.attributes["unit_of_measurement"] == "EUR"
    assert abo.attributes["device_class"] == "monetary"
    assert float(kwh.state) == 0.1925 and kwh.attributes["unit_of_measurement"] == "EUR/kWh"
    assert abo.attributes["friendly_name"] == "Zen Online 6 kVA (Base) Monthly subscription"
    assert abo.attributes["date_application"] == "2026-08-01" and abo.attributes["tarif_provisoire"] is False
    assert "prochaine_valeur" not in abo.attributes


async def test_zen_online_hc_hp_9kva(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", pdf_online())
    entry = (await creer(hass, "ZEN_ONLINE", "hc_hp", 9))["result"]
    assert cles_capteurs(hass, entry) == {
        "abonnement", "prix_kwh_hp", "prix_kwh_hc", "abonnement_jour", "abonnement_prix_energie", "abonnement_compteur",
    }
    assert valeur(hass, entry, "abonnement") == 19.88
    assert valeur(hass, entry, "prix_kwh_hp") == 0.2059 and valeur(hass, entry, "prix_kwh_hc") == 0.1531


async def test_autre_contrat_week_end_flex(hass, edf, maintenant):
    """Zen Week-End, option Flex : 4 prix (données synthétiques d'après la description du PDF)."""
    tarifs = {
        o: {p: {"abonnement": 16.0 + p, **valeurs_valides(o)} for p in (6, 9)}
        for o in ("week_end", "hc_week_end", "flex")
    }
    edf.sert("ZEN_WEEK_END", build_pdf(tarifs, titres=SYNTH_TITRES["ZEN_WEEK_END"], phrase=phrase("15 septembre 2026")))
    entry = (await creer(hass, "ZEN_WEEK_END", "flex", 9))["result"]
    assert entry.title == "Zen Week-End 9 kVA (Flex)"
    assert cles_capteurs(hass, entry) == {
        "abonnement", "prix_kwh_hc_eco", "prix_kwh_hp_eco", "prix_kwh_hc_sobriete", "prix_kwh_hp_sobriete",
        "abonnement_jour", "abonnement_prix_energie", "abonnement_compteur",
    }
    prix = valeurs_valides("flex")
    for cle, centimes in prix.items():
        assert valeur(hass, entry, cle) == pytest.approx(centimes / 100)
    assert valeur(hass, entry, "abonnement") == 25.0
    # 15 septembre 2026 est dans le futur (nous sommes le 1er) et il n'y a pas d'autre grille :
    assert etat(hass, entry, "abonnement").attributes["tarif_provisoire"] is True


# ------------------------------------------------------------------------------------------
# Abonnement dans le tableau Énergie
# ------------------------------------------------------------------------------------------
async def test_abonnement_pour_le_tableau_energie(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", pdf_online())
    entry = (await creer(hass, "ZEN_ONLINE", "base", 6))["result"]
    par_jour = abonnement_par_jour(15.86, datetime(2026, 9, 1).date())

    jour, prix = etat(hass, entry, "abonnement_jour"), etat(hass, entry, "abonnement_prix_energie")
    assert float(jour.state) == pytest.approx(par_jour) and jour.attributes["unit_of_measurement"] == "EUR"
    assert prix.attributes["unit_of_measurement"] == "EUR/kWh"
    assert float(prix.state) == pytest.approx(par_jour / KWH_PAR_JOUR_ABONNEMENT)

    compteur = etat(hass, entry, "abonnement_compteur")
    assert compteur.attributes["device_class"] == "energy"
    assert compteur.attributes["state_class"] == "total_increasing"
    assert compteur.attributes["unit_of_measurement"] == "kWh"
    assert float(compteur.state) == 0  # part de zéro à la création


async def test_le_compteur_avance_de_facon_continue(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", pdf_online())
    entry = (await creer(hass, "ZEN_ONLINE", "base", 6))["result"]

    await avancer(hass, maintenant, hours=12)
    assert valeur(hass, entry, "abonnement_compteur") == pytest.approx(KWH_PAR_JOUR_ABONNEMENT / 2)
    await avancer(hass, maintenant, hours=12)
    assert valeur(hass, entry, "abonnement_compteur") == pytest.approx(KWH_PAR_JOUR_ABONNEMENT)
    await avancer(hass, maintenant, days=9)
    assert valeur(hass, entry, "abonnement_compteur") == pytest.approx(10 * KWH_PAR_JOUR_ABONNEMENT)
    # Coût d'une journée dans le tableau Énergie = compteur × prix = abonnement du jour
    cout_jour = KWH_PAR_JOUR_ABONNEMENT * valeur(hass, entry, "abonnement_prix_energie")
    assert cout_jour == pytest.approx(valeur(hass, entry, "abonnement_jour"))


async def test_le_tableau_energie_accepte_les_capteurs_d_abonnement(hass, edf, maintenant):
    """On applique les propres règles de validation du tableau Énergie de Home Assistant."""
    from homeassistant.components.energy import validate as energie

    edf.sert("ZEN_ONLINE", pdf_online())
    entry = (await creer(hass, "ZEN_ONLINE", "base", 6))["result"]
    compteur = etat(hass, entry, "abonnement_compteur").entity_id
    prix = etat(hass, entry, "abonnement_prix_energie").entity_id
    abonnement = etat(hass, entry, "abonnement").entity_id

    def valider(entite_energie, entite_prix):
        problemes = energie.ValidationIssues()
        # Les statistiques n'existent qu'après la 1re heure d'enregistrement : on les suppose présentes.
        with patch("homeassistant.components.recorder.is_entity_recorded", return_value=True):
            energie._async_validate_usage_stat(
                hass, {entite_energie: (1, {})}, entite_energie,
                energie.ENERGY_USAGE_DEVICE_CLASSES, energie.ENERGY_USAGE_UNITS,
                energie.ENERGY_UNIT_ERROR, problemes,
            )
        energie._async_validate_price_entity(
            hass, entite_prix, problemes, energie.ENERGY_PRICE_UNITS, energie.ENERGY_PRICE_UNIT_ERROR
        )
        return set(problemes.issues)  # types de problèmes détectés

    assert valider(compteur, prix) == set()  # accepté sans le moindre problème

    # Contre-épreuve : le validateur n'est pas complaisant. Un capteur monétaire en € n'est
    # ni une énergie, ni un prix au kWh.
    assert valider(abonnement, abonnement) == {
        "entity_unexpected_device_class",
        "entity_unexpected_state_class",
        "entity_unexpected_unit_energy_price",
    }


# ------------------------------------------------------------------------------------------
# Dates d'entrée en vigueur
# ------------------------------------------------------------------------------------------
async def test_un_tarif_publie_a_l_avance_ne_s_applique_qu_a_sa_date(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", pdf_online())  # grille du 1er août 2026 : 6 kVA Base = 15,86 €
    entry = (await creer(hass, "ZEN_ONLINE", "base", 6))["result"]
    assert valeur(hass, entry, "abonnement") == 15.86

    # EDF publie déjà la grille du 1er février 2027 (abonnement 16,50, kWh 20,00 cts).
    edf.sert("ZEN_ONLINE", pdf_online(phrase("1er février 2027"), {("base", 6): {"abonnement": 16.5, "prix_kwh": 20.0}}))
    await avancer(hass, maintenant, hours=6, minutes=1)  # rafraîchissement : la nouvelle grille est lue

    abo = etat(hass, entry, "abonnement")
    assert float(abo.state) == 15.86  # PAS le nouveau tarif
    assert valeur(hass, entry, "prix_kwh") == 0.1925
    assert abo.attributes["date_application"] == "2026-08-01"
    assert abo.attributes["prochaine_date_application"] == "2027-02-01"
    assert abo.attributes["prochaine_valeur"] == 16.5
    assert etat(hass, entry, "prix_kwh").attributes["prochaine_valeur"] == 0.2

    # La veille de l'entrée en vigueur : toujours l'ancien tarif.
    await aller_a(hass, maintenant, datetime(2027, 1, 31, 23, 59, tzinfo=PARIS))
    assert valeur(hass, entry, "abonnement") == 15.86

    # Le jour J, peu après minuit : le nouveau tarif s'applique.
    await aller_a(hass, maintenant, datetime(2027, 2, 1, 0, 1, tzinfo=PARIS))
    abo = etat(hass, entry, "abonnement")
    assert float(abo.state) == 16.5 and valeur(hass, entry, "prix_kwh") == 0.2
    assert abo.attributes["date_application"] == "2027-02-01"
    assert "prochaine_valeur" not in abo.attributes


async def test_la_bascule_se_fait_a_minuit_sans_telechargement(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", pdf_online())
    entry = (await creer(hass, "ZEN_ONLINE", "base", 6))["result"]
    edf.sert("ZEN_ONLINE", pdf_online(phrase("2 septembre 2026"), {("base", 6): {"abonnement": 17.0}}))
    await avancer(hass, maintenant, hours=6, minutes=1)  # 1er sept. 18:01 : grille du 2 sept. lue
    assert valeur(hass, entry, "abonnement") == 15.86

    edf.sert("ZEN_ONLINE", status=500)  # plus de réseau : seule l'horloge peut déclencher la bascule
    demandes = len(edf.mock.mock_calls)
    maintenant.move_to(datetime(2026, 9, 2, 0, 0, 5, tzinfo=PARIS))
    entry.runtime_data._au_changement_de_jour(None)  # ce que fait la programmation de 00:00:05
    await hass.async_block_till_done()
    assert valeur(hass, entry, "abonnement") == 17.0
    assert len(edf.mock.mock_calls) == demandes  # aucun téléchargement


async def test_pdf_sans_date_les_tarifs_sont_appliques_et_un_avertissement_est_journalise(hass, edf, maintenant, caplog):
    edf.sert("ZEN_ONLINE", pdf_online("Prix valables pour toute nouvelle souscription"))
    entry = (await creer(hass, "ZEN_ONLINE", "base", 6))["result"]
    abo = etat(hass, entry, "abonnement")
    assert float(abo.state) == 15.86 and abo.attributes["date_application"] is None
    assert caplog.text.count("Date d'entrée en vigueur introuvable") == 1

    await avancer(hass, maintenant, hours=6, minutes=1)  # 2e lecture : pas de nouvel avertissement
    assert caplog.text.count("Date d'entrée en vigueur introuvable") == 1


async def test_installation_pendant_l_attente_d_un_nouveau_tarif(hass, edf, maintenant):
    """Seule la grille du 15 septembre existe et nous sommes le 1er : utilisée en « provisoire »."""
    edf.sert("ZEN_ONLINE", pdf_online(phrase("15 septembre 2026")))
    entry = (await creer(hass, "ZEN_ONLINE", "base", 6))["result"]
    abo = etat(hass, entry, "abonnement")
    assert float(abo.state) == 15.86 and abo.attributes["tarif_provisoire"] is True
    assert abo.attributes["date_application"] == "2026-09-15"


async def test_une_puissance_retiree_de_la_grille_garde_son_ancien_tarif(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", pdf_online())
    entry = (await creer(hass, "ZEN_ONLINE", "base", 36))["result"]
    assert valeur(hass, entry, "abonnement") == 53.88

    edf.sert("ZEN_ONLINE", pdf_online(phrase("2 septembre 2026"), {("base", 36): None}))  # 36 kVA supprimé
    await aller_a(hass, maintenant, datetime(2026, 9, 3, 12, 0, tzinfo=PARIS))
    abo = etat(hass, entry, "abonnement")
    assert float(abo.state) == 53.88 and abo.attributes["date_application"] == "2026-08-01"


# ------------------------------------------------------------------------------------------
# Pannes et redémarrages
# ------------------------------------------------------------------------------------------
async def test_demarrage_impossible_sans_pdf(hass, edf, maintenant):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="ZEN_ONLINE_base_6", title="Zen Online 6 kVA (Base)",
        data={"offre": "ZEN_ONLINE", "option_tarifaire": "base", "puissance": 6},
    )
    entry.add_to_hass(hass)
    edf.sert("ZEN_ONLINE", status=500)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY  # HA réessaiera tout seul

    edf.sert("ZEN_ONLINE", b"pas un pdf")
    await avancer(hass, maintenant, minutes=1)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_pdf_sans_les_tableaux(hass, edf, maintenant):
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    import io

    buf = io.BytesIO()
    SimpleDocTemplate(buf).build([Paragraph("Autre document", getSampleStyleSheet()["Normal"])])
    edf.sert("ZEN_ONLINE", buf.getvalue())
    entry = (await creer(hass, "ZEN_ONLINE", "base", 6))
    # Le formulaire lui-même refuse : la grille est illisible.
    assert entry["type"] is FlowResultType.FORM and entry["errors"] == {"base": "pdf_illisible"}


async def test_puissance_absente_de_toutes_les_grilles(hass, edf, maintenant):
    edf.sert("ZEN_ONLINE", pdf_online())
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="x", title="Zen Online 99 kVA (Base)",
        data={"offre": "ZEN_ONLINE", "option_tarifaire": "base", "puissance": 99},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_panne_temporaire_on_garde_les_derniers_tarifs_puis_indisponible(hass, edf, maintenant, caplog):
    edf.sert("ZEN_ONLINE", pdf_online())
    entry = (await creer(hass, "ZEN_ONLINE", "base", 6))["result"]

    edf.sert("ZEN_ONLINE", status=500)
    await avancer(hass, maintenant, hours=6, minutes=1)
    assert valeur(hass, entry, "abonnement") == 15.86  # toujours affiché
    assert "on garde les derniers tarifs enregistrés" in caplog.text

    await avancer(hass, maintenant, days=10)
    assert valeur(hass, entry, "abonnement") == 15.86  # 10 jours : encore toléré

    await avancer(hass, maintenant, days=5)  # > 14 jours sans lecture réussie
    assert etat(hass, entry, "abonnement").state == STATE_UNAVAILABLE

    edf.sert("ZEN_ONLINE", pdf_online())  # EDF revient
    await avancer(hass, maintenant, hours=6, minutes=1)
    assert valeur(hass, entry, "abonnement") == 15.86


async def test_redemarrage_sans_reseau_avec_l_historique_enregistre(hass, edf, maintenant, hass_storage):
    edf.sert("ZEN_ONLINE", pdf_online())
    entry = (await creer(hass, "ZEN_ONLINE", "base", 6))["result"]
    assert cle_stockage("ZEN_ONLINE") in hass_storage  # historique écrit sur le disque

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    edf.sert("ZEN_ONLINE", status=500)  # EDF injoignable au redémarrage
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert valeur(hass, entry, "abonnement") == 15.86


async def test_decharger_et_supprimer(hass, edf, maintenant, hass_storage):
    edf.sert("ZEN_ONLINE", pdf_online())
    premiere = (await creer(hass, "ZEN_ONLINE", "base", 6))["result"]
    seconde = (await creer(hass, "ZEN_ONLINE", "hc_hp", 6))["result"]

    assert await hass.config_entries.async_unload(premiere.entry_id)
    await hass.async_block_till_done()
    assert premiere.state is ConfigEntryState.NOT_LOADED
    assert etat(hass, premiere, "abonnement").state == STATE_UNAVAILABLE

    # Supprimer la 1re configuration garde l'historique (la 2nde l'utilise encore)...
    await hass.config_entries.async_remove(premiere.entry_id)
    await hass.async_block_till_done()
    assert cle_stockage("ZEN_ONLINE") in hass_storage
    # ...supprimer la dernière l'efface.
    await hass.config_entries.async_remove(seconde.entry_id)
    await hass.async_block_till_done()
    assert cle_stockage("ZEN_ONLINE") not in hass_storage


# ------------------------------------------------------------------------------------------
# Traductions
# ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("langue", ["fr", "en"])
async def test_traductions_presentes_et_dans_la_bonne_langue(hass, langue):
    config = await async_get_translations(hass, langue, "config", [DOMAIN])
    p = f"component.{DOMAIN}.config"
    for cle in (
        "step.user.title", "step.user.data.offre", "step.option.data.option_tarifaire",
        "step.puissance.data.puissance", "error.cannot_connect", "error.pdf_illisible",
        "abort.already_configured",
    ):
        assert config.get(f"{p}.{cle}"), f"traduction manquante ({langue}) : {cle}"

    entite = await async_get_translations(hass, langue, "entity", [DOMAIN])
    q = f"component.{DOMAIN}.entity.sensor"
    cles = {"abonnement", "abonnement_jour", "abonnement_prix_energie", "abonnement_compteur"}
    cles |= {c for o in OPTIONS.values() for c in o["prix"]}
    for cle in cles:
        assert entite.get(f"{q}.{cle}.name"), f"traduction manquante ({langue}) : capteur {cle}"

    # Home Assistant retombe sur l'anglais si une traduction manque : on vérifie le TEXTE.
    attendu = {"fr": ("Abonnement mensuel", "Puissance souscrite"), "en": ("Monthly subscription", "Subscribed power")}[langue]
    assert entite[f"{q}.abonnement.name"] == attendu[0]
    assert config[f"{p}.step.puissance.data.puissance"] == attendu[1]
