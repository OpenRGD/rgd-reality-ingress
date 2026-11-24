# HANDOFF — RI → Robot Chronograf / Qualified Time

**Destinazione:** [RobotChronograf/chronograf](https://github.com/RobotChronograf/chronograf), chat Chronograf e temporizzazione OpenRGD.
**Riferimenti:** [RI PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4), [Core-D draft PR #14](https://github.com/OpenRGD/openrgd/pull/14), [Temporal/Chronon Profile](https://github.com/OpenRGD/openrgd/blob/main/contracts/agent/v0.1.0/contracts/00_TEMPORAL_CHRONON_PROFILE.md).
**Stato:** request/response **da progettare**; nessun adattatore Chronograf in RI è installato.

## Confine di proprietà

RI registra timestamp originali del produttore e *receipt monotonic clock* del suo host con identità del boot/clock-domain. `host_receive_utc` è una stima/reporta, non il tempo fisico di esposizione o di latch. Chronograf è il solo proprietario della qualificazione TimeAtom, uncertainty e dell'eventuale AnchorRef64; History/Chronon rimane un'autorità diversa.

Il riferimento storico RI v0.4 dichiara esplicitamente `alignment_status=NOT_RESOLVED_BY_CHRONOGRAF`. Non cambiare quella dichiarazione dopo il fatto, nemmeno se in futuro si dispone di un nuovo time service.

## Richiesta

1. Specificare un adapter **additivo e opzionale** `RI TimeQualificationRequest` / risposta da un Chronograf realmente attivo, mantenendo `observation_id`, `clock_domain_id`, `boot_id`, `received_monotonic_ns`, eventuale source timestamp, method/uncertainty, source host e integrità.
2. Distinguere *timestamp della sorgente*, *ricezione host*, *tempo dell'importazione*, *tempo della qualificazione* e *tempo del commit History*. Non retrodatare l'Anchor all'esposizione quando questo momento non è misurato.
3. Usare `TimeAtom` e handle opachi con namespace/TimeAtom hash verificabili; un numero monotonic o un clock nel Chronoscope non è un anchor.
4. Cross-host (Paky-01 ↔ RTX 5080) richiede dominio e prove di sincronizzazione esplicite; evitare confronti numerici fra monotonic-clock di host differenti.
5. Quando il servizio non è disponibile o la prova è insufficiente, restituire un risultato dichiarato `UNRESOLVED`/non qualificato, non un campo valorizzato “best effort” con false garanzie.
6. Non includere metodi di creazione Chronon o Life binding nell'adapter RI; il commit storico è un'altra autorizzazione e un altro ciclo.

## Accettazione

Fixture same-boot, different-boot, sensor source time assente, importazione tardiva, disallineamento tra host, clock reset e temporale impreciso. Nessun mutamento del payload/evidence ID originale. Nessuna dipendenza obbligatoria di acquisizione fisica da Chronograf.

**Licenza:** la repo RobotChronograf dichiara una licenza diversa dal MIT OpenRGD; un adapter o scambio di schema non implica automaticamente la rilicenza del motore Chronograf. Verificare condizioni e diritto di distribuzione prima di includerlo in bundle commerciali.
