# HANDOFF — RI → Paky-01 Hardware / Acquisition

**Destinazione:** [italiarobotica/paky-01](https://github.com/italiarobotica/paky-01), chat hardware di Paky-01.
**Origine:** [Reality Ingress PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4), [RI-HOST-01 issue #5](https://github.com/OpenRGD/rgd-reality-ingress/issues/5).
**Stato:** proposta di integrazione, NON un comando di installazione su Paky-01.

## Contesto e proprietà

Reality Ingress v0.4 è stato recuperato e integrato in `main` come baseline sperimentale. Ingress possiede evidenza e provenienza; l'istanza Paky-01 possiede installazione fisica, binding dei sensori e configurazione host. Un **solo acquisition owner** può aprire ogni endpoint fisico.

Hardware già sperimentato: OCCHI SVPRO `32e4:2b10`, stereo USB side-by-side `2560×720 MJPEG @30fps` su collegamento diretto; Logitech C920 `046d:08e5` come vista ambientale distinta; WIT/CH340 IMU già letto da un publisher separato. La calibrazione OCCHI 35 coppie è un candidato sperimentale ([CAL PR #4](https://github.com/OpenRGD/rgd-calibration/pull/4)), non una misura metrica certificata. L'ordine fisico left/right non deve essere indovinato; per il montaggio capovolto ruotare ciascuna mezza vista indipendentemente quando l'adapter lo richiede.

## Richiesta a questa chat/repository

1. Verificare e dichiarare nel profilo dell'istanza *source UID persistente*, montaggio, `reference_frame_id`, versione del binding, identità del processo proprietario e stato di verifica per OCCHI e C920. Non dedurre identità stabile da `/dev/videoN`.
2. Concordare con RI-HOST-01 un **pilot opt-in e a durata limitata**: un solo camera publisher e subscriber RI in sola lettura; la cattura deve fermarsi o fallire chiaramente se la camera è occupata.
3. Aggiungere diagnostica di warm-up, frame incompleti, lacune/drop, USB disconnect/reconnect e restart sessione, con buffer e quote limitate; niente archiviazione continua per default.
4. Mantenere la semantica reale del vecchio adapter: `VideoCapture` decodifica e ricodifica JPEG; non descrivere i payload come byte MJPEG originali del bus.
5. Non modificare il lettore seriale IMU, il broker Console, il percorso Voice/microfono o alcuna interfaccia CAN. Foto/video di laboratorio, dati privati e credenziali rimangono **fuori dalle repository pubbliche**.

## Condizioni di accettazione

Sessione locale controllata su Ubuntu, un solo proprietario del device, osservazioni con ID/hash verificabili tramite RI, stato `live/stale` derivato da campioni autenticamente ricevuti, disconnect e rollback testati. Evidenza pubblicabile: metriche, log redatti, revisioni codice; **non** video o audio privati. Nessun movimento, nessun Chronon inventato e nessuna modifica a runtime già funzionanti durante il pilot.

## Invarianti inter-repo

Il consumer ref RI è ancora `ri.consumer-observation-ref.v0.1-candidate`: un riferimento a *evidenza effettivamente registrata*, non l'identità fisica del sensore né un nuovo schema di telemetria Paky-01. Il modello fisico e il sensore restano distinti dai soggetti osservati.
