"""Point d'entrée de l'intégration : c'est le premier fichier que Home Assistant charge.

Il ne fait pas le travail lui-même : il prépare le terrain (création du coordinator,
premier chargement des données) puis délègue l'affichage à sensor.py.
"""

# Active une gestion plus souple des annotations de type (les ": ConfigEntry" ci-dessous).
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CONF_OFFRE, DOMAIN
from .coordinator import STORAGE_VERSION, EdfOffresMarcheCoordinator, cle_stockage

# Types d'entités créés par l'intégration : uniquement des capteurs (sensor.py).
PLATFORMS = [Platform.SENSOR]

# Alias de type : "un ConfigEntry qui transporte un EdfOffresMarcheCoordinator".
# N'a aucun effet à l'exécution, sert seulement à l'éditeur (autocomplétion, erreurs).
type EdfOffresMarcheConfigEntry = ConfigEntry[EdfOffresMarcheCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: EdfOffresMarcheConfigEntry) -> bool:
    """Démarre une instance de l'intégration (appelée par HA, jamais par nous)."""
    coordinator = EdfOffresMarcheCoordinator(hass, entry)

    # Premier téléchargement immédiat. En cas d'échec, HA réessaiera plus tard tout seul
    # (ConfigEntryNotReady) au lieu de laisser l'intégration à moitié démarrée.
    await coordinator.async_config_entry_first_refresh()

    # On range le coordinator sur l'entry : sensor.py le récupérera avec entry.runtime_data.
    entry.runtime_data = coordinator

    # Demande à HA de charger sensor.py pour cette entry.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EdfOffresMarcheConfigEntry) -> bool:
    """Arrête l'intégration (suppression ou rechargement par l'utilisateur)."""
    # Décharge les plateformes ; renvoie True si tout s'est bien passé.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: EdfOffresMarcheConfigEntry) -> None:
    """Appelée quand l'utilisateur SUPPRIME l'intégration : on efface l'historique enregistré."""
    offre = entry.data[CONF_OFFRE]
    autres = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id and e.data.get(CONF_OFFRE) == offre
    ]
    # Le fichier est partagé par toutes les entrées d'une même offre : on ne l'efface
    # que si c'était la dernière.
    if not autres:
        await Store(hass, STORAGE_VERSION, cle_stockage(offre)).async_remove()
