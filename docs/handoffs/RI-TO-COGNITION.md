# HANDOFF — RI → Cognition / Attention / Work

**Destinazione:** [OpenRGD/rgd-cognition](https://github.com/OpenRGD/rgd-cognition), chat RGD-COG.
**Riferimenti:** [COG-C1 PR #5](https://github.com/OpenRGD/rgd-cognition/pull/5), [COG–CORE-B PR #6](https://github.com/OpenRGD/rgd-cognition/pull/6), [COG–CORE-D PR #7](https://github.com/OpenRGD/rgd-cognition/pull/7), [RI PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4).
**Stato:** handoff adapter candidate, non implementazione della Cognition.

## Confine di proprietà

RI fornisce *osservazione referenziata + qualità/provenienza*; Perception fornisce output interpretativi con modello/versione/incertezza; COG possiede Attention, agenda autonoma, ragionamento e proposte non attuanti. Nessun modulo RI può attribuire il `SELF` a un soggetto nell'immagine o emettere GoalAdmission/EffectGrant.

Il campo `integrity_status=verified_local_hash` del candidato RI dimostra soltanto che un **EvidenceStore locale** ha superato la verifica del payload. Non autentica il sensore, il robot, il Life binding, il tempo Chronograf o il consenso. Non equivale automaticamente a qualunque stato specifico della `cog_context_slice_v0.2-candidate`.

## Richiesta alla chat Cognition

1. Progettare un **adapter esplicito di versione**, che legga `ObservationRef` solo dopo autorizzazione di accesso, validi schema e payload disponibili, e mappi gli stati di attendibilità nel linguaggio COG *senza promuovere falsamente* la fiducia nella sorgente.
2. Per la prima wave usare `SESSION_SCOPED` e binding Life non verificato/null; nessun nuovo resolver identity, enrollment o writer Chronon prodotto dal parser.
3. Tenere separati: IMU `sensor axes unverified`, eventuale informazione percettiva derivata, Voice transcript e report di `speaking`. Trascrizione e riconoscimento oggetti sono inferenze, non osservazioni grezze.
4. Gestire backlog, stale, replay, assenza evidence/media, calibrazione scaduta e temporizzazione multi-host non sincronizzata. Una osservazione non disponibile non è una osservazione falsa o con valore zero.
5. Mantenere il percorso attuale COG C1→C0 Work agenda e le regole Core-B di **ammissione singola** e ownership: riuso del consumer/input adapter, non un secondo planner.
6. Eventuali risposte vocali, espressioni o gesti rimangono **proposte** per le policy/output owner; nessuna action diretta su CAN, LED, microfono o History.

## Accettazione

Fixture positive/negative con stesso `observation_id`, provata preservazione di hash, rigetto di stati RI `source_verified=false` in contesti che richiedono identità verificata, caso mancata sincronizzazione, e COG che continua a funzionare anche se RI è offline. Tracciare esplicitamente quali campi restano null/unknown.

**Non creare:** un secondo EvidenceStore nel motore COG, un `world_model.json` immutabile come unica fonte della realtà, o un percorso implicito di movimento.
