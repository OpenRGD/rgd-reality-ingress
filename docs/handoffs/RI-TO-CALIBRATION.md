# HANDOFF — RI → RGD Calibration

**Destinazione:** [OpenRGD/rgd-calibration](https://github.com/OpenRGD/rgd-calibration), chat calibrazione.
**Riferimenti:** [CAL-0.3 OCCHI PR #4](https://github.com/OpenRGD/rgd-calibration/pull/4), [RI PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4).
**Stato:** progetto di interoperabilità, non nuova procedura di calibrazione fisica.

## Confine di proprietà

Calibration è proprietaria dei profili geometrici, loro revisioni, qualità metrologica, prove e ciclo di validazione. Reality Ingress è proprietario **solo delle evidenze in ingresso** e può riferire un calibration profile con maturità esplicita. Perception usa tale profilo per elaborazioni geometriche e pubblica output derivati con incertezza. L'algoritmo legacy `src/reality_ingress/calibration.py` della v0.4 resta temporaneamente per compatibilità, non diventa l'autorità dei profili CAL.

## Fatto sperimentale OCCHI

35 coppie, scacchiera da 20mm, RMS stereo ~0.652px, baseline stimata ~64.905mm contro distanza fisica tra le lenti misurata ~60mm. L'ordine A/B, la profondità metrica e la trasformazione camera→corpo non sono certificati; il collo mobile cambierà il montaggio e richiederà nuove verifiche delle extrinsics.

## Richiesta

1. Definire per i consumatori un `calibration_profile_ref` stabile, `revision`, hash e stato `experimental/candidate/validated` (con la nomenclatura effettiva di CAL), legato a hardware UID, formato video, risoluzione, frame A/B e modello fisico **senza confondere modello con installazione**.
2. Concordare un profilo di interfaccia *read-only* affinché Ingress possa associare un riferimento CAL ad un'evidenza **senza** cambiare l'ID/hash storico v0.4. Preferire metadati laterali versionati dove il vecchio envelope è già immutabile.
3. Separare intrinsics stereo da extrinsics camera→collo→torso e monitorare l'eventuale deriva dopo modifiche meccaniche. Non promuovere automaticamente il vecchio candidato.
4. Definire criteri per Perception depth: `calibration_revision`, trasformazioni richieste, unità, validità, incertezza e graceful degradation quando il profilo non è disponibile.
5. Preservare le evidenze originali delle misure fuori da Git se contengono immagini del laboratorio o dati privati; pubblicare report e hash solo con policy esplicita.

## Criteri di accettazione

Riferimenti CAL risolvibili/invalidabili, baseline v0.4 immutata, test con revisione mancante/obsoleta/incompatibile, nessuna conversione silenziosa in metri e nessuna richiesta motori/homing dall'Ingress.

**Non duplicare in RI:** algoritmo e workflow CAL ufficiali, gestione delle revisioni, validazione metrologica, scrittura nel modello OpenRGD o attuazione.
