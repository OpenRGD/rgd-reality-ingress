# HANDOFF — RI → Visual Feedback / Eyes / Expressive Output

**Destinazione:** [OpenRGD/rgd-visual-feedback](https://github.com/OpenRGD/rgd-visual-feedback), chat Visual Feedback, in coordinamento con [rgd-console](https://github.com/OpenRGD/rgd-console).
**Riferimenti:** [Visual Eye Composer PR #10](https://github.com/OpenRGD/rgd-visual-feedback/pull/10), [Core Feedback PR #6](https://github.com/OpenRGD/openrgd/pull/6), [RI PR #4](https://github.com/OpenRGD/rgd-reality-ingress/pull/4).
**Stato:** contratto di confine, non modifica dei preset o del runtime BLE.

## Confine di proprietà

Visual Feedback è proprietario dei renderer, degli stati, delle espressioni, delle scene, delle gesture occhi, della consegna al device e dei feedback `desired/applied`. La Console è editor/preview, non motore espressivo concorrente. RI gestisce **eventuali evidenze/osservazioni** e non decide come un anello/occhio si illumini.

Un evento Voice `speaking` è un evento di lifecycle; `applied` BLE è un risultato del driver, non verifica ottica del colore. Questi report possono essere osservati come *report*, ma non inseriti sotto lo stesso tipo delle misure fisiche senza descriverne la provenienza.

## Richiesta alla chat Visual Feedback

1. Conservare il flusso Voice→Visual già studiato; RI non va inserito come proxy obbligatorio fra playback e LED/occhi.
2. Definire un adapter **read-only** futuro per eventi di sorgente e report di consegna con `event_kind`, `source_owner`, `occurred_at`/clock-domain e prova disponibile. Non convertire il report in `camera_observation` o `physical_output_observed=true`.
3. Quando Cognition/Perception introdurrà gaze target o espressioni guidate dalla scena, richiedere `derived_input_refs`, freschezza, qualità, arbitro della policy e fallback neutro: una detection incerta non guida automaticamente occhi o ring.
4. Conservare l'indipendenza fra render di occhi/indicatori e BLE del ring, con possesso singolo del device e TTL per segnali temporanei. Perception/RI non scrivono sul socket del driver.
5. Separare nel debug desired cue, rendered scene, driver ack e osservazione fisica indipendente; la Console non deve dichiarare che il LED ha prodotto una luce osservata soltanto perché il write BLE è riuscito.
6. Preservare pack espressioni/eye composer e non creare un secondo catalogo in Reality Ingress.

## Accettazione

Le PR Visual/Console e il percorso Voice lifecycle mantengono test e anteprime; input RI assente/degradato non blocca segnali parlato/errori; replay/synthetic non diventa stato live; nessun path di attuazione motori e nessuna falsa attestazione di output fisico.

**Da non duplicare:** feedback engine, blink/gaze recipes, RGB mapping, Bluetooth ownership, catalog revisioning o le funzioni della Console Studio.
