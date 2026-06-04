"""Command-line entry point for openlibing-cli.

Subcommands mirror what the VS Code extension does, but driven from a shell.
"""

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urlparse, parse_qs, unquote

from . import __version__
from .api import APIError, ResourceManagerAPI
from .config import Config
from .constants import ENVIRONMENTS
from . import ssh_key


# ---------- helpers --------------------------------------------------------


def resolve_session_id(args, config):
    """Find the session ticket, in priority order:
    1. --ticket flag
    2. OPENLIBING_SESSION_ID env var
    3. config file
    """
    if getattr(args, "ticket", None):
        return args.ticket
    env = os.environ.get("OPENLIBING_SESSION_ID")
    if env:
        return env
    stored = config.get("session_id")
    if stored:
        return stored
    raise SystemExit(
        "No session ticket. Provide one via:\n"
        "  --ticket <AUTH_TICKET>\n"
        "  OPENLIBING_SESSION_ID environment variable\n"
        "  or run: openlibing login --ticket <AUTH_TICKET>"
    )


def resolve_env(args, config):
    return (getattr(args, "env", None)
            or os.environ.get("OPENLIBING_ENV")
            or config.get("env", "prod"))


def make_api(args, config):
    env = resolve_env(args, config)
    if env not in ENVIRONMENTS:
        raise SystemExit(f"Unknown environment: {env}. Valid: {', '.join(ENVIRONMENTS)}")
    config.set("env", env)
    return ResourceManagerAPI(ENVIRONMENTS[env], resolve_session_id(args, config), env)


def parse_vscode_uri(uri):
    """Parse a `vscode://.../connect?...` deep link.

    Tolerates URIs where the whole query string has been percent-encoded
    (e.g. `?authTicket%3DABC%26userId%3DXYZ` — common when the URL is
    captured from a redirected address bar).
    """
    parsed = urlparse(uri)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    result = {
        "authTicket": (qs.get("authTicket") or [None])[0],
        "userId": (qs.get("userId") or [None])[0],
        "envId": (qs.get("envId") or [None])[0],
        "authType": (qs.get("authType") or [None])[0],
    }
    # If normal parsing yielded nothing, the query was probably
    # double-encoded — try unquoting once and reparsing.
    if not any(result.values()) and parsed.query:
        decoded = unquote(parsed.query)
        if decoded != parsed.query:
            qs2 = parse_qs(decoded, keep_blank_values=True)
            result = {
                "authTicket": (qs2.get("authTicket") or [None])[0],
                "userId": (qs2.get("userId") or [None])[0],
                "envId": (qs2.get("envId") or [None])[0],
                "authType": (qs2.get("authType") or [None])[0],
            }
    return result


def normalize_machine_info(env_id, info):
    """Pull the SSH-relevant fields out of a connect/checkStatus response.

    The `info` dict is `response.data` — i.e. the inner `data` of the
    business envelope.
    """
    use_proxy = bool(info.get("useProxy"))
    host = info.get("targetIp") if use_proxy else info.get("ip")
    port = info.get("targetPort") if use_proxy else info.get("port")
    if port is not None:
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = None
    jump_port = info.get("jumpPort")
    if jump_port is not None:
        try:
            jump_port = int(jump_port)
        except (TypeError, ValueError):
            jump_port = None
    return {
        "devEnvId": env_id,
        "devEnvName": info.get("devEnvName") or f"ResourceEnv-{env_id}",
        "host": host,
        "port": port,
        "user": info.get("userName"),
        "workdir": info.get("workingDir") or "",
        "status": info.get("status"),
        "usableTime": info.get("usableTime"),
        "accountType": info.get("accountType"),
        "description": info.get("description"),
        "useProxy": use_proxy,
        "jumpIp": info.get("jumpIp"),
        "jumpPort": jump_port,
        "targetIp": info.get("targetIp"),
        "targetPort": int(info["targetPort"]) if info.get("targetPort") else None,
        "identityFile": str(ssh_key.key_path()),
    }


def print_human(info):
    print()
    print(f"  env-id:    {info['devEnvId']}")
    print(f"  name:      {info['devEnvName']}")
    print(f"  status:    {info['status']}")
    if info["useProxy"] and info.get("targetIp"):
        print(f"  host:      {info['targetIp']}  (via jump {info['jumpIp']}:{info['jumpPort']})")
        print(f"  port:      {info['targetPort']}")
    else:
        print(f"  host:      {info['host']}")
        print(f"  port:      {info['port']}")
    print(f"  user:      {info['user']}")
    print(f"  workdir:   {info['workdir'] or '(none)'}")
    print(f"  key:       {info['identityFile']}")
    if info.get("usableTime"):
        print(f"  usable:    {info['usableTime']}")
    if info.get("description"):
        print(f"  desc:      {info['description']}")
    print()
    if info["useProxy"] and info.get("targetIp"):
        jump = f"jump@{info['jumpIp']}:{info['jumpPort'] or 22}"
        print("  # SSH command (jump host):")
        print(f"  ssh -J {jump} -p {info['targetPort']} -i {info['identityFile']} "
              f"{info['user']}@{info['targetIp']}")
    else:
        print("  # SSH command:")
        print(f"  ssh -p {info['port']} -i {info['identityFile']} "
              f"{info['user']}@{info['host']}")


def wait_for_terminal(api, env_id, initial_status, args):
    """Poll checkStatus until status is `running`/`exception`/`ready`.

    Mirrors the extension's `pollMachineStatus` (max 360 × 5s).
    Returns the final status data dict.
    """
    if initial_status in ("running", "exception", "ready"):
        return {"status": initial_status}
    if args.no_wait:
        return {"status": initial_status}
    deadline = time.time() + args.timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            data = api.check_status(env_id)
            status = (data.get("data") or {}).get("status", "unknown")
        except APIError as e:
            print(f"  ⚠ poll #{attempt} failed: {e}", file=sys.stderr)
            time.sleep(args.interval)
            continue
        if not args.json:
            print(f"  [{attempt}] status: {status}")
        if status in ("running", "exception", "ready"):
            return data.get("data") or {"status": status}
        time.sleep(args.interval)
    print(f"✗ polling timed out after {args.timeout}s", file=sys.stderr)
    return {"status": "timeout"}


# ---------- subcommands ----------------------------------------------------


def cmd_login(args):
    config = Config(args.config)
    ticket = args.ticket
    env_id = None
    user_id = args.user_id

    if args.uri:
        parsed = parse_vscode_uri(args.uri)
        if not ticket:
            ticket = parsed.get("authTicket")
        if parsed.get("envId"):
            env_id = parsed["envId"]
        if parsed.get("userId") and not user_id:
            user_id = parsed["userId"]
    if not ticket:
        raise SystemExit("Must provide --ticket or --uri")

    config.set("session_id", ticket)
    if user_id:
        config.set("user_id", user_id)
    if env_id:
        config.set("default_env_id", env_id)
    if args.env:
        config.set("env", args.env)

    print(f"✓ Session saved to {config.path}")
    print(f"  env:    {config.get('env')}")
    print(f"  userId: {config.get('user_id') or '(unset)'}")
    if config.get("default_env_id"):
        print(f"  default env-id: {config.get('default_env_id')}")


def cmd_connect(args):
    config = Config(args.config)
    api = make_api(args, config)
    pub = ssh_key.ensure_public_key(
        auto_generate=args.generate_key, force=args.force_keygen
    )

    if not args.json:
        print(f"→ POST /localIde/connect env_id={args.env_id}")
    try:
        data = api.connect(args.env_id, pub)
    except APIError as e:
        print(f"✗ connect failed: {e}", file=sys.stderr)
        raise SystemExit(1)

    info = data.get("data") or {}
    if not args.no_wait and not args.json:
        print(f"→ polling (interval={args.interval}s, timeout={args.timeout}s)")

    final = wait_for_terminal(api, args.env_id, info.get("status"), args)
    # Merge the polled final into info (running-state usually has the
    # up-to-date ip/port).
    info.update({k: v for k, v in final.items() if v})

    out = normalize_machine_info(args.env_id, info)
    out["publicKeyFingerprint"] = pub.split()[-1] if pub else None

    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(f"✓ {data.get('msg', 'connected')}")
        print_human(out)


def cmd_status(args):
    config = Config(args.config)
    api = make_api(args, config)
    try:
        data = api.check_status(args.env_id)
    except APIError as e:
        print(f"✗ {e}", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_stop(args):
    config = Config(args.config)
    api = make_api(args, config)
    try:
        data = api.stop(args.env_id)
    except APIError as e:
        print(f"✗ {e}", file=sys.stderr)
        raise SystemExit(1)
    print(f"✓ {data.get('msg', 'stopped')}")


def cmd_delete(args):
    if not args.yes:
        ans = input(f"Delete env {args.env_id}? [y/N] ")
        if ans.lower() != "y":
            print("cancelled")
            return
    config = Config(args.config)
    api = make_api(args, config)
    try:
        data = api.delete(args.env_id)
    except APIError as e:
        print(f"✗ {e}", file=sys.stderr)
        raise SystemExit(1)
    print(f"✓ {data.get('msg', 'deleted')}")


def cmd_list(args):
    config = Config(args.config)
    api = make_api(args, config)
    try:
        data = api.list_env()
    except APIError as e:
        print(f"✗ {e}", file=sys.stderr)
        raise SystemExit(1)
    envs = (data.get("data") or [])
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    if not envs:
        print("No environments.")
        return
    for e in envs:
        eid = e.get("id", "?")
        status = e.get("status", "?")
        name = e.get("devEnvName", "?")
        desc = e.get("devEnvDesc") or ""
        print(f"  {eid:<22}  {status:<10}  {name}  ({desc})")


def cmd_info(args):
    """Just print user@host:port for piping into another command."""
    config = Config(args.config)
    api = make_api(args, config)
    try:
        data = api.check_status(args.env_id)
    except APIError as e:
        print(f"✗ {e}", file=sys.stderr)
        raise SystemExit(1)
    out = normalize_machine_info(args.env_id, data.get("data") or {})
    host = out["host"]
    port = out["port"]
    user = out["user"]
    if not (host and port and user):
        raise SystemExit("Environment is not ready (no host/port/user yet)")
    print(f"{user}@{host}:{port}")


def cmd_ssh_config(args):
    """Print an ~/.ssh/config Host block for the env."""
    config = Config(args.config)
    api = make_api(args, config)
    try:
        data = api.check_status(args.env_id)
    except APIError as e:
        print(f"✗ {e}", file=sys.stderr)
        raise SystemExit(1)
    out = normalize_machine_info(args.env_id, data.get("data") or {})
    alias = re.sub(r"[^a-zA-Z0-9._-]", "-", f"openlibing-{out['devEnvId']}")
    key_file = out["identityFile"]
    if out["useProxy"] and out.get("targetIp"):
        block = (
            f"# Generated by openlibing-cli for {out['devEnvId']}\n"
            f"Host {alias}\n"
            f"    HostName {out['targetIp']}\n"
            f"    Port {out['targetPort']}\n"
            f"    User {out['user']}\n"
            f"    IdentityFile {key_file}\n"
            f"    IdentitiesOnly yes\n"
            f"    ProxyJump jump@{out['jumpIp']}:{out['jumpPort'] or 22}\n"
            f"    StrictHostKeyChecking no\n"
            f"    UserKnownHostsFile /dev/null\n"
        )
    else:
        block = (
            f"# Generated by openlibing-cli for {out['devEnvId']}\n"
            f"Host {alias}\n"
            f"    HostName {out['host']}\n"
            f"    Port {out['port']}\n"
            f"    User {out['user']}\n"
            f"    IdentityFile {key_file}\n"
            f"    IdentitiesOnly yes\n"
            f"    StrictHostKeyChecking no\n"
            f"    UserKnownHostsFile /dev/null\n"
        )
    sys.stdout.write(block)
    sys.stdout.write("\n")


def cmd_refresh(args):
    """Exchange sessionId for refreshToken, then exchange refreshToken
    for a fresh sessionId, and save the new sessionId to config."""
    config = Config(args.config)
    api = make_api(args, config)
    try:
        data = api.get_refresh_token()
        refresh = data.get("data")
        if not refresh:
            raise APIError("refreshToken missing in response", body=data)
        new_session = api.refresh_access_token(refresh)
    except APIError as e:
        print(f"✗ {e}", file=sys.stderr)
        raise SystemExit(1)
    config.set("session_id", new_session)
    print(f"✓ new sessionId saved ({new_session[:8]}…{new_session[-6:]})")


def cmd_keygen(args):
    pub = ssh_key.generate_keypair(force=args.force)
    print(f"✓ key generated")
    print(f"  private: {ssh_key.key_path()}")
    print(f"  public:  {ssh_key.pub_path()}")
    print()
    print(pub)


def cmd_whoami(args):
    config = Config(args.config)
    sid = resolve_session_id(args, config)
    print(f"env:        {resolve_env(args, config)}")
    print(f"baseURL:    {ENVIRONMENTS.get(resolve_env(args, config))}")
    print(f"user-id:    {config.get('user_id') or '(unset)'}")
    print(f"env-id:     {config.get('default_env_id') or '(unset)'}")
    print(f"session:    {sid[:8]}…{sid[-6:]}  ({len(sid)} chars)")
    print(f"config:     {config.path}")


# ---------- parser ---------------------------------------------------------


def build_parser():
    # Shared global flags — they can appear before OR after the subcommand.
    global_flags = argparse.ArgumentParser(add_help=False)
    global_flags.add_argument("--config", help="Path to config file (default: ~/.config/openlibing-cli/config.json)")
    global_flags.add_argument("--env", choices=list(ENVIRONMENTS.keys()),
                              help="Backend environment: prod (default), beta, alpha, alpha_yellow")
    global_flags.add_argument("--ticket", help="Session ticket — overrides env var and config file")
    global_flags.add_argument("--json", action="store_true", help="Output as JSON where supported")

    p = argparse.ArgumentParser(
        prog="openlibing",
        parents=[global_flags],
        description=(
            "Resource-manager access from the command line. Reverse-engineered "
            "from a vendor VS Code extension. Use your own "
            "session ticket (authTicket) to connect to your own environment."
        ),
    )
    p.add_argument("--version", action="version", version=f"openlibing-cli {__version__}")

    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # login
    sp = sub.add_parser("login", parents=[global_flags],
                        help="Save session ticket (and optional default env-id)")
    sp.add_argument("--uri", help="Full vscode://.../connect?... URI")
    sp.add_argument("--user-id", help="User ID (for reference)")
    sp.set_defaults(func=cmd_login)

    # connect
    sp = sub.add_parser("connect", parents=[global_flags],
                        help="Upload pub key + poll until running, print SSH info")
    sp.add_argument("env_id", help="Environment ID (envId from the deep link)")
    sp.add_argument("--generate-key", action="store_true",
                    help="Auto-generate ~/.ssh/id_rsa if missing")
    sp.add_argument("--force-keygen", action="store_true",
                    help="Re-generate the key pair (overwrites existing)")
    sp.add_argument("--no-wait", action="store_true", help="Don't poll — return immediately")
    sp.add_argument("--interval", type=float, default=5.0, help="Poll interval seconds (default 5)")
    sp.add_argument("--timeout", type=float, default=1800.0, help="Poll timeout seconds (default 1800)")
    sp.set_defaults(func=cmd_connect)

    # status
    sp = sub.add_parser("status", parents=[global_flags],
                        help="Check env status (no key upload side effect)")
    sp.add_argument("env_id", help="Environment ID")
    sp.set_defaults(func=cmd_status)

    # stop
    sp = sub.add_parser("stop", parents=[global_flags],
                        help="Disconnect env")
    sp.add_argument("env_id", help="Environment ID")
    sp.set_defaults(func=cmd_stop)

    # delete
    sp = sub.add_parser("delete", parents=[global_flags],
                        help="Delete env")
    sp.add_argument("env_id", help="Environment ID")
    sp.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    sp.set_defaults(func=cmd_delete)

    # list
    sp = sub.add_parser("list", parents=[global_flags], aliases=["ls"],
                        help="List my environments")
    sp.set_defaults(func=cmd_list)

    # info
    sp = sub.add_parser("info", parents=[global_flags],
                        help="Print just user@host:port (good for piping)")
    sp.add_argument("env_id", help="Environment ID")
    sp.set_defaults(func=cmd_info)

    # ssh-config
    sp = sub.add_parser("ssh-config", parents=[global_flags],
                        help="Print an SSH config Host block")
    sp.add_argument("env_id", help="Environment ID")
    sp.set_defaults(func=cmd_ssh_config)

    # refresh — exchange refresh token for new session id
    sp = sub.add_parser("refresh", parents=[global_flags],
                        help="Refresh sessionId via refreshToken")
    sp.set_defaults(func=cmd_refresh)

    # keygen
    sp = sub.add_parser("keygen", parents=[global_flags],
                        help="Generate RSA 2048 SSH key pair")
    sp.add_argument("--force", action="store_true", help="Overwrite existing")
    sp.set_defaults(func=cmd_keygen)

    # whoami
    sp = sub.add_parser("whoami", parents=[global_flags],
                        help="Show current session / config")
    sp.set_defaults(func=cmd_whoami)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
