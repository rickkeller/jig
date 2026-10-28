# AGENTS.md: Jig

Jig is a single-process harness: a Telegram door, per-owner memory and a SQLite work list. It is one Python process. It is not a cron job and not a Hermes profile.

## Layout

```
jig/
  process.py    entry point (`jig`). Runs the main loop: work list pass, door poll, stop/wake files
  package.py    Package: owns the data dir lock, profiles, memory, rules and the reasoning/engine model
  worklist.py   SQLite work list (items, events, standing duties)
  door.py       held/sent replies (door.sqlite)
  telegram.py   Telegram long-poll client, allow-list filtering, `remember ` facts
  intake.py     files incoming messages onto the work list
  reasoner.py   calls the external `caller` program (prompt on stdin, 240 s timeout)
  local.py      reads data-dir files: door.token, allow, owner, door-model, caller
  bus_link.py   optional Agent Bus claim; files one chat as an ask when bus.json exists
  buscopy.py    optional websocket client for a local agent-bus copy
  installed.py  install checks (refuses Hermes paths, archive helper)
tests/          unittest-style tests; fixtures in tests/fixtures/
docs/SETUP.md   setup for a new machine
```

## Run and test

```sh
python3 -m venv .venv && .venv/bin/pip install -e .
python3 -m unittest discover -s tests     # or: python3 -m pytest -q
.venv/bin/jig /tmp/jig-scratch 5          # stop with: touch /tmp/jig-scratch/stop
```

- Only ever use a scratch data directory. Never point a test or a manual run at a real data directory.
- `jig --help` is not help. It creates `./--help` and starts the service.

## Conventions

- Standard library only. Don't add runtime dependencies without a strong reason.
- Configuration lives in data-dir files, not environment variables or YAML. If you add a new file, document it in README.md and docs/SETUP.md, and add it to `.gitignore`.
- All state goes through SQLite in the data directory. Keep writes transactional.
- One process per data directory. `Package` enforces this with an `fcntl` lock, so don't work around it.
- Write short, plain sentences in docs and docstrings.
- Every behaviour change needs a test in `tests/`.

## Secrets: never commit them

- Never commit `door.token`, `alfred.token`, `allow`, `owner`, `door-model`, `caller`, `.env`, `*.pem`, `auth.json` or `credentials.json`. They are in `.gitignore`, so keep them there.
- Don't put bot tokens, API keys, Telegram chat or user ids, or host-specific home paths in code, tests, fixtures, docs or commit messages. Use obvious placeholders.
- Model credentials belong to the external caller program, never to Jig.
