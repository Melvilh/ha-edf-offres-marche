"""Coordinator : lit régulièrement la grille EDF et partage le résultat avec les capteurs.

Un "coordinator" va chercher les données UNE seule fois à intervalle régulier, puis
tous les capteurs (sensor.py) lisent ce résultat partagé. Sans lui, chaque capteur
referait sa propre requête réseau.

Ce coordinator garde aussi un HISTORIQUE des grilles vues (voir historique.py) pour
n'appliquer un nouveau tarif qu'à sa date d'entrée en vigueur, même s'il est publié avant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ErreurLecture, ErreurTelechargement, async_lire_grille
from .const import CONF_OFFRE, CONF_OPTION, CONF_PUISSANCE, DOMAIN, PEREMPTION_JOURS
from .historique import (
    Grille,
    Selection,
    ajouter_grille,
    choisir_tarif,
    historique_depuis_json,
    historique_vers_json,
)

# Logger nommé d'après ce fichier (custom_components.edf_tarifs_offres_marche.coordinator) :
# dans les journaux de HA, on voit tout de suite d'où vient un message.
_LOGGER = logging.getLogger(__name__)

# Numéro de version du fichier de sauvegarde (utile si son format change un jour).
STORAGE_VERSION = 1


def cle_stockage(offre: str) -> str:
    """Nom du fichier de sauvegarde (dans .storage/) : un par offre."""
    return f"{DOMAIN}.{offre.lower()}"


@dataclass(frozen=True)
class EtatTarifs:
    """Ce que le coordinator partage avec les capteurs (son `data`)."""

    historique: tuple[Grille, ...]  # toutes les grilles connues, de la plus ancienne à la plus récente
    derniere_lecture: datetime | None  # dernier téléchargement réussi du PDF


class EdfOffresMarcheCoordinator(DataUpdateCoordinator[EtatTarifs]):
    """Récupère la grille de prix de l'offre choisie toutes les 6 heures."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({entry.title})",
            # Les tarifs EDF ne changent qu'une ou deux fois par an : 6 h est déjà large.
            # L'intervalle n'est volontairement pas configurable par l'utilisateur.
            update_interval=timedelta(hours=6),
            config_entry=entry,
        )
        self.offre: str = entry.data[CONF_OFFRE]
        self._store: Store = Store(hass, STORAGE_VERSION, cle_stockage(self.offre))
        self._historique: tuple[Grille, ...] = ()
        self._derniere_lecture: datetime | None = None
        self._date_absente_signalee = False

    async def _async_setup(self) -> None:
        """Appelée une seule fois, juste avant le premier rafraîchissement."""
        # On recharge l'historique enregistré lors des exécutions précédentes.
        sauvegarde = await self._store.async_load()
        if sauvegarde:
            self._historique = historique_depuis_json(sauvegarde["historique"])
            if sauvegarde.get("derniere_lecture"):
                self._derniere_lecture = datetime.fromisoformat(sauvegarde["derniere_lecture"])

        # Chaque nuit à 00:00:05 on relit l'historique (sans réseau) : c'est ce qui fait
        # basculer les capteurs sur un nouveau tarif PILE le jour de son entrée en vigueur,
        # sans attendre le prochain rafraîchissement (toutes les 6 h).
        self.config_entry.async_on_unload(
            async_track_time_change(
                self.hass, self._au_changement_de_jour, hour=0, minute=0, second=5
            )
        )

    async def _async_update_data(self) -> EtatTarifs:
        """Appelée par HA à chaque rafraîchissement ; son résultat devient self.data."""
        maintenant = dt_util.utcnow()

        try:
            grille = await async_lire_grille(self.hass, self.offre)
        except (ErreurTelechargement, ErreurLecture) as err:
            # Site EDF en panne ou PDF illisible : si on a déjà des tarifs récents en
            # mémoire, on continue de les utiliser (avec un avertissement) plutôt que de
            # rendre les capteurs indisponibles pour une simple panne temporaire.
            if self._donnees_encore_valables(maintenant):
                _LOGGER.warning("%s : on garde les derniers tarifs enregistrés", err)
                return self._etat_verifie()
            # UpdateFailed = "ce rafraîchissement a échoué, réessaie au prochain cycle".
            raise UpdateFailed(str(err)) from err

        if grille.date_effet is None and not self._date_absente_signalee:
            # Sans date, impossible de retarder un tarif publié à l'avance : la grille est
            # appliquée tout de suite. On le dit clairement (une seule fois).
            self._date_absente_signalee = True
            _LOGGER.warning(
                "Date d'entrée en vigueur introuvable dans le PDF %s : les tarifs sont "
                "appliqués dès leur lecture. Lancez outils/verifier_pdf.py et signalez-le.",
                self.offre,
            )

        self._historique = ajouter_grille(self._historique, grille)
        self._derniere_lecture = maintenant
        await self._store.async_save(
            {
                "historique": historique_vers_json(self._historique),
                "derniere_lecture": maintenant.isoformat(),
            }
        )
        return self._etat_verifie()

    def _donnees_encore_valables(self, maintenant: datetime) -> bool:
        """Vrai si on a des tarifs enregistrés et que leur dernière lecture est assez récente."""
        return bool(
            self._historique
            and self._derniere_lecture
            and maintenant - self._derniere_lecture <= timedelta(days=PEREMPTION_JOURS)
        )

    def _etat(self) -> EtatTarifs:
        return EtatTarifs(self._historique, self._derniere_lecture)

    def _etat_verifie(self) -> EtatTarifs:
        """Renvoie l'état, après avoir vérifié que NOTRE tarif existe dans les grilles."""
        etat = self._etat()
        option = self.config_entry.data[CONF_OPTION]
        puissance = self.config_entry.data[CONF_PUISSANCE]
        if choisir_tarif(etat.historique, dt_util.now().date(), option, puissance) is None:
            raise UpdateFailed(
                f"Aucun tarif {puissance} kVA / option {option} dans la grille EDF actuelle"
            )
        return etat

    def selection(self, option: str, puissance: int) -> Selection | None:
        """Tarif en vigueur AUJOURD'HUI pour cette option et cette puissance."""
        return choisir_tarif(self.data.historique, dt_util.now().date(), option, puissance)

    @callback
    def _au_changement_de_jour(self, _maintenant: datetime | None) -> None:
        """Prévient les capteurs de se recalculer (la date du jour a changé).

        On utilise async_update_listeners() et NON async_set_updated_data() : ce dernier
        déclarerait le dernier rafraîchissement « réussi » et rendrait les capteurs
        disponibles alors que le téléchargement vient peut-être d'échouer.
        """
        self.async_update_listeners()
