# ⚡ Tesla Smart Charge

[English](README.md) | [Français](README.fr.md)

[](https://github.com/hacs/integration)
[](https://opensource.org/licenses/MIT)
[](https://www.home-assistant.io/)

**Optimisez la recharge de votre Tesla selon les tarifs dynamiques d'electricite.** Cette integration Home Assistant planifie automatiquement la recharge pendant les plages les moins cheres, tout en garantissant que la voiture soit prete a l'heure voulue.

-----

## ✨ Fonctionnalites principales

  * **Optimisation en deux etapes :**
    1.  **Priorite readiness :** Atteint votre `Min. SOC at Ready Time` avant `Departure Time`.
    2.  **Recharge bonus "Cheap" :** Continue vers `Target SOC (Low Rate)` uniquement sur les plages de prix tres bas, sans contrainte horaire.
  * **Sources tarifaires flexibles :** Support des attributs de capteur, endpoints REST (JSON) et prix spot bruts (CU4 Particulier TTC).
  * **Sensors de marche pour dashboard/ticker :** Expose le prix spot actuel, la variation vs le slot precedent, la tendance court terme, le prochain creux significatif et le niveau relatif du prix courant.
  * **Automatisation intelligente :** Augmente automatiquement la limite de charge Tesla de `+1%` si necessaire pour reveiller la voiture et demarrer une session.
  * **Dashboard pret a l'emploi :** Service integre pour generer une vue Lovelace dediee avec integration `ApexCharts`.

-----

## 🛠 Prerequis

1.  **Integration Tesla :** Une integration Tesla active (officielle ou custom) fournissant SOC, amperage, switch de charge et etat du cable.
2.  **Donnees tarifaires :** Un capteur ou une API qui fournit les prix a venir.
3.  **Frontend (optionnel) :** Installer `ApexCharts Card` et `HTML Template Card` via HACS (`Frontend`) pour une meilleure visualisation et le support de `custom:html-template-card`.

-----

## 🚀 Installation

### Option 1 : HACS (recommande)

1.  Ouvrez **HACS** > **Integrations**.
2.  Cliquez sur les 3 points (en haut a droite) > **Custom repositories**.
3.  Collez l'URL de ce repo et choisissez **Integration** comme categorie.
4.  Cliquez sur **Install** puis **Restart** Home Assistant.

### Option 2 : Manuel

1.  Copiez le dossier `tesla_smart_charge` dans `/config/custom_components/`.
2.  **Redemarrez** Home Assistant.

-----

## ⚙️ Configuration

1.  Allez dans **Settings** > **Devices & Services** > **Add Integration**.
2.  Recherchez **Tesla Smart Charge**.
3.  **Mapping des entites :** Mappez les capteurs Tesla (SOC, limite de charge, amperage, etc.).
4.  **Constantes :** Definissez la capacite batterie (kWh), l'efficacite vehicule (Wh/km) et la puissance max (kW).

-----

## 📊 Entites principales

| Icon | Type d'entite | Nom | Usage |
| :--- | :--- | :--- | :--- |
| 🔢 | **Number** | `Min. SOC at Ready Time` | Niveau batterie cible pour le depart. |
| 🕒 | **Number** | `Departure Time` | Echeance pour atteindre le SOC minimum. |
| 💰 | **Number** | `Price Limit Threshold` | Prix plafond pour la recharge "Bonus". |
| ⚡ | **Switch** | `Enable Smart Charging` | Interrupteur principal de l'optimiseur. |
| 🛰️ | **Binary Sensor** | `Smart Charging Status` | Actif si cable branche et planification Tesla desactivee. |

-----

## 📈 Sensors "Marche"

Ces sensors sont pensés pour un affichage de type ticker ou salle de marche, avec un contexte immediat plutot qu'une simple liste de prix bruts.

| Nom | Type | Valeur principale | Attributs utiles |
| :--- | :--- | :--- | :--- |
| `Current Spot Price` | Sensor | Prix spot courant en `EUR/kWh` | `start`, `end`, `source` |
| `Price Change vs Previous Slot` | Sensor | Ecart absolu vs le slot precedent | `delta_percent`, `direction`, `current_price`, `previous_price` |
| `Short-Term Price Trend` | Sensor | `up`, `down` ou `stable` | `current_price`, `delta_vs_previous`, `price_level` |
| `Next Significant Low` | Timestamp Sensor | Debut du prochain vrai creux exploitable | `end`, `price`, `duration_minutes` |
| `Current Price Level` | Sensor | `very_low`, `low`, `normal`, `high`, `very_high` | `percentile`, `status`, `current_price` |

Exemple d'affichage synthétique :

```text
SPOT 0.164 EUR/kWh  DELTA -0.012  TREND down  NEXT LOW 11:30  STATUS cheap
```

-----

## 🛠 Services

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

## 💡 Notes techniques

> [!IMPORTANT]
> **Controlabilite :** le capteur `Smart Charging Status` doit etre a `True` pour que l'integration fonctionne. Cela demande que la voiture soit **branchee** et que la **planification de charge Tesla interne soit desactivee** (pour eviter les conflits).

  * **Prix spot :** Les prix du lendemain sont recuperes apres `13:10` heure locale. L'optimiseur regarde jusqu'a 48h pour trouver les meilleurs slots.
  * **Variation vs slot precedent :** Les analytics conservent le contexte du slot precedent pour pouvoir calculer un delta utile au ticker.
  * **Tendance court terme :** La tendance est calculee sur plusieurs slots afin d'eviter de surinterpreter une seule variation de 15 minutes.
  * **Prochain creux significatif :** Ce n'est pas uniquement le minimum absolu; l'algorithme cherche d'abord un vrai creux local exploitable, puis etend la fenetre basse contigue.
  * **Niveau relatif :** Le statut `very_low` a `very_high` est derive d'un percentile calcule sur la journee du slot courant.
  * **Efficacite :** Les calculs utilisent les valeurs `Wh/km` et `kWh` pour estimer la duree necessaire afin d'atteindre les cibles.
  * **Format JSON :** L'integration attend une liste d'objets avec timestamps (`start`, `end`) et une cle `price`.

-----

## 🤝 Contribuer

Feedback et Pull Requests bienvenus. Ouvrez un issue pour tout bug ou demande de fonctionnalite.
