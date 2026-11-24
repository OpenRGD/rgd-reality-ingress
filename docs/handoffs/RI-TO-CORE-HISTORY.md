# HANDOFF — RI → OpenRGD Core / Identity / History

**Destinazione:** [OpenRGD/openrgd](https://github.com/OpenRGD/openrgd), chat Canonical Core, Core-B/C/D e Life/Chronon.
**Riferimenti:** [RI PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4), [CORE-B #11](https://github.com/OpenRGD/openrgd/pull/11), [CORE-C #13](https://github.com/OpenRGD/openrgd/pull/13), [CORE-D #14](https://github.com/OpenRGD/openrgd/pull/14).
**Stato:** proposta di interoperabilità, **non** richiesta di promuovere automaticamente un contratto a normative.

## Confini già emersi

Reality Ingress: dati osservati e provenienza, con local evidence store/hash; Core: contratti condivisi, semantica e conformance; Identity/Life: binding e ownership verificata; Chronograf: tempo qualificato; History/Physics: Chronon canonici, writer e ricevute; Cognition: proposte; Somatic: safety-gated action.

I livelli Core-D sono distinti: L0 campioni volatili, L1 vault di evidenze con consent/retention, L2 Chronon canonici, L3/L4 proiezioni/memoria/autobiografia. Il file store legacy RI **non** certifica di essere L1 Vault conforme né L2 History. Un `ObservationRef` RI non è un Chronon e non concede accesso ai media.

## Richiesta alla chat Core

1. Esaminare `ri.consumer-observation-ref.v0.1-candidate` come **projection API locale**, non come standard generale; identificare eventuali campi corretti per l'interoperabilità futura senza cambiare le ID storiche v0.4.
2. Stabilire ownership di source/device/host binding contro identity `robot_instance_id`, Life e `SELF`. Una stringa `source_id` o `robot_id` inviata da un publisher non verifica l'entità.
3. Allineare stato `integrity_status=verified_local_hash` a una semantica di **hash solo locale**; autenticazione fonte, physical attestation, calibration, privacy e time qualifed sono prove indipendenti.
4. Definire, **solo come candidatura**, come un consumer autorizzato può chiedere History commit; il writer deve controllare Life binding/lease/fencing, effect grant, idempotenza, provenienza, disponibilità e ricevuta autenticata. Nessun RI side effect “archive this to Chronon” senza gate.
5. Distinguere observation/derived result/producer lifecycle report/cognitive proposal per evitare un unico `event` ambiguo. La persistenza di ambient audio/video deve avere policy privacy, retention, accesso, redazione e traccia delle cancellazioni indipendenti.
6. Proteggere P0: nessun ingress, UI, modello o publisher può emettere istruzioni CAN, e-stop, torque enable o safe balance tramite un semplice record di osservazione.
7. Valutare il percorso di versionamento e conformità per un eventuale **adattatore canonico** senza rendere dipendenti i produttori hardware da PR draft ancora non accettate.

## Acceptance / gate

Documento di review con mapping puntuale dei campi, status `CANDIDATE` vs `ACCEPTED`, tests negativi (false identity, unknown time, stale proof, duplicated commit, uncertain receipt, private media), nessuna modifica automatica a `spec/` normativo. Dopo la review RI mantiene la sua API compatibile e riporta le revisioni realmente adottate.

**Non copiare** la versione v0.4 di Perception o dell'EvidenceStore nel Core: si discute il contratto, non si sposta il runtime.
