# Setup

Install, then put four files in a data directory. Those files stay on the machine. They do not go in the repository.

## Install

```
git clone https://github.com/rickkeller/jig
cd jig
python3 -m venv .venv
.venv/bin/pip install .
mkdir -p ~/jig-data
.venv/bin/jig ~/jig-data
```

The process starts. It does not install a broker and it does not run cron. The door does not reply until the files below exist.

## Data directory

### door.token

One line. The Telegram bot token. Jig reads it and does not print it.

Open the bot once in Telegram so it is allowed to reply.

### allow

One chat id per line. A message from any other chat is ignored. If this file is missing, the door answers nobody.

### owner

One name. Memory is stored at `memory/<name>.sqlite`. If this file is missing, the name is `owner`.

### door-model

Three lines:

```
provider
model
effort
```

The door uses these when it replies. If this file is missing, the door does not call a model. Use a model you already have. This repository does not choose one.

### caller

Line 1 is a program. Jig runs it with the prompt on standard input. The arguments are the provider, the model, and the effort. The program prints the reply.

Lines 2 and 3 are that program's directory and home. An optional fourth line is the effort for the reasoning call. If it is missing, the effort is `xhigh`.

If this file is missing, the process does not call a model. The model token stays with that program. Do not copy it into Jig.

### bus.json

Optional. If this file is missing, Jig does not use Agent Bus. Paths are relative to this data directory:

```json
{"state_dir": "bus-state", "config": "endpoints.json", "endpoint_id": "jig"}
```

`config` is the Agent Bus allowlist. `endpoint_id` is this install. A chat from an allowed sender is filed as an ask. Jig does not call a model to receive it. The other endpoint answers with its own client. A Hermes path is refused.
