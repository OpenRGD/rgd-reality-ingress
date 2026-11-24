# HANDOFF — RI → Voice / Audio I/O

**Destinazione:** [OpenRGD/rgd-voice](https://github.com/OpenRGD/rgd-voice), chat Voice.
**Contesto:** [Voice audio-ownership ADR / PR #3](https://github.com/OpenRGD/rgd-voice/pull/3), [progressive Piper / PR #7](https://github.com/OpenRGD/rgd-voice/pull/7), [RI PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4).
**Stato:** PROPOSTA, no installazione o registrazione audio automatica.

## Confine di proprietà

Voice possiede la logica di parlato: VAD, STT, TTS, profili, sessione conversazionale, riproduzione e lifecycle (`listening/thinking/speaking`). Nell'attuale laboratorio il processo Voice usa PulseAudio/parecord per acquisire; l'evoluzione PERIPH prevede un solo acquisition owner con fan-out autorizzato. RI è **consumatore opzionale** di evidenze audio prelevate con consenso, non un secondo processo che apre il microfono.

Una **trascrizione** è interpretazione derivata e deve riferire la sorgente audio/ASR quando accessibile; Voice continua a possedere l'ASR. Un evento `speaking` o `playback.started` è un **producer lifecycle report**, non prova acustica di suono emesso. Il flusso Voice→Visual esistente non deve essere sostituito con un bus RI.

## Richiesta alla chat Voice

1. Concordare un punto di fan-out **opzionale** per segmento audio o riferimento a segmento *già acquisito*, con consenso esplicito, delimitazione di sessione e scadenza/retention; default: **nessun salvataggio di voce ambientale**.
2. Distinguere metadata di cattura (`source_id`, sessione, sequenza, formato PCM, frame count, clock del processo host, source time ignoto quando non disponibile) da transcript/ASR, intenti cognitivi, voce sintetizzata e stato riproduzione.
3. Niente blocchi nel VAD/audio thread: RI lento, disconnesso o senza storage deve causare drop osservabile del fan-out, non interruzione o latenza del parlato.
4. Definire se e quando un transcript può riferirsi a un `ObservationRef` RI; senza un evidence record realmente registrato, usare soltanto il riferimento produttore/transitorio con provenienza corretta.
5. Integrare la policy privacy prima di ogni invio remoto a RTX/servizi cloud; nessuna chiave provider e nessun audio personale nella repo GitHub.
6. Aggiornare l'ADR storico dove descrive RI come repository privata/vuota: adesso RI è pubblica MIT, v0.4 recuperata e merged; PR #4 resta draft.

## Accettazione

Test audio local-first Voice e Visual rimangono verdi; un solo capture owner; segnale Voice validato senza registrazioni di default; prove con RI disconnesso e col segmento consentito; nessun lifecycle evento falsamente promosso a osservazione fisica.

**Da non fare:** nuovo VAD/STT in RI, replica di Voice Studio, cattura duplicata, persistenza ambientale silenziosa, controllo LED direttamente da RI, modifica del playback Piper della PR #7 come prerequisito di evidenze.
