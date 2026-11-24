# HANDOFF — RI → RGD Perception (future repository)

**Destinazione prevista:** `OpenRGD/rgd-perception` (**non ancora presente su GitHub al momento di questo handoff**), futura chat Perception.
**Origine:** [RI PR #2](https://github.com/OpenRGD/rgd-reality-ingress/pull/2) (baseline storica v0.4), [RI PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4) (reference consumer candidate).
**Stato:** handoff di fondazione, non un migration già effettuata.

## Confine di proprietà

RI acquisisce/valida/indicizza osservazioni, riferimenti e provenienza. Perception consuma evidenze autorizzate e produce **risultati derivati** quali oggetti YOLO, marker ArUco, bounding boxes, pose, disparity/depth, tracking, fusioni visive e altre inferenze. Voice è proprietario dell'ASR del suo percorso conversazionale; non introdurre un secondo STT generale in Perception solo per consumare audio.

Il legacy v0.4 conserva `perception.py`, `fiducials.py`, `derivations.py`, `calibration.py` e CLI `derive/markers-*` come implementazione storica compatibile. Estrarre questi algoritmi **senza cancellare o ri-keyare** le evidenze esistenti.

## Richiesta al nuovo modulo

1. Definire un `PerceptionResult` candidate con `input_observation_refs[]`, processor/model/weights version+hash, parametri, calibration ref, CPU/GPU/location, task, output schema, confidence/uncertainty, status, data origin e tempo inferenza separato da tempo acquisizione.
2. Consumare la ref RI `v0.1-candidate` tramite adapter con autorizzazione ai media separata; un ref valido non è un bearer token per leggere file locali.
3. Preservare output derivati append-only, idempotenza/dedup e diagnostica di replay; nessuna mutazione dell'Envelope originale. Distinguere `unknown` da `not detected` e da `sensor unavailable`.
4. Implementare i provider con licenze e dipendenze proprie; annotare la compatibilità MIT/Apache/AGPL, specialmente Ultralytics. Split repo/process NON elimina automaticamente obblighi AGPL. Non includere modelli/pesi con diritto di redistribuzione incerto.
5. Definire un primo pilot **OCCHI** in cui il crop side-by-side A/B è deterministico, l'orientamento fisico è verificato e la geometria usa una revisione CAL candidate; output profondità non certificata finché i requisiti CAL non sono soddisfatti.
6. Non rendere RTX 5080 necessaria per la cattura: elaborazione locale essenziale e offload opzionale con canale autenticato, policy privacy, timeout, backpressure e fallback. Le inference remote non sono sorgenti di tempo canonico o azioni.
7. Nessun motore CAN/IMU device open, niente seconda camera acquisition, niente salvataggi History/Life o decisioni su `SELF`.

## Accettazione

Fixture deterministiche basate su synthetic observations e dati consentiti, vecchi 34 test RI preservati, compatibilità dei riferimenti `obs_*` legacy, fallback provider sconosciuto/offline, calibrazione assente, modello non disponibile e retrievable derived results. Prima della pubblicazione del nuovo repository si congela la licenza specifica e si documentano i third-party notices.

**Handoff per il momento:** nessuna PR Perception può essere aperta finché la repository non viene creata; l'implementazione resta nel perimetro dello sviluppo successivo, non nella PR RI #4.
