# EDF Offres de marché pour Home Assistant

Intégration Home Assistant qui lit les **grilles de prix publiques d'EDF** (les PDF de leurs
offres de marché) et en fait des capteurs : abonnement, prix du kWh, et un abonnement
utilisable dans le **tableau Énergie**.

> ⚠️ Intégration **non officielle**, sans lien avec EDF. Les prix sont ceux des grilles publiées
> par EDF « pour toute nouvelle souscription » : vérifiez toujours avec votre contrat ou votre
> facture avant de vous y fier pour un calcul financier.

Les **tarifs réglementés** (Tarif Bleu : Base, HP/HC, Tempo) ne sont pas gérés ici : l'intégration
[hass-tarif-edf](https://github.com/delphiki/hass-tarif-edf) s'en occupe très bien.

## Ce que fait l'intégration

- L'utilisateur **choisit son contrat, son option tarifaire et sa puissance** dans l'interface.
  Seules les combinaisons qui existent dans la grille EDF du moment sont proposées.
- Les tarifs sont relus **toutes les 6 heures**.
- **Un nouveau tarif ne s'applique qu'à sa date d'entrée en vigueur**, même si EDF publie la
  grille à l'avance : l'intégration lit la date « Applicable à compter du… », garde chaque
  grille en mémoire et bascule à minuit le jour J. Le prochain tarif est annoncé dans les
  attributs des capteurs (`prochaine_date_application`, `prochaine_valeur`).
- Si le site d'EDF est en panne ou si un PDF devient illisible, les derniers tarifs enregistrés
  restent utilisés pendant 14 jours (avec un avertissement dans les journaux), puis les capteurs
  deviennent « indisponibles » plutôt que d'afficher des tarifs trop anciens.

## Contrats pris en charge

| Contrat | Options | État de la vérification |
|---|---|---|
| Zen Online | Base, Heures Creuses | ✅ lecture vérifiée sur les tableaux du vrai PDF |
| Zen Fixe | Base, Heures Creuses | ✅ lecture vérifiée sur les tableaux du vrai PDF (cellules fusionnées gérées) |
| Zen Week-End | Week-End, Heures Creuses + WE, Flex | ⚠️ écrit d'après la description du PDF, à confirmer sur le vrai fichier |
| Zen Week-End Plus | WE + jour choisi, Heures Creuses + WE + jour choisi | ⚠️ idem |
| Zen Estival | Heures super creuses été / hiver | ⚠️ idem |
| Vert Électrique | Base, Heures Creuses | ⚠️ idem |
| Vert Électrique Week-End | Week-End, Heures Creuses + WE | ⚠️ idem |
| Vert Électrique Auto | Heures Creuses | ⚠️ idem |
| Vert Électrique Régional | Base, Heures Creuses | ⚠️ idem |

Pour les contrats marqués ⚠️, la lecture est protégée par des garde-fous (valeurs plausibles,
« heures creuses ≤ heures pleines »…) : en cas de doute, l'intégration **échoue avec un message
clair** plutôt que d'afficher de faux tarifs. Pour vérifier un contrat sur votre installation,
lancez `python outils/verifier_pdf.py` (voir plus bas) et ouvrez une *issue* avec le rapport.

## Installation

### Avec HACS (dépôt personnalisé)

1. HACS → menu ⋮ → **Dépôts personnalisés**.
2. Ajoutez `https://github.com/Melvilh/ha-edf-offres-marche`, catégorie **Intégration**.
3. Installez **EDF Offres de marché**, puis redémarrez Home Assistant.
4. **Paramètres → Appareils et services → Ajouter une intégration → EDF Offres de marché**.

### Manuellement

Copiez le dossier `custom_components/edf_tarifs_offres_marche` dans le dossier
`config/custom_components/` de Home Assistant, puis redémarrez.

## Capteurs créés

Pour chaque configuration (un contrat + une option + une puissance) :

| Capteur | Unité | Détail |
|---|---|---|
| Abonnement mensuel | € | TTC, tel qu'écrit dans la grille |
| Prix du kWh (un capteur par colonne de l'option : unique, heures pleines / creuses, semaine / week-end…) | €/kWh | TTC |
| Abonnement journalier | € | abonnement annuel (×12) réparti sur 365 ou 366 jours |
| Abonnement – prix pour le tableau Énergie | €/kWh | voir ci-dessous |
| Abonnement – compteur pour le tableau Énergie | kWh | voir ci-dessous |

Chaque capteur de tarif expose aussi en attributs : `date_application`, `tarif_provisoire`,
`derniere_lecture_pdf` et, quand une grille future est déjà publiée, `prochaine_date_application`
et `prochaine_valeur`.

## Mettre l'abonnement dans le tableau Énergie

Le tableau Énergie n'a pas de champ « abonnement ». L'intégration fournit donc un **compteur
d'énergie fictif** qui avance de 0,001 kWh toutes les 24 h, et un « prix du kWh » associé tel que
*coût d'une journée = abonnement d'une journée*. L'abonnement apparaît alors sur **sa propre ligne** :

1. **Paramètres → Tableaux de bord → Énergie → Consommation du réseau → Ajouter une consommation.**
2. *Énergie consommée* : **… Abonnement – compteur pour le tableau Énergie**.
3. *Utiliser une entité avec le prix actuel* : **… Abonnement – prix pour le tableau Énergie**.
4. Enregistrer.

Le compteur est minuscule (0,001 kWh par jour) pour ne pas fausser vos totaux de consommation.
La constante `KWH_PAR_JOUR_ABONNEMENT` de `const.py` permet de changer cette valeur. Ces deux
capteurs sont acceptés par les règles de validation du tableau Énergie de Home Assistant
(vérifié par un test automatique).

## Limites connues

- Les **majorations** (auto-producteur avec injection, absence de compteur Linky, absence de
  transmission d'index) ne sont pas ajoutées à l'abonnement.
- **Zen Week-End Flex** : les prix « jour Éco » et « jour Sobriété » sont affichés tous les deux ;
  l'intégration ne sait pas quels jours sont des jours Sobriété.
- **Zen Estival** : les six prix (été / hiver, super creuses / creuses / pleines) sont affichés ;
  il n'y a pas encore de capteur « prix en vigueur maintenant ».
- La grille lue est celle « pour toute nouvelle souscription » : un contrat plus ancien peut avoir
  une date de révision différente.
- Si la date « Applicable à compter du… » n'est pas trouvée dans un PDF, ses tarifs sont appliqués
  immédiatement (un avertissement est écrit dans les journaux).
- Toute la lecture dépend de la mise en page des PDF d'EDF : si elle change, l'intégration le
  signale au lieu de deviner.

## Développement

```bash
pip install -r requirements_test.txt
pytest                          # tests unitaires et tests dans un vrai Home Assistant de test
python outils/verifier_pdf.py   # lit les vraies grilles EDF et écrit outils/sortie_verification.txt
```
