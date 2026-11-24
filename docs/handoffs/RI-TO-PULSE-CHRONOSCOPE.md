# HANDOFF — RI → Pulse / Chronoscope

**Destinazione:** [OpenRGD/rgd-pulse](https://github.com/OpenRGD/rgd-pulse), chat Pulse/Chronoscope.
**Riferimenti:** [PULSE-0.3C baseline](https://github.com/OpenRGD/rgd-pulse/blob/main/docs/RELEASE-PULSE-0.3C.md), [PULSE 0.4B PR #13](https://github.com/OpenRGD/rgd-pulse/pull/13), [RI PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4).
**Stato:** handoff di interoperabilità read-only; nessun firmware da flashare.

## Stato reale da preservare

Pulse/Chronoscope Pico W ha una baseline fisicamente testata `0.3C`. La pagina K3 IMU riceve campioni **già accettati dalla Console** tramite `pulse-bridge` e li mostra con gli stati `RAW/STALE/N/A`. La finestra UI 800ms **non** è il TTL 3000ms della Console e non è una deadline di controllo; gli assi sensore restano non calibrati.

Il PULSE K2 “Chronons” e K4 “SYSTEM” devono dipendere dalle rispettive autorità reali; una osservazione RI non diventa automaticamente un Chronon, una misura Chronograf o telemetria motoria.

## Richiesta

1. **Non** sostituire il collegamento K3 Console→Pulse con RI. Evitare secondo lettore IMU, nuovi stream duplicati o un nuovo protocollo USB motivato solo dalla nascita di RI.
2. Considerare RI come fonte futura di **diagnostica read-only** (esistenza source evidence, hash/integrità, fonte, freshness, dropped observations, richiamo a sessione), eventualmente su una pagina K4 o Console se compatibile con gli stati esistenti.
3. Il display deve distinguere `source observed`, `hash locally verified`, `source/device unverified`, `simulated`, `stale` e `unknown` senza comprimere tutti gli stati in `LIVE`. Il firmware usa DTO bounded, niente payload video/audio o percorsi filesystem.
4. Se K2 mostra Chronons, richiedere **ricevute History/Chronograf realmente verificate**, non `ObservationRef` RI e non il solo timestamp del mini-PC.
5. Preservare protocollo PULSE/1 e PULSE/IMU-1, handshake/CRC, source/freshness e modalità Demo vs RAW. RI offline non deve alterare il K3 reale.
6. Non attribuire a Chronoscope il ruolo del clock manager: visualizzare il tempo non significa emettere AnchorRef64.

## Accettazione

I test e la baseline fisica 0.3C restano invariati; K3 Live→STALE continua dopo arresto publisher, il nuovo consumer opzionale non introduce jitter/memoria eccessiva, il payload RI non espone dati sensibili o media. Testare a parte nuovo firmware e nuovo host bridge solo quando una funzione reale è approvata.

**No:** USB access per RI, CAN, attuazione, stima di balance, Chronon inventati, promozione di fonti importate/sintetiche a fisiche.
