"""Capteurs : abonnement et prix du kWh du contrat choisi par l'utilisateur.

Le coordinator contient TOUTES les grilles de prix connues (toutes les puissances, toutes
les options, y compris les tarifs futurs déjà publiés). Ici, on ne garde que la ligne qui
correspond à la configuration de l'utilisateur ET à la date d'aujourd'hui, et on crée un
capteur par valeur à afficher.

Capteurs créés pour chaque configuration :
  - Abonnement mensuel (€/mois)
  - Un prix du kWh par colonne de l'option choisie (€/kWh)
  - Abonnement journalier (€/jour), pour information
  - Deux capteurs pour mettre l'abonnement dans le tableau Énergie de HA :
      * un compteur d'énergie fictif qui avance de 0,001 kWh toutes les 24 h
      * un « prix du kWh » associé, tel que coût du jour = abonnement du jour
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import EdfOffresMarcheConfigEntry
from .abonnement import abonnement_par_jour, compteur_kwh, prix_energie_de_l_abonnement
from .const import CONF_OFFRE, CONF_OPTION, CONF_PUISSANCE, DOMAIN, OFFRES, OPTIONS
from .coordinator import EdfOffresMarcheCoordinator


def _centimes_vers_euros(centimes: float) -> float:
    """Le PDF donne le kWh en centimes d'euro (19.25) ; HA attend des euros (0.1925).

    Le round() évite les artefacts des nombres flottants (ex. 0.19249999999999998).
    """
    return round(centimes / 100, 6)


@dataclass(frozen=True, kw_only=True)
class EdfSensorDescription(SensorEntityDescription):
    """Décrit un capteur : ses propriétés fixes + comment calculer sa valeur.

    SensorEntityDescription apporte key, translation_key, unité, device_class...
    On y ajoute value_fn : une petite fonction qui reçoit la ligne de tarifs de
    l'utilisateur (ex. {"abonnement": 15.86, "prix_kwh": 19.25}) et la date du jour,
    et renvoie la valeur du capteur.
    """

    value_fn: Callable[[dict, date], float]


# Le nom affiché de chaque capteur vient de translations/*.json (via translation_key).
ABONNEMENT = EdfSensorDescription(
    key="abonnement",
    translation_key="abonnement",
    device_class=SensorDeviceClass.MONETARY,
    native_unit_of_measurement="EUR",
    suggested_display_precision=2,
    value_fn=lambda tarif, jour: tarif["abonnement"],  # déjà en euros par mois dans le PDF
)

ABONNEMENT_JOUR = EdfSensorDescription(
    key="abonnement_jour",
    translation_key="abonnement_jour",
    device_class=SensorDeviceClass.MONETARY,
    native_unit_of_measurement="EUR",
    suggested_display_precision=4,
    value_fn=lambda tarif, jour: abonnement_par_jour(tarif["abonnement"], jour),
)

# L'unité "EUR/kWh" (devise/kWh) est celle que le tableau de bord Énergie de HA accepte
# pour une entité de « prix actuel ».
ABONNEMENT_PRIX_ENERGIE = EdfSensorDescription(
    key="abonnement_prix_energie",
    translation_key="abonnement_prix_energie",
    native_unit_of_measurement="EUR/kWh",
    suggested_display_precision=2,
    value_fn=lambda tarif, jour: prix_energie_de_l_abonnement(tarif["abonnement"], jour),
)


def _description_prix(cle: str) -> EdfSensorDescription:
    """Un capteur de prix du kWh pour la colonne `cle` (ex. "prix_kwh_hp")."""
    return EdfSensorDescription(
        key=cle,
        translation_key=cle,
        native_unit_of_measurement="EUR/kWh",
        suggested_display_precision=4,
        value_fn=lambda tarif, jour: _centimes_vers_euros(tarif[cle]),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EdfOffresMarcheConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crée les capteurs (appelée par HA grâce au async_forward_entry_setups de __init__.py).

    async_add_entities est la fonction fournie par HA pour lui remettre nos capteurs.
    """
    coordinator = entry.runtime_data  # posé par __init__.py

    # Les prix du kWh dépendent de l'option choisie (1 en Base, 2 en HC/HP, 4 en Flex...).
    descriptions = [
        ABONNEMENT,
        *(_description_prix(cle) for cle in OPTIONS[entry.data[CONF_OPTION]]["prix"]),
        ABONNEMENT_JOUR,
        ABONNEMENT_PRIX_ENERGIE,
    ]

    async_add_entities(
        [
            *(EdfTarifSensor(coordinator, entry, description) for description in descriptions),
            EdfAbonnementCompteurSensor(entry),
        ]
    )


def _device_info(entry: EdfOffresMarcheConfigEntry) -> DeviceInfo:
    """Regroupe tous les capteurs d'une même configuration sous un seul « appareil »."""
    offre = OFFRES[entry.data[CONF_OFFRE]]
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="EDF",
        model=offre["nom"],
        entry_type=DeviceEntryType.SERVICE,  # service en ligne, pas un objet physique
        configuration_url=offre["url"],
    )


class EdfTarifSensor(CoordinatorEntity[EdfOffresMarcheCoordinator], SensorEntity):
    """Un capteur de tarif EDF.

    CoordinatorEntity : le capteur se met à jour tout seul à chaque rafraîchissement du
    coordinator, et passe en "indisponible" si les données sont trop anciennes.
    """

    entity_description: EdfSensorDescription

    # Le nom complet devient "<nom de l'appareil> <nom du capteur>".
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EdfOffresMarcheCoordinator,
        entry: EdfOffresMarcheConfigEntry,
        description: EdfSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description

        # Réponses données dans le formulaire (voir config_flow.py).
        self._option: str = entry.data[CONF_OPTION]
        self._puissance: int = entry.data[CONF_PUISSANCE]

        # Identifiant unique du capteur : permet à HA de le retrouver après un
        # redémarrage et de garder son historique.
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        """Valeur du capteur : on va chercher notre ligne dans les tarifs en vigueur aujourd'hui."""
        selection = self.coordinator.selection(self._option, self._puissance)
        if selection is None:
            return None  # affiche "inconnu" au lieu de planter
        return self.entity_description.value_fn(selection.tarif, dt_util.now().date())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Informations en plus : quel tarif est utilisé, et quel sera le prochain."""
        selection = self.coordinator.selection(self._option, self._puissance)
        if selection is None:
            return None
        jour = dt_util.now().date()
        lecture = self.coordinator.data.derniere_lecture

        attributs: dict[str, Any] = {
            "date_application": selection.date_effet.isoformat() if selection.date_effet else None,
            "tarif_provisoire": selection.provisoire,
            "derniere_lecture_pdf": lecture.isoformat() if lecture else None,
        }
        # Un tarif déjà publié mais pas encore en vigueur : on l'annonce sans l'appliquer.
        if selection.suivant is not None:
            attributs["prochaine_date_application"] = (
                selection.suivant_date.isoformat() if selection.suivant_date else None
            )
            attributs["prochaine_valeur"] = self.entity_description.value_fn(
                selection.suivant, selection.suivant_date or jour
            )
        return attributs


class EdfAbonnementCompteurSensor(SensorEntity):
    """Compteur d'énergie fictif, pour afficher l'abonnement dans le tableau Énergie.

    Dans le tableau Énergie de HA : ajouter une « consommation du réseau » avec ce capteur
    comme énergie consommée, puis choisir « utiliser une entité avec le prix actuel » =
    le capteur « Abonnement - prix pour le tableau Énergie ». Le coût affiché par jour est
    alors exactement l'abonnement du jour, sur une ligne à part.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "abonnement_compteur"
    # Ces trois lignes sont exigées par le tableau Énergie pour accepter un capteur.
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 6
    # Pas d'interrogation automatique : on écrit nous-mêmes l'état toutes les 15 minutes.
    _attr_should_poll = False

    def __init__(self, entry: EdfOffresMarcheConfigEntry) -> None:
        # Le compteur vaut 0 à la création de l'intégration puis avance de façon continue.
        self._origine = entry.created_at
        self._attr_unique_id = f"{entry.entry_id}_abonnement_compteur"
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Appelée quand HA a ajouté le capteur : on programme les mises à jour."""
        # Toutes les 15 minutes pile (:00, :15, :30, :45) : le tableau Énergie compte par
        # heures, donc à chaque heure pleine la valeur enregistrée est exacte.
        self.async_on_remove(
            async_track_time_change(self.hass, self._mise_a_jour, minute=[0, 15, 30, 45], second=0)
        )

    @callback
    def _mise_a_jour(self, _maintenant: Any) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return compteur_kwh(dt_util.utcnow(), self._origine)
