"""Assistant de configuration (Paramètres > Appareils et services > Ajouter une intégration).

Trois questions, dans l'ordre : le contrat (offre), l'option tarifaire, la puissance.
Les choix proposés à chaque étape dépendent des précédents et viennent de la grille EDF
actuelle, lue en direct : on ne propose donc que des combinaisons qui existent vraiment.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import ErreurLecture, ErreurTelechargement, async_lire_grille
from .const import CONF_OFFRE, CONF_OPTION, CONF_PUISSANCE, DOMAIN, OFFRES, OPTIONS
from .historique import Grille

# SelectOptionDict sépare ce que l'utilisateur VOIT (label) de ce qui est STOCKÉ (value).
OFFRES_SELECT = [
    SelectOptionDict(value=cle, label=offre["nom"]) for cle, offre in OFFRES.items()
]


def _menu(options: list[SelectOptionDict]) -> SelectSelector:
    """Liste déroulante à choix unique."""
    return SelectSelector(SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN))


class EdfOffresMarcheConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gère le formulaire de configuration."""

    # Numéro de version du format des données stockées (utile pour de futures migrations).
    VERSION = 1

    def __init__(self) -> None:
        # Réponses et données gardées d'une étape à la suivante.
        self._offre: str | None = None
        self._grille: Grille | None = None
        self._option: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape 1 : choix du contrat. HA l'appelle 2 fois : d'abord sans réponse (afficher
        le formulaire), puis avec les réponses de l'utilisateur (les valider)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            offre = user_input[CONF_OFFRE]
            # On lit tout de suite la grille EDF : ça teste la connexion ET ça permet de
            # ne proposer ensuite que les options et puissances qui existent.
            try:
                self._grille = await async_lire_grille(self.hass, offre)
            except ErreurTelechargement:
                errors["base"] = "cannot_connect"
            except ErreurLecture:
                errors["base"] = "pdf_illisible"
            else:
                self._offre = offre
                return await self.async_step_option()

        schema = vol.Schema({vol.Required(CONF_OFFRE): _menu(OFFRES_SELECT)})
        return self.async_show_form(
            step_id="user",
            # Après une erreur, on remet la réponse déjà choisie dans le formulaire.
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_option(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape 2 : choix de l'option tarifaire (Base, Heures Creuses, Week-End...)."""
        if self._grille is None or self._offre is None:
            return await self.async_step_user()

        # Options prévues pour ce contrat ET présentes dans la grille lue.
        disponibles = [o for o in OFFRES[self._offre]["options"] if o in self._grille.tarifs]

        if user_input is not None:
            self._option = user_input[CONF_OPTION]
            return await self.async_step_puissance()

        # Une seule option possible : inutile de poser la question.
        if len(disponibles) == 1:
            self._option = disponibles[0]
            return await self.async_step_puissance()

        schema = vol.Schema(
            {
                vol.Required(CONF_OPTION): _menu(
                    [SelectOptionDict(value=o, label=OPTIONS[o]["libelle"]) for o in disponibles]
                )
            }
        )
        return self.async_show_form(step_id="option", data_schema=schema)

    async def async_step_puissance(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape 3 : choix de la puissance souscrite (celles qui existent pour cette option)."""
        if self._grille is None or self._offre is None or self._option is None:
            return await self.async_step_user()

        if user_input is not None:
            # Le formulaire renvoie du texte : on convertit la puissance en entier une
            # bonne fois pour toutes (elle sert de clé dans les tarifs lus dans le PDF).
            puissance = int(user_input[CONF_PUISSANCE])

            # Identifiant unique de CETTE combinaison : empêche d'ajouter deux fois la
            # même configuration (ex. Zen Online, Base, 6 kVA).
            await self.async_set_unique_id(f"{self._offre}_{self._option}_{puissance}")
            self._abort_if_unique_id_configured()

            nom = OFFRES[self._offre]["nom"]
            return self.async_create_entry(
                title=f"{nom} {puissance} kVA ({OPTIONS[self._option]['titre']})",
                data={
                    CONF_OFFRE: self._offre,
                    CONF_OPTION: self._option,
                    CONF_PUISSANCE: puissance,
                },
            )

        puissances = sorted(self._grille.tarifs[self._option])
        schema = vol.Schema(
            {
                vol.Required(CONF_PUISSANCE): _menu(
                    # Un SelectSelector stocke toujours du TEXTE : la valeur est str(p).
                    [SelectOptionDict(value=str(p), label=f"{p} kVA") for p in puissances]
                )
            }
        )
        return self.async_show_form(step_id="puissance", data_schema=schema)
