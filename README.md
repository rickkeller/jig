# Jig

Jig is a small personal assistant harness that runs as a single Python process. It does two things:

- **Telegram door.** It polls a Telegram bot, answers allowed users by passing each message to a model program you supply (the "caller"), and keeps per-owner memory in SQLite.
- **Work list.** On a timer, it works through a SQLite work list (todos, ideas, handoffs, standing duties) and can hand items to a reasoning model through the same caller.

It has no broker and no cron, and it needs no third-party Python packages. All state lives in one data directory that you choose.

> **Warning: `jig --help` does not show help.** Jig has no option parser. Its first argument is always the data directory, so `jig --help` creates a folder named `--help` in the current directory and starts the service. If that happens, stop it (see [Stop and wake](#stop-and-wake)) and delete the `./--help` folder.

## Requirements

- Python 3.11 or newer.
- Linux or macOS. Jig uses `fcntl` file locks, so it doesn't run on Windows.
- For the Telegram door: a Telegram bot token from [@BotFather](https://t.me/BotFather).
- For any model reply: a program you already have that reads a prompt on stdin and prints a reply (see [`caller`](#caller)). Jig doesn't ship one, and it doesn't pick a model for you.

## Install

```sh
git clone https://github.com/rickkeller/jig
cd jig
python3 -m venv .venv
.venv/bin/pip install .
```

## Quickstart

```sh
mkdir -p ~/jig-data
.venv/bin/jig ~/jig-data          # usage: jig [DATA_DIR] [INTERVAL_SECONDS]
```

- `DATA_DIR` defaults to `~/.local/share/jig`.
- `INTERVAL_SECONDS` is the time between work-list passes. It defaults to `900`.

The process runs in the foreground until you stop it. On its own it only works the list, and it sends nothing to Telegram. To turn on the door, add the files described in [Configuration](#configuration) to the data directory. Jig checks for them on every loop, so you don't need to restart.

To try it without Telegram, start it with a short interval and check the log:

```sh
.venv/bin/jig /tmp/jig-demo 5 &
sleep 6; cat /tmp/jig-demo/process.log
touch /tmp/jig-demo/stop
```

### Stop and wake

Jig has no signals or subcommands. You control it with files in the data directory:

| File | Effect |
| --- | --- |
| `stop` | Jig exits at the next check. **Delete it before starting again**, or Jig exits right away. |
| `wake` | Touch it (change its modification time) to skip the rest of the current wait and run a pass now. |

## Configuration

Jig uses no environment variables. Configuration is plain files in the data directory. Keep them out of git. The repo's `.gitignore` already lists them.

| File | Required for | Contents |
| --- | --- | --- |
| `door.token` | Telegram door | One line: the bot token. The legacy name `alfred.token` is also read. Jig never prints it. |
| `allow` | Telegram door | One Telegram **user id** per line. `#` comments are allowed. Jig checks the sender's user id, which in a private chat is the same as the chat id. If the file is missing or empty, nobody gets an answer. |
| `door-model` | Telegram door | Line 1 is the provider, line 2 the model, and an optional line 3 the effort (default `medium`). Jig passes these to the caller. |
| `caller` | Any model call | Line 1 is the program. Line 2 is its working directory. Line 3 is its home, which Jig passes in the `CALLER_HOME` environment variable. An optional line 4 is the effort for reasoning calls (default `xhigh`). |
| `owner` | Optional | One name, used for memory at `memory/<name>.sqlite`. Defaults to `owner`. |
| `door-hold` | Optional | While this file exists, replies are stored instead of sent. Delete it to send the held replies. |
| `reasoner-hold` | Written by Jig | A UTC timestamp. Clock and duty items wait until then. |

The door polls only when `door.token`, `caller` and `door-model` all exist.

A message that starts with `remember ` is stored as a fact in the owner's memory.

### `caller`

Jig runs the caller like this:

```
<program> <provider> <model> <effort>
```

The prompt goes to stdin. Whatever the program prints to stdout becomes the reply. Each call times out after 240 seconds. The caller keeps its own model credentials, so don't copy API keys into Jig.

### Reasoning model (optional)

The work list calls a reasoning model only when one is recorded in the data directory's `package.sqlite` **and** `caller` exists. You set it from Python, and Jig must be stopped first because it holds a lock on the directory:

```sh
.venv/bin/python -c "from jig.package import Package; p = Package('$HOME/jig-data'); p.set_reasoning_model('PROVIDER', 'MODEL'); p.close()"
```

### Files Jig creates

`process.pid`, `process.log`, `package.sqlite`, `package.lock`, `work.sqlite`, `door.sqlite`, `door-on`, `telegram.offset`, `memory/<owner>.sqlite` and `vault/` (Markdown notes). Back up the whole data directory to keep the state.

More detail is in [docs/SETUP.md](docs/SETUP.md).

## Troubleshooting

- **The bot never replies.** Check that `door.token`, `caller` and `door-model` all exist, and that your user id is in `allow`. Send the bot a message in Telegram first. Door errors are swallowed and not logged, so also run your caller by hand to test it: `echo hi | <program> <provider> <model> medium`.
- **A folder named `--help` (or another flag) appeared.** See the warning at the top. Stop Jig, then remove the folder.
- **Jig exits as soon as it starts.** A `stop` file from an earlier run is still in the data directory. Delete it.
- **`RuntimeError: another Package owns this root`.** Another Jig process, or a Python session, is using the same data directory. Check `process.pid`, or stop the other process.
- **The log shows only `judgment_missing`, `slept` or `held`.** `judgment_missing` means no reasoning model is set up (see [Reasoning model](#reasoning-model-optional)). Jig then writes a note under `vault/engine/`. `slept` and `held` are normal when the list is empty or while `reasoner-hold` is in the future.

## Development

```sh
python3 -m unittest discover -s tests        # or: python3 -m pytest -q
```

See [AGENTS.md](AGENTS.md) for the repo layout and conventions.

## License

MIT. See [LICENSE](LICENSE).
