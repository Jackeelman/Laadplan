# Laadplanner

Eigen EV-module voor Home Assistant, naast Omnibattery. Plant wanneer de auto laadt (groen of in gekozen kwartieren) en rekent mee wat een dynamisch contract had gekost.

**Fase 1 = schaduwmodus.** De schakelaar `switch.laadplanner_sturing_actief` staat standaard **uit**: de module plant en rekent, maar raakt de laadpaal niet aan.

## Wat hij wel en niet doet

- Zet alleen de **laadmodus** (`Groen` / `Handmatig`) en **aan/uit** van de IQ-lader, en alleen als de sturing aan staat.
- Verandert **nooit de laadstroom**: dat kan niet tijdens het laden. Wel **rekent hij met de ingestelde laadstroom**: stroom × fasen × 230 V (16 A drie fasen = 11,04 kW), maal het deel dat de auto daar in eerdere laadbeurten echt van afnam (geleerd, start op 90%). Zet je de paal op een andere stroom, dan past het plan zich aan. Wisselingen korter dan 2 minuten negeert hij.
- De fasekeuze (1/3) laat hij aan de paal.
- Schakelt de paal hooguit eens per 2 minuten.
- **Laadgrens van de auto:** meldt de auto `COMPLETED` terwijl hij aangesloten is, dan geldt hij als vol, ook als de doel-SoC hoger staat of de SoC-sensor nog achterloopt. De resterende vraag gaat dan naar 0. Zet de laadgrens in de auto dus gelijk aan of hoger dan de doel-SoC als je tot het doel wilt laden. Een `COMPLETED` telt alleen als FordPass **na het aansluiten** ververst is; een oude melding van de vorige laadbeurt wordt genegeerd. Bij twijfel (bijv. net na een herstart van HA) plant hij gewoon laden.
- Is het doel bereikt terwijl de paal op `Handmatig` laadt, dan zet hij de paal uit. Op `Groen` laat hij de paal met rust.
- Het vermogen van de paal komt traag uit de Enphase-cloud; dat wordt alleen gebruikt om het gemiddelde laadvermogen te leren.

## Installeren

**Handmatig:** kopieer `custom_components/laadplanner` naar `/config/custom_components/laadplanner` en herstart HA.

**Via HACS:** voeg `https://github.com/Jackeelman/Laadplan` in HACS toe als *Custom repository* (type Integratie) en installeer *Laadplanner*.

Daarna: **Instellingen → Apparaten en diensten → Integratie toevoegen → Laadplanner**. De velden zijn vooraf ingevuld; vervang `jouw_vin` door het VIN in de naam van je eigen FordPass-sensoren:

| Veld | Standaard |
| --- | --- |
| Laadtoestand auto | `sensor.fordpass_jouw_vin_soc` |
| Auto aangesloten | `binary_sensor.iq_ev_charger_1219_ingeplugd` |
| Prijssensor | `sensor.nordpool_kwh_nl_eur_3_10_021` (later Zonneplan ONE) |
| Zon resterend vandaag / morgen | `sensor.energy_production_today_remaining_2` / `sensor.energy_production_tomorrow_2` |
| P1 import / export | `sensor.meterkast_p1_meter_hw_energie_import` / `_export` |
| Laadmodus / aan-uit | `select.iq_ev_charger_1219_laadmodus` / `switch.iq_ev_charger_1219` |
| Laadvermogen (optioneel) | `sensor.iq_ev_charger_1219_vermogen` |
| Ingestelde laadstroom (optioneel) | `number.auto_iq_ev_charger_1219_standaard_laadniveau` |
| Fasen laadpaal (optioneel) | `sensor.iq_ev_charger_1219_elektrische_fase` |
| Gebruikte laadstroom (optioneel) | `sensor.iq_ev_charger_1219_ampere_instellen` |
| Laadstatus auto (optioneel) | `sensor.fordpass_jouw_vin_elvehcharging` |
| Auto laatst vernieuwd (optioneel) | `sensor.fordpass_jouw_vin_lastrefresh` |
| Auto: laden pauzeren / starten (optioneel) | `button.fordpass_jouw_vin_evpause` / `button.fordpass_jouw_vin_evstart` |
| Vermogen thuisaccu (optioneel, W, + = ontladen) | `sensor.energy_battery_batterij_ontladen_batterij_laden_net_power` |

## Na installatie instellen

1. **Tarieven** (onder Configuratie van het apparaat Laadplanner), in €/kWh incl. btw:
   - `Vast tarief inkoop` en `Vast tarief teruglevering`: uit je huidige contract.
   - `Dynamisch opslag inkoop`: wat er bovenop de Nord Pool-prijs komt (energiebelasting, inkoopvergoeding). Let op: de Nord Pool-sensor bevat al 21% btw over de kale prijs.
   - `Dynamisch aftrek teruglevering`: wat de leverancier van de terugleverprijs afhoudt.
   Zolang deze op 0 staan, kloppen de kostensensoren niet.
2. **Doel-SoC** (80%) en **Klaar om** (07:00).
3. **Strategie**: `Automatisch` kiest zelf tussen Groen, Groen + aanvullen en Kwartieren.
4. **Pushmelding** (optioneel): vul bij Configureren onder *Meldingsdienst* je telefoon in, bv. `notify.mobile_app_eelphone`. Dan krijg je een melding als de auto niet wil laden. Zonder invulling komt de melding alleen in HA.

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

## Log en database

De module houdt de Home Assistant-database en het log klein:

- De kostensensoren tellen elke minuut mee, maar tonen hun waarde **eens per kwartier**. Dat zijn hooguit 96 regels per sensor per dag in plaats van honderden.
- De attributen van `sensor.laadplanner_plan` (reden, kwartieren, enz.) komen niet in de geschiedenis. Getallen worden afgerond op 0,1, zodat ze niet elke minuut een nieuwe regel opleveren.
- Instellingen en de kostentelling staan in een eigen klein bestand (`.storage`), niet in de database. Dat bestand wordt hooguit eens per 5 minuten geschreven.
- Lukt het sturen van de laadpaal niet, dan komt er **één** waarschuwing in het log, niet elke minuut. Werkt het weer, dan staat dat er ook (op info-niveau).

## Overstappen naar sturen (fase 3)

Eerst de EV-sturing in SlimLaden op Homey uitzetten (bijvoorbeeld de Homey-flow die de laadpaal stuurt uitschakelen), dan pas `switch.laadplanner_sturing_actief` aan. Nooit twee systemen tegelijk aan de laadpaal of de accu's.

## Aan- en uitzetten van de laadpaal

De Enphase-cloud meldt de stand van de laadpaal minuten te laat (getest 15-11-2026: laden begon 38 s na het startsein, de schakelaar in HA stond pas 4 minuten later op aan). Daarom:

- Na een startsein wacht de module tot 5 minuten op bevestiging voordat hij opnieuw "aan" stuurt.
- Moet het laden stoppen, dan stuurt hij "uit" zodra iets wijst op laden: de schakelaar, het laadvermogen, de laadstatus van de auto of zijn eigen laatste startsein. Dat herhaalt hij elke 2 minuten (hooguit 5 keer) zolang het laden nog zichtbaar is. De laadstatus van de auto telt alleen als FordPass ná het laatste stuursignaal ververst is; een oude "bezig met laden" wordt genegeerd.
- Laadt de paal na 5 keer "uit" nog steeds, dan stopt hij met sturen en zet hij één waarschuwing in het log.
- Die stopronde vervalt bij een **nieuwe sessie**: auto opnieuw ingestoken, of de paal opnieuw gestart (schakelaar ná de stop weer aan). Laat het vermogen of een verse FordPass-status na 30 minuten nog laden zien, dan begint hij ook een nieuwe ronde. Met 0 W en geen laadstatus blijft hij stil, zodat het log niet volloopt (gezien 23-11: na 5 keer "uit" om 07:00 bleef hij de hele ochtend stil en laadde de auto door tot 81%).
- **Vastgelopen start:** staat de schakelaar op aan terwijl er 6 minuten lang geen vermogen loopt en de auto geen laden meldt (gezien 23-11: auto `FAULT` bij het insteken, paal `FINISHING`, schakelaar de hele nacht "aan"), dan probeert hij opnieuw te starten met `enphase_ev.start_charging` en FordPass `evstart`, hooguit 2 keer met 5 minuten ertussen. Laat de P1-meter (zonder thuisaccu) zien dat de auto toch stroom neemt, dan telt dat als laden: de Enphase-cloud meldt soms 0 W terwijl de auto 12 kW laadt. Komt het laden later toch op gang, dan verdwijnt de melding in HA weer. Helpt dat niet, dan één melding in HA en, als ingesteld, een pushmelding: steek de stekker opnieuw in.
- De laadmodus (Groen/Handmatig) verandert hij hooguit eens per 15 minuten, behalve als er nú geladen moet worden. Elke wissel start of stopt de paal. Het plan wisselt bovendien pas naar "zon aanvullen" als de zon 25% van de vraag dekt, en blijft dat tot het onder 15% zakt.
- Stoppen wordt niet tegengehouden door de wachttijd van 2 minuten tussen schakelen; starten wel.
- De Enphase-cloud negeert een stopcommando voor een laadsessie die hij zelf nog niet kent (getest 15-11-2026: "uit" om 19:56:45 genegeerd, de cloud stond nog op gepauzeerd terwijl de auto op 11,7 kW laadde). Was "uit" verstuurd terwijl de cloud de paal nog niet als aan zag, dan stuurt de module het opnieuw zodra de cloud de paal wél als aan meldt.
- Na elk stuurcommando vraagt hij de Enphase-integratie (als die `start_live_stream` heeft) om een tijd lang snellere cloudupdates.
- Elk stuurcommando staat op info-niveau in het log ("Laadplanner: laadpaal aan/uit").
- Het deel dat de auto van het ingestelde vermogen opneemt, leert hij alleen als de paal op Handmatig staat (Groen kan op één fase laden).

## Terugvaloptie via de auto (FordPass)

Kent de Enphase-cloud de laadsessie niet, dan negeert de paal elk "uit", ook dat van de Enphase-app (gezien op 15-11, zie issue #10). Dan pauzeert de module de **auto** zelf via FordPass:

- **Wanneer:** 2,5 minuut na het eerste "uit" laadt de auto nog. Dat blijkt uit:
  - de **P1-meter, gecorrigeerd voor de thuisaccu**: het verbruik zonder accu is niet met minstens de helft van het laadvermogen gedaald sinds vlak voor de stop. Een accu die van het net laadt (tot 7,5 kW) telt dus niet als auto. Werkt niet als de auto op zon laadde.
  - of een **verse** laadstatus van FordPass (ververst na de stop).
  - Is het accuvermogen onbekend, dan zijn **beide** nodig: P1 én FordPass.
  - Op de Enphase-cloud wordt hierbij niet vertrouwd. Hooguit 2 keer per stop.
- **Nooit op pauze laten hangen:**
  - "Zelf gepauzeerd" wordt meteen opgeslagen en overleeft een herstart van HA.
  - Moet er weer geladen worden, dan eerst `evstart` op de auto, een minuut later de paal. `evstart` herhaalt hij elke 3 minuten tot de auto zichtbaar laadt; na 5 pogingen één waarschuwing en daarna elke 10 minuten. Als bewijs telt alleen het vermogen van de paal of een verse `IN_PROGRESS` van FordPass, **niet de P1-meter**: een accu die van het net laadt zou de pauze dan ten onrechte opheffen.
  - Is er nog energie nodig, dan drukt hij ongeacht het plan **anderhalf uur voor de deadline** altijd op `evstart`. Is het doel bereikt, dan blijft een pauze staan tot je de auto loskoppelt: opheffen zou de auto boven het doel laten doorladen terwijl de paal "uit" negeert.
  - Zet je de sturing uit, dan heft hij de pauze meteen op.
  - Koppel je de auto los, dan vervalt de pauze.
- **Knoppen niet beschikbaar** (bijvoorbeeld als de auto niet aangesloten is): dan slaat hij deze stap over en gebruikt hij alleen de paal. Kan hij een eigen pauze niet opheffen, dan komt er een waarschuwing.
- Het attribuut `auto_gepauzeerd` van `sensor.laadplanner_plan` laat zien of de module de auto heeft gepauzeerd.

## Veiligheidsstand van de paal (6 A)

Valt de paal terug op zijn veiligheidsstand (`safe_limit_active` op `sensor.iq_ev_charger_1219_ampere_instellen`, gezien 's nachts via wifi), dan rekent het plan met de stroom die de paal dan echt geeft (meestal 6 A) in plaats van het standaard laadniveau. Korte uitschieters (seconden) telt hij niet mee.

## Bekende beperkingen

- De zonvoorspelling geeft alleen dagtotalen. Het deel van morgen vóór de deadline wordt lineair geschat over 08:00–17:00.
- Bij een vast contract met één tarief kiest hij nachtkwartieren vanaf `Laden vanaf` (standaard 00:00) tot de deadline. Is die nacht te kort, dan vult hij aan met de avondkwartieren direct ervoor.
- `Laadvermogen (startwaarde)` wordt alleen gebruikt als de ingestelde laadstroom niet bekend is, en dan alleen tot de module zelf het echte vermogen van de paal heeft geleerd.
- De attributen `laadstroom_a`, `fasen` en `laadvermogen_kw` van `sensor.laadplanner_plan` laten zien waarmee gerekend wordt.

## Tests

```
pip install pytest-homeassistant-custom-component
pytest
```
