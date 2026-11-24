# HANDOFF — RI → Console / Peripheral Manager / IMU

**Destinazione:** [OpenRGD/rgd-console](https://github.com/OpenRGD/rgd-console), chat Console e IMU.
**Riferimenti in corso:** [PERIPH PR #5](https://github.com/OpenRGD/rgd-console/pull/5), [PERIPH PR #6](https://github.com/OpenRGD/rgd-console/pull/6), [RI PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4).
**Stato:** handoff candidato; non sostituisce contratti Console né servizi installati.

## Confine di proprietà

Console/PERIPH gestisce identità device, lifecycle publisher, status/controlli autorizzati e dashboard. Il processo host che già acquisisce IMU è l'**unico lettore WIT/CH340**. Reality Ingress conserva/espone evidenze e riferimenti; **non** si appropria del device, della UI, del broker o del token di pubblicazione IMU.

Il percorso attuale del pilot IMU è lettore locale Paky-01 → `POST 127.0.0.1:8088/api/v1/imu/observations` (token privato) → Console Rust API e WS read-only `/api/v1/stream?robot_id=paky-01`. Il POST è **solo producer-ingress**, non un endpoint cui RI debba inviare dati per fingere un publisher. Il `console.imu.v0.1-candidate` read-side è diverso dallo schema del publisher e diverso da `ri.consumer-observation-ref.v0.1-candidate`.

## Richiesta alla chat Console/IMU

1. Confermare l'owner del sensore IMU e il fan-out **read-only** dal flusso esistente (o un adapter di export dedicato), senza secondo `pyserial`, senza duplicare endpoint REST o cambiare token.
2. Esporre, quando disponibili, source/session/sequence, boot/clock-domain reale, `host_monotonic_ns`, qualità, frame `imu_sensor_axes_unverified`, calibrazione null e provenienza senza promuovere `source_kind=physical` ad attestazione crittografica.
3. Mantenere tre stati distinti in Console: *device presente*, *publisher running*, *stream live/stale*. Un processo running non dimostra che siano arrivate misure; un hash verificato non dimostra binding hardware.
4. Proporre un piccolo **bridge non bloccante** verso RI per campioni IMU autorizzati, con quote e throttling. Un `ObservationRef` RI è emettibile **solo dopo effettivo ingest/stored evidence** e non si ricava artificialmente da un evento WS ancora volatile.
5. Visualizzare eventuali riferimenti RI con `origin_status`, `integrity_status`, provenienza e restrizioni di accesso, mantenendo separati dati grezzi, interpretazioni e report di lifecycle.
6. Non rendere Console un secondo EvidenceStore, un Chronograf o un controllore motorio. Le PR PERIPH sono ancora candidate e le estensioni audio/video necessitano provider e allowlist realmente verificati.

## Criteri di collaudo

La dashboard IMU/Pulse corrente resta invariata; arresto publisher → stale; reboot/session reset senza false continuità; RI assente o offline **non** blocca il lettore né la UI live. Confrontare lo stesso `session_id`/sequence fra fan-out e archivio RI quando il bridge verrà implementato. Nessuna chiamata USB/CAN/seriale da RI o dai container Console.

## Non-obiettivi

Non chiediamo a Console di adottare lo schema RI come schema IMU canonico, cambiare la firma delle API già in produzione, mettere segreti nell'app o creare nuove policy di autenticazione senza review del broker.
