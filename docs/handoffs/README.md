# RI-INTEGRATION-01 — Handoff per le repository OpenRGD

**24 novembre 2026 · packet di coordinamento · candidato/non-normativo.**
Questi handoff sono **messaggi pronti da inoltrare alle chat dedicate** dei rispettivi moduli; sono versionati nella [PR #4 Reality Ingress](https://github.com/OpenRGD/rgd-reality-ingress/pull/4), non modificano le repository destinatarie e non autorizzano deployment, acquisizione, mutazioni storiche o attuazione.

## Invariante condiviso

**Una sola acquisizione fisica per dispositivo; più consumer autorizzati, ciascuno con responsabilità distinta.**

1. **Host/Peripheral acquisition owner** acquisisce un segnale o pubblica un sample.
2. **Reality Ingress** valida/registrata, quando consentito, provenienza, integrità e riferimenti alle evidenze, senza reinterpretarle.
3. **Perception/Voice** producono interpretazioni *derivate* secondo i loro contratti.
4. **Cognition** usa risultati con qualità/freshness per reasoning e proposte non attuanti.
5. **Chronograf/History** qualificano tempo e persistenza *solo* tramite autorità effettive e policy indipendenti.
6. **Visual Feedback/Pulse/Console** presentano e/o consegnano feedback attraverso i propri servizi, senza possedere i sensori.
7. **Somatic** rimane esterno a RI e non riceve nessun permesso automatico di movimento.

**Non trasformare ogni campione volatile in una evidenza persistente.** La pipeline è fan-out e integrazione di responsabilità, non un nuovo collettore obbligatorio nella catena critica di VAD, IMU, controllo fisico o feedback.

## Inoltra alle chat / repository

| Priorità | Repository/chat destinataria | Handoff | Decisione richiesta |
|---|---|---|---|
| P0 | `italiarobotica/paky-01` — hardware e sensori | [RI-TO-PAKY-01.md](RI-TO-PAKY-01.md) | Un solo camera owner; identità OCCHI/C920; pilot breve ed esplicito |
| P0 | `OpenRGD/rgd-console` — PERIPH + IMU | [RI-TO-CONSOLE-PERIPH-IMU.md](RI-TO-CONSOLE-PERIPH-IMU.md) | Fan-out read-only; no seconda seriale; Console non diventa EvidenceStore |
| P0 | `OpenRGD/rgd-voice` | [RI-TO-VOICE.md](RI-TO-VOICE.md) | Owner mic/VAD/STT, consenso e forward opzionale di segmenti |
| P1 | `OpenRGD/rgd-calibration` | [RI-TO-CALIBRATION.md](RI-TO-CALIBRATION.md) | Ref/revisione profilo, frame, maturità, no depth certificata |
| P1 | `OpenRGD/rgd-cognition` | [RI-TO-COGNITION.md](RI-TO-COGNITION.md) | Adapter di consumer e limiti della fiducia nel dato, no effetto |
| P1 | `OpenRGD/rgd-visual-feedback` | [RI-TO-VISUAL-FEEDBACK.md](RI-TO-VISUAL-FEEDBACK.md) | Input ref ≠ lifecycle/LED proof; niente nuovo renderer |
| P1 | `OpenRGD/rgd-perception` (da creare) | [RI-TO-PERCEPTION.md](RI-TO-PERCEPTION.md) | Derivazioni traceable, legacy compat, provider/licenze |
| P2 | `OpenRGD/rgd-pulse` — Chronoscope | [RI-TO-PULSE-CHRONOSCOPE.md](RI-TO-PULSE-CHRONOSCOPE.md) | Non toccare K3 Console→Pulse; eventuale futura diagnostica |
| P2 | `RobotChronograf/chronograf` | [RI-TO-CHRONOGRAF.md](RI-TO-CHRONOGRAF.md) | Time qualification separata da host receipt e History |
| P2 | `OpenRGD/openrgd` — Core-B/C/D/History | [RI-TO-CORE-HISTORY.md](RI-TO-CORE-HISTORY.md) | Reconcile/contract review, NON automatic promotion |

P0/P1/P2 indicano **ordine del confronto**, non autorizzazioni di merge o promesse di implementazione. Perception è una repo pianificata, non esistente al momento di questo handoff. Gli altri moduli possono già proseguire autonomamente.

## Contratto minimo condiviso — cosa è reale e cosa non lo è

- `RI v0.4`: su `main` dopo [PR #2](https://github.com/OpenRGD/rgd-reality-ingress/pull/2); codice storico sperimentale, test software, non deployment.
- `ri.consumer-observation-ref.v0.1-candidate`: nella [PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4), *read-only*, si applica a osservazioni v0.4 effettivamente conservate; non sostituisce gli schemi dei publisher Console/Voice/Pulse. Il ref NON concede accesso ai payload.
- `integrity_status=verified_local_hash`: verifica di hash nel file store **locale**, non autenticazione della sorgente fisica.
- `source_verified=false`, `robot_binding_verified=false`, `history_committed=false`, `actuation_enabled=false`: limiti espressamente imposti all'adapter candidato.
- Clock: `received_monotonic_ns` + boot/domain non prova tempo sensore né sincronizzazione global; Chronograf/History sono autorità esterne.
- Privacy e performance: no archiviazione audio ambientale predefinita, niente video continuo per default, buffer/retention controllati, nessun media su GitHub, nessun blocco del sensor loop per la persistenza.

## Risposta attesa da ogni chat destinataria

Riportare al progetto RI, preferibilmente come nota/PR nel proprio repository:

1. Qual è **oggi** la vera sorgente dati, il proprietario della periferica e la versione installata/verificata (distinguere `main`, draft PR e host)?
2. Esiste già un output *read-only* che RI può consumare? Se sì, quale schema/trasporto e quali controlli di sicurezza/freshness? Se no, quale adapter minimo senza secondo reader?
3. Che cosa NON bisogna duplicare, quali PR già coprono la funzione, quali gap di schema/esecuzione restano?
4. Un test sintetico/negativo e un test fisico facoltativo, con criteri di rollback e senza rischio per la catena di controllo.
5. Referenza a PR/Issue nel repo proprietario (nessun merge automatico) e un breve handoff di ritorno a RI per aggiornare la matrice compatibilità.

## Fonti del dossier

- [Pipeline owner boundaries](../RI-INTEGRATION-01-PIPELINE.md)
- [Contratto candidato read-only](../../contracts/consumer-observation-ref.v0.1-candidate.schema.json)
- [Python consumer ref](../../src/reality_ingress/consumer_ref.py)
- [RI-HOST-01 OCCHI Pilot issue #5](https://github.com/OpenRGD/rgd-reality-ingress/issues/5)
- [RI History audit](../RI-RECOVERY-01.md)

**Questa è una guida di coordinamento, non una nuova autorità trasversale.**
