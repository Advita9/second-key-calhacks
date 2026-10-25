# Demo-ready chat UI changes

## Persuasion score
The chat score is now calculated from actual backend values:
`round(10 + 90 * (0.6 * model_persuasion + 0.4 * min(1, cue_count / 5)))`.

The model value and distinct cue count are passed through `TurnResult`, the memory-room reply snapshot, and the frontend parser. The score is intentionally separate from the conversation stage and never changes payment authorization.

## Backend compatibility
The included kernel/memory backend now sends the metrics. Legacy feeds and the SpacetimeDB path currently do not provide these fields in the included source bundle, so the UI displays “Waiting for signal metrics” instead of inventing a score. To show the real score with SpacetimeDB, its table/reducer schema must also publish `model_persuasion` and `cue_count`; that schema directory was not part of the supplied archive.

## Validation
Python syntax compilation passed for the modified backend files. The test suite could not be run in this environment because the uploaded archive excludes the project's virtual environment and `hypothesis` is not installed here. Run the project's normal backend tests and `npm run typecheck` / `npm run build` locally before the live demo.
