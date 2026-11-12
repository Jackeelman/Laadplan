# Laadplanner

Eigen EV-module voor Home Assistant, naast Omnibattery. Plant wanneer de auto laadt (groen of in gekozen kwartieren) en rekent mee wat een dynamisch contract had gekost.

**Fase 1 = schaduwmodus.** De schakelaar `switch.laadplanner_sturing_actief` staat standaard **uit**: de module plant en rekent, maar raakt de laadpaal niet aan.

## Wat hij wel en niet doet

- Zet alleen de **laadmodus** (`Groen` / `Handmatig`) en **aan/uit** van de IQ-lader, en alleen als de sturing aan staat.
- Verandert **nooit de laadstroom**: dat kan niet tijdens het laden. Hij rekent met het vermogen dat de paal in eerdere sessies haalde.
- De fasekeuze (1/3) laat hij aan de paal.
- Schakelt de paal hooguit eens per 2 minuten.
- Is het doel bereikt terwijl de paal op `Handmatig` laadt, dan zet hij de paal uit. Op `Groen` laat hij de paal met rust.
- Het vermogen van de paal komt traag uit de Enphase-cloud; dat wordt alleen gebruikt om het gemiddelde laadvermogen te leren.

## Installeren

**Handmatig:** kopieer `custom_components/laadplanner` naar `/config/custom_components/laadplanner` en herstart HA.

**Via HACS:** voeg `https://github.com/Jackeelman/Laadplan` in HACS toe als *Custom repository* (type Integratie) en installeer *Laadplanner*.

Daarna: **Instellingen → Apparaten en diensten → Integratie toevoegen → Laadplanner**. De velden zijn al ingevuld met jouw entiteiten:

| Veld | Standaard |
| --- | --- |
| Laadtoestand auto | `sensor.fordpass_wf0rpbef9tsk88764_soc` |
| Auto aangesloten | `binary_sensor.iq_ev_charger_1219_ingeplugd` |
| Prijssensor | `sensor.nordpool_kwh_nl_eur_3_10_021` (later Zonneplan ONE) |
| Zon resterend vandaag / morgen | `sensor.energy_production_today_remaining_2` / `sensor.energy_production_tomorrow_2` |
| P1 import / export | `sensor.meterkast_p1_meter_hw_energie_import` / `_export` |
| Laadmodus / aan-uit | `select.iq_ev_charger_1219_laadmodus` / `switch.iq_ev_charger_1219` |
| Laadvermogen (optioneel) | `sensor.iq_ev_charger_1219_vermogen` |

## Na installatie instellen

1. **Tarieven** (onder Configuratie van het apparaat Laadplanner), in €/kWh incl. btw:
   - `Vast tarief inkoop` en `Vast tarief teruglevering`: uit je huidige contract.
   - `Dynamisch opslag inkoop`: wat er bovenop de Nord Pool-prijs komt (energiebelasting, inkoopvergoeding). Let op: de Nord Pool-sensor bevat al 21% btw over de kale prijs.
   - `Dynamisch aftrek teruglevering`: wat de leverancier van de terugleverprijs afhoudt.
   Zolang deze op 0 staan, kloppen de kostensensoren niet.
2. **Doel-SoC** (80%) en **Klaar om** (07:00).
3. **Strategie**: `Automatisch` kiest zelf tussen Groen, Groen + aanvullen en Kwartieren.

## Koppeling met Omnibattery

In Omnibattery bij het uitgesloten apparaat *IQ-lader*:

- **Solar Surplus** aan: de accu wijkt voor de auto.
- **Resterende vraag**: `sensor.laadplanner_resterende_vraag`.
- **Aanwezigheid**: `binary_sensor.iq_ev_charger_1219_ingeplugd`.

## Entiteiten

| Entiteit | Inhoud |
| --- | --- |
| `sensor.laadplanner_plan` | Gekozen stand; attributen: reden, kwartieren, haalbaar, nu_laden |
| `sensor.laadplanner_resterende_vraag` | kWh nodig tot het doel (incl. laadverlies) |
| `sensor.laadplanner_volgende_start` | Eerstvolgend laadkwartier |
| `sensor.laadplanner_kosten_vast_vandaag` / `_maand` | Werkelijk verbruik × vast tarief |
| `sensor.laadplanner_kosten_dynamisch_vandaag` / `_maand` | Zelfde verbruik × dynamische prijs |
| `sensor.laadplanner_verschil_dynamisch_maand` | Wat dynamisch deze maand had gescheeld (positief = dynamisch goedkoper) |
| `select.laadplanner_strategie`, `select.laadplanner_contract` | Instellingen |
| `number.laadplanner_doel_soc`, `time.laadplanner_deadline` | Doel en deadline |
| `time.laadplanner_laden_vanaf` | Vanaf hoe laat 's nachts geladen mag worden (standaard 00:00) |
| `switch.laadplanner_sturing_actief` | Uit = schaduwmodus |

## Overstappen naar sturen (fase 3)

Eerst de EV-sturing in SlimLaden op Homey uitzetten, dan pas `switch.laadplanner_sturing_actief` aan. Nooit twee systemen tegelijk aan de laadpaal of de accu's.

## Bekende beperkingen

- De zonvoorspelling geeft alleen dagtotalen. Het deel van morgen vóór de deadline wordt lineair geschat over 08:00–17:00.
- Bij een vast contract met één tarief kiest hij nachtkwartieren vanaf `Laden vanaf` (standaard 00:00) tot de deadline. Is die nacht te kort, dan vult hij aan met de avondkwartieren direct ervoor.
- `Laadvermogen (startwaarde)` wordt alleen gebruikt tot de module zelf het echte vermogen van de paal heeft geleerd.

## Tests

```
pip install pytest-homeassistant-custom-component
pytest
```
