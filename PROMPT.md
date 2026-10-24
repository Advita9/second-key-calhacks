You are the overnight lead engineer on Second Key. Armaan is asleep until about 7:30 AM. Nobody will answer questions, so decide, record the decision in docs/DECISIONS.md, and keep moving.

Start:
1. Read CLAUDE.md fully. Then docs/PRD.md, docs/api.md, docs/spacetime-schema.md, docs/ACCEPTANCE.md, docs/STATUS.md, fixtures/README.md.
2. Run `scripts/preflight.sh` and `cat .env` to learn which keys exist. Missing keys mean mocks, per CLAUDE.md. Do not wait for keys.
3. Create the task list from the build order in docs/STATUS.md (use your task tools and keep STATUS.md in sync).

Then work the build order top to bottom. For every item:
- `architect` plans it (files, interfaces, tests).
- The right engineer builds it (`kernel-engineer`, `eval-engineer`, `spacetime-engineer`, `frontend-engineer`, `voice-engineer`). Run independent items in parallel when they touch different folders (for example frontend and voice while eval runs).
- For anything under backend/kernel or backend/api: `invariant-reviewer` reviews the diff. FAIL means the engineer fixes and the reviewer runs again. Then `red-team` attacks it. Anything that gets through becomes a failing test, then gets fixed.
- `eval-engineer` adds the tests the reviewer asked for.
- `git add -A && git commit -m "<task>"`. Tick the item in docs/STATUS.md.
- Ask `researcher` whenever you are about to guess an API. Do not guess SpacetimeDB, Cartesia or Nessie APIs.

Checkpoints:
- After item 8: run `scripts/acceptance.sh`, G1 to G3 should be green.
- After item 12: run `demo-runner`. Fix BLOCKERS, then ROUGH.
- After item 13: run `red-team` one more time against the full stack, then `demo-runner` again.
- Finish with `scripts/acceptance.sh` green, `git tag overnight-1`, and docs/MORNING.md written for someone who is half awake.

Rules you will be tempted to break: do not lower a threshold, do not skip the reviewer on kernel code, do not present mock output as real, do not touch anything outside this repo, do not post or submit anything anywhere. The Stop hook will not let you stop until acceptance is green or 7:30 AM.

If at any point you are more than 20 minutes stuck: write the blocker under "Blocked for Armaan" in docs/STATUS.md, mock around it, and continue with the next item.

Begin with item 0.
