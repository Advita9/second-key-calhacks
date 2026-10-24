# Overnight setup (about 20 minutes)

Do these in order. Everything else the agent does itself.

## 1. Tools (5 min)
```
claude update || npm i -g @anthropic-ai/claude-code
brew install uv tmux
node -v        # you have 24.x, fine
python3 --version
```
Optional, saves the agent 10 minutes: `curl -sSf https://install.spacetimedb.com | sh` then `spacetime version`.

## 2. Keys (10 min, all optional, mocks cover gaps)
- Anthropic: console.anthropic.com, switch to your Individual org (the one showing credits), Settings > API Keys > create "second-key". Paste into `.env` as `ANTHROPIC_API_KEY`. This is the product's key, not Claude Code's.
- Cartesia: play.cartesia.ai, sign up, API key, apply promo CARTESIACALHACKS. Paste `CARTESIA_API_KEY`, set `TTS_PROVIDER=cartesia`.
- Nessie: api.nessieisreal.com, sign up, copy key, `NESSIE_API_KEY`.
```
cp .env.example .env
open -e .env
```
Never `export ANTHROPIC_API_KEY` in your terminal. If you did: `unset ANTHROPIC_API_KEY`.

## 3. Repo (2 min)
```
git init && git add -A && git commit -m "overnight kit"
```
Private GitHub repo so teammates can pull in the morning:
```
gh repo create second-key --private --source=. --remote=origin --push
```
If you want the agent to push milestones overnight, set `PUSH_OK=1` in `.env`. Otherwise it commits locally and you push at 7:30.

## 4. Preflight
```
chmod +x scripts/*.sh .claude/hooks/*.sh
./scripts/preflight.sh
```
Fix any MISS line.

## 5. Launch
Plug in. Keep the lid open. Then:
```
tmux new -s overnight
./scripts/overnight.sh
```
First screen: Claude Code may ask you to confirm bypass permissions. Confirm. Watch the first 2 or 3 minutes: it should read the docs and start item 0 (scaffold). Then detach: `Ctrl-b` then `d`.

Change the model: `MODEL=claude-fable-5-1 ./scripts/overnight.sh` (default alias is `fable`). Change the morning cutoff: `OVERNIGHT_HARD_STOP=08:00`.

## 6. Check on it (from your phone or when you wake up)
- `tmux attach -t overnight` to watch.
- `cat docs/STATUS.md` for progress. `tail .claude/overnight.log` for the stop-gate loop.
- Stop it gracefully: `touch .claude/STOP_NOW`. It finishes the current step and stops. Hard kill: `tmux kill-session -t overnight`.

## 7. In the morning
Read `docs/MORNING.md` first. Then `./scripts/acceptance.sh`. Then start the stack with `scripts/dev.sh` and open the three URLs it prints.

## What can go wrong
- Rate limits on a Max plan: the session pauses until the window resets, then the stop gate resumes. If you want no pauses, you can run Claude Code on API billing by exporting a *separate* key in the tmux shell before launch; that spends console credits fast at the top model, so I would not.
- Mac sleeps: `caffeinate` prevents idle sleep while plugged in, but closing the lid still sleeps it. Lid open.
- SpacetimeDB CLI will not install: the agent falls back to the in-memory room and records it. The module still compiles for the judge.
- The agent stops early: the stop gate only allows stopping when acceptance is green, after 07:30, after 60 loop iterations, or if STOP_NOW exists. Check `.claude/overnight.log` for which one.

## What it will not do
Submit to Devpost, post anywhere, email anyone, make the repo public, force-push, change macOS settings, or touch files outside this folder. Those are denied in `.claude/settings.json` and in CLAUDE.md.
