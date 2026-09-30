"""Téléchargement et lecture d'une grille de prix EDF.

Utilisé à deux endroits : le formulaire de configuration (pour proposer uniquement les
options et puissances qui existent vraiment) et le coordinator (mises à jour régulières).
"""

from __future__ import annotations

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import OFFRES
from .historique import Grille
from .parsers import parse_pdf


class ErreurTelechargement(Exception):
    """Le PDF n'a pas pu être téléchargé (réseau, site EDF indisponible...)."""


class ErreurLecture(Exception):
    """Le PDF a été téléchargé mais on n'a pas su le lire (mise en page modifiée ?)."""


async def async_lire_grille(hass: HomeAssistant, offre: str) -> Grille:
    """Télécharge le PDF de l'offre puis le lit."""
    # Session HTTP partagée par tout Home Assistant (ne pas utiliser `requests` ici :
    # il est bloquant et gèlerait HA pendant le téléchargement).
    session = async_get_clientsession(hass)

    try:
        # Timeout explicite : sans lui, un serveur qui ne répond pas ferait attendre
        # très longtemps.
        async with session.get(
            OFFRES[offre]["url"], timeout=aiohttp.ClientTimeout(total=30)
        ) as reponse:
            reponse.raise_for_status()  # lève une erreur si le code HTTP n'est pas 2xx
            pdf_bytes = await reponse.read()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ErreurTelechargement(f"téléchargement impossible : {err}") from err

    # Lire un PDF est un travail bloquant : on l'envoie dans un thread séparé avec
    # async_add_executor_job pour ne jamais geler la boucle asynchrone de HA.
    try:
        return await hass.async_add_executor_job(parse_pdf, offre, pdf_bytes)
    except Exception as err:  # noqa: BLE001
        # On attrape large volontairement : la bibliothèque de lecture de PDF peut lever
        # presque n'importe quelle erreur si EDF change la mise en page.
        raise ErreurLecture(f"PDF illisible (mise en page modifiée ?) : {err}") from err
