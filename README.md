# openlibing-cli

A small Python CLI for talking to a reverse-engineered resource-manager backend without the original VS Code extension.

The repository has been sanitized for public sharing:

- Checked-in URLs use `example.com` placeholder domains.
- Deep-link, user, environment, and network examples use fake values.
- Real deployment details must be injected locally through environment variables.

It does three things:

1. Stores your `authTicket` (`sessionId`) from a `vscode://.../connect?...` deep link.
2. POSTs your local `~/.ssh/id_rsa.pub` to the target environment.
3. Returns SSH connection info and can print a usable `~/.ssh/config` block.

## Install

```bash
cd cli/
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Or run it directly:

```bash
PYTHONPATH=cli python3 -m openlibing_cli --help
```

## Runtime configuration

The code no longer ships real backend coordinates. Set the real values in your shell before use:

```bash
export OPENLIBING_GATEWAY_PATH="/your/real/gateway/path"
export OPENLIBING_BASE_URL_PROD="https://rm.internal.example"
export OPENLIBING_REFERER_PROD="https://portal.internal.example/"
```

Optional environment-specific overrides:

```bash
export OPENLIBING_BASE_URL_BETA="https://rm-beta.internal.example/api/beta"
export OPENLIBING_BASE_URL_ALPHA="https://rm-alpha.internal.example/api/alpha"
export OPENLIBING_BASE_URL_ALPHA_YELLOW="https://rm-alpha-yellow.internal.example"

export OPENLIBING_REFERER_BETA="https://portal-beta.internal.example/"
export OPENLIBING_REFERER_ALPHA="https://portal-alpha.internal.example/"
export OPENLIBING_REFERER_ALPHA_YELLOW="https://portal-alpha-yellow.internal.example/"
```

## Quick start

### 1. Capture the deep link

Example:

```text
vscode://vendor.resource-manager/connect
  ?authTicket=SESSION_TOKEN_EXAMPLE
  &userId=user_example
  &envId=env-1234567890
  &authType=resource-manager
```

### 2. Save the session

```bash
openlibing login --uri "vscode://vendor.resource-manager/connect?authTicket=SESSION_TOKEN_EXAMPLE&userId=user_example&envId=env-1234567890&authType=resource-manager"
# or:
openlibing login --ticket SESSION_TOKEN_EXAMPLE --user-id user_example
```

The ticket is stored in `~/.config/openlibing-cli/config.json` with mode `0600`. You can also pass it inline with `--ticket`, or via `OPENLIBING_SESSION_ID`.

### 3. Connect and print SSH info

```bash
openlibing connect env-1234567890 --generate-key
```

Sample output:

```text
-> POST /localIde/connect env_id=env-1234567890
-> polling (interval=5.0s, timeout=1800.0s)
  [1] status: connecting
  [2] status: running
✓ success
  env-id:    env-1234567890
  name:      ResourceEnv-env-1234567890
  status:    running
  host:      203.0.113.10
  port:      32222
  user:      dev_user
  workdir:   /workspace/project
  key:       /Users/you/.ssh/id_rsa

  # SSH command:
  ssh -p 32222 -i /Users/you/.ssh/id_rsa dev_user@203.0.113.10
```

### 4. Or write a `~/.ssh/config` block

```bash
openlibing ssh-config env-1234567890 >> ~/.ssh/config
ssh openlibing-env-1234567890
```

## Subcommands

| Command | What it does |
| --- | --- |
| `openlibing login --uri <URI>` | Parse a `vscode://.../connect?...` URI, store ticket + user-id + env-id |
| `openlibing login --ticket <T>` | Store a ticket directly |
| `openlibing connect <envId> --generate-key` | Upload pub key, poll until running, print SSH info |
| `openlibing status <envId>` | Check status without re-uploading the key |
| `openlibing stop <envId>` | Disconnect the environment |
| `openlibing delete <envId>` | Delete the environment |
| `openlibing list` | List environments |
| `openlibing info <envId>` | Print `user@host:port` |
| `openlibing ssh-config <envId>` | Print an SSH config `Host` block |
| `openlibing refresh` | Exchange `refreshToken` for a new `sessionId` |
| `openlibing keygen` | Generate `~/.ssh/id_rsa` if needed |
| `openlibing whoami` | Show current session / config |

## Notes

- TLS verification is still disabled in the HTTP client to preserve behavior of the reverse-engineered flow.
- SSH host-key checking is disabled in the generated SSH config block.
- The session ticket is a long-lived secret. Prefer environment variables over persisting it when possible.
- This repository intentionally omits the real vendor gateway coordinates.
