# Tesla Smart Charge

[English](README.md) | [Français](README.fr.md)

[](https://github.com/hacs/integration)
[](https://opensource.org/licenses/MIT)
[](https://www.home-assistant.io/)

**Optimisez la recharge de votre Tesla selon les tarifs dynamiques d'electricite.** Cette integration Home Assistant planifie automatiquement la recharge pendant les plages les moins cheres, tout en garantissant que la voiture soit prete a l'heure voulue.

-----

## Fonctionnalites principales

  * **Optimisation en deux etapes :**
    1.  **Priorite readiness :** Atteint votre `Minimum SOC` avant `Ready By Hour`.
    2.  **Recharge bonus "Cheap" :** Continue vers `SOC If Cheap` uniquement sur les plages de prix tres bas, sans contrainte horaire.
  * **Sources tarifaires flexibles :** Support des attributs de capteur, endpoints REST (JSON) et prix spot bruts (CU4 Particulier TTC).
  * **Automatisation intelligente :** Augmente automatiquement la limite de charge Tesla de `+1%` si necessaire pour reveiller la voiture et demarrer une session.
  * **Dashboard pret a l'emploi :** Service integre pour generer une vue Lovelace dediee avec integration `ApexCharts`.

-----

## Prerequis

1.  **Integration Tesla :** Une integration Tesla active (officielle ou custom) fournissant SOC, amperage, switch de charge et etat du cable.
2.  **Donnees tarifaires :** Un capteur ou une API qui fournit les prix a venir.
3.  **Frontend (optionnel) :** Installer `ApexCharts Card` via HACS pour une meilleure visualisation sur le dashboard.

-----

## Installation

### Option 1 : HACS (recommande)

1.  Ouvrez **HACS** > **Integrations**.
2.  Cliquez sur les 3 points (en haut a droite) > **Custom repositories**.
3.  Collez l'URL de ce repo et choisissez **Integration** comme categorie.
4.  Cliquez sur **Install** puis **Restart** Home Assistant.

### Option 2 : Manuel

1.  Copiez le dossier `tesla_smart_charge` dans `/config/custom_components/`.
2.  **Redemarrez** Home Assistant.

-----

## Configuration

1.  Allez dans **Settings** > **Devices & Services** > **Add Integration**.
2.  Recherchez **Tesla Smart Charge**.
3.  **Mapping des entites :** Mappez les capteurs Tesla (SOC, limite de charge, amperage, etc.).
4.  **Constantes :** Definissez la capacite batterie (kWh), l'efficacite vehicule (Wh/km) et la puissance max (kW).

-----

## Entites principales

| Icon | Type d'entite | Nom | Usage |
| :--- | :--- | :--- | :--- |
| 1 | **Number** | `Minimum SOC By Ready Time` | Niveau batterie cible pour le depart. |
| 2 | **Number** | `Ready By Hour` | Echeance pour atteindre le SOC minimum. |
| 3 | **Number** | `Cheap Price Threshold` | Prix plafond pour la recharge "Bonus". |
| 4 | **Switch** | `Smart Charging Enabled` | Interrupteur principal de l'optimiseur. |
| 5 | **Binary Sensor** | `Module Charge Controllable` | Actif si cable branche et planification Tesla desactivee. |

-----

## Services

| Service | Description |
| :--- | :--- |
| `reoptimize` | Force un recalcul du planning de charge. |
| `apply_control` | Force l'etat actuel (demarrage/arret) vers le vehicule. |
| `install_dashboard_template` | Genere un fichier dashboard YAML dans la config. |

**Exemple d'installation du dashboard :**

```yaml
service: tesla_smart_charge.install_dashboard_template
data:
  filename: dashboards/tesla_smart_charge.yaml
  # existing_dashboard_filename: ui-lovelace.yaml (Optionnel)
```

-----

## Notes techniques

> [!IMPORTANT]
> **Controlabilite :** le capteur `Module Charge Controllable` doit etre a `True` pour que l'integration fonctionne. Cela demande que la voiture soit **branchee** et que la **planification de charge Tesla interne soit desactivee** (pour eviter les conflits).

  * **Prix spot :** Les prix du lendemain sont recuperes apres `13:10` heure locale. L'optimiseur regarde jusqu'a 48h pour trouver les meilleurs slots.
  * **Efficacite :** Les calculs utilisent les valeurs `Wh/km` et `kWh` pour estimer la duree necessaire afin d'atteindre les cibles.
  * **Format JSON :** L'integration attend une liste d'objets avec timestamps (`start`, `end`) et une cle `price`.

-----

## Contribuer

Feedback et Pull Requests bienvenus. Ouvrez un issue pour tout bug ou demande de fonctionnalite.
