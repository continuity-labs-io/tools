#!/usr/bin/env python3
"""Oura API V2 sync: OAuth2 (authorization code + PKCE) and nightly telemetry.

Usage:
    python src/oura/oura_sync.py --auth                 # one-time browser handshake
    python src/oura/oura_sync.py                        # last 7 nights -> src/oura/sleep.json
    python src/oura/oura_sync.py --days 14 --out -      # JSON to stdout

OURA_CLIENT_ID / OURA_CLIENT_SECRET are resolved lazily -- only for the --auth code
exchange or an actual token refresh -- so routine fetches with a valid cached access
token never touch them. They are read from the environment, or from a .env file in the
current directory or next to this script (real environment variables win).

A value prefixed with "cmd:" is treated as a command whose stdout is the secret, so
secrets can live in any external store without being written to disk, e.g.:

    OURA_CLIENT_SECRET="cmd:my-secret-tool get oura/client_secret"

The command is split with shlex and run directly (no shell).

Tokens live in ~/.oura_tokens.json (mode 0600). Oura refresh tokens are single-use,
so every new token pair is written atomically (tmp file + fsync + os.replace) under
an exclusive lock, so a crash or a concurrent run can't break the refresh chain.

Logs go to stderr. The JSON report is written to sleep.json next to this script (git-ignored)
unless --out names another file, or `--out -` sends it to stdout for piping.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import functools
import hashlib
import http.server
import json
import logging
import os
import secrets
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger("oura_sync")

AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
API_BASE = "https://api.ouraring.com"

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"
SCOPES = "daily heartrate personal workout tag session spo2Daily"

CMD_PREFIX = "cmd:"
CMD_TIMEOUT_S = 120

TOKEN_PATH = Path.home() / ".oura_tokens.json"
DEFAULT_OUT = Path(__file__).resolve().parent / "sleep.json"
EXPIRY_MARGIN_S = 300
AUTH_TIMEOUT_S = 300
HTTP_TIMEOUT_S = 30
USER_AGENT = "oura-sync/1.0 (python-urllib)"

# Nadir position thresholds (fraction of the sleep window).
EARLY_DROP_BEFORE = 0.35
LATE_SLOPE_AFTER = 0.70


class OuraError(RuntimeError):
    """Expected, user-actionable failure (bad config, rejected token, network)."""


class ApiHTTPError(OuraError):
    def __init__(self, status: int, url: str, body: str) -> None:
        super().__init__(f"HTTP {status} from {url}: {body[:500]}")
        self.status = status
        self.body = body


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

def load_dotenv(paths: list[Path]) -> None:
    """Minimal .env parser. Existing environment variables always win."""
    for path in paths:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)
        logger.info("Loaded settings from %s", path)


@functools.cache
def _load_local_dotenv() -> None:
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parent / ".env"]
    load_dotenv(list(dict.fromkeys(p.resolve() for p in candidates)))


def _run_secret_command(env_var: str, command: str) -> str:
    """Run a `cmd:` helper (no shell) and return its stripped stdout."""
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise OuraError(f"Could not parse the cmd: value for {env_var} ({exc}).") from None
    if not argv:
        raise OuraError(f"The cmd: value for {env_var} is empty.")

    logger.info("Resolving %s via its cmd: helper.", env_var)
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, check=True, timeout=CMD_TIMEOUT_S
        )
    except FileNotFoundError:
        raise OuraError(f"Failed to resolve {env_var}: command {argv[0]!r} not found.") from None
    except subprocess.TimeoutExpired:
        raise OuraError(f"Failed to resolve {env_var}: helper timed out after {CMD_TIMEOUT_S}s.") from None
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise OuraError(f"Failed to resolve {env_var}: helper exited with {exc.returncode}{suffix}") from None

    secret = result.stdout.strip()
    if not secret:
        raise OuraError(f"Failed to resolve {env_var}: helper produced no output.")
    return secret


@functools.cache
def get_credential(env_var: str) -> str:
    """Resolve a secret from env/.env; `cmd:` values are executed (cached per process)."""
    _load_local_dotenv()
    value = os.environ.get(env_var, "").strip()
    if not value:
        raise OuraError(f"{env_var} is not set (environment or .env file).")
    if value.startswith(CMD_PREFIX):
        return _run_secret_command(env_var, value[len(CMD_PREFIX):])
    return value


def get_client_credentials() -> tuple[str, str]:
    """Only call where a client id/secret is actually needed (code exchange, refresh)."""
    return get_credential("OURA_CLIENT_ID"), get_credential("OURA_CLIENT_SECRET")


# --------------------------------------------------------------------------- #
# Token storage
# --------------------------------------------------------------------------- #

def _lock_path() -> Path:
    return TOKEN_PATH.with_name(TOKEN_PATH.name + ".lock")


@contextmanager
def token_lock() -> Iterator[None]:
    """Exclusive inter-process lock around any read-refresh-write of the token pair."""
    fd = os.open(_lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def save_tokens(tokens: dict[str, Any]) -> None:
    """Atomically persist tokens with 0600 permissions."""
    tmp = TOKEN_PATH.with_name(TOKEN_PATH.name + ".tmp")
    data = (json.dumps(tokens, indent=2) + "\n").encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        os.fchmod(fh.fileno(), 0o600)  # in case tmp pre-existed with looser perms
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, TOKEN_PATH)
    # Make the rename itself durable.
    dir_fd = os.open(TOKEN_PATH.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def load_tokens() -> dict[str, Any] | None:
    try:
        raw = TOKEN_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        tokens = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OuraError(f"{TOKEN_PATH} is not valid JSON ({exc}). Re-run with --auth.") from None
    missing = {"access_token", "refresh_token", "expires_at"} - set(tokens)
    if missing:
        raise OuraError(f"{TOKEN_PATH} is missing {sorted(missing)}. Re-run with --auth.")
    mode = TOKEN_PATH.stat().st_mode & 0o777
    if mode & 0o077:
        logger.info("Tightening permissions on %s (was %o).", TOKEN_PATH, mode)
        os.chmod(TOKEN_PATH, 0o600)
    return tokens


def tokens_from_response(payload: dict[str, Any], previous_refresh: str | None = None) -> dict[str, Any]:
    access = payload.get("access_token")
    if not access:
        raise OuraError("Token response did not include an access_token.")
    refresh = payload.get("refresh_token")
    if not refresh:
        if not previous_refresh:
            raise OuraError("Token response did not include a refresh_token.")
        logger.warning("Token response had no refresh_token; keeping the previous one.")
        refresh = previous_refresh
    expires_in = int(payload.get("expires_in") or 86400)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int(time.time() + expires_in - EXPIRY_MARGIN_S),
    }


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def _request_json(req: urllib.request.Request) -> dict[str, Any]:
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise ApiHTTPError(exc.code, req.full_url, exc.read().decode("utf-8", "replace")) from None
    except urllib.error.URLError as exc:
        raise OuraError(f"Network error contacting {req.full_url}: {exc.reason}") from None
    return json.loads(body) if body else {}


def post_token(form: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(form).encode("ascii"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return _request_json(req)


# --------------------------------------------------------------------------- #
# --auth: authorization code + PKCE handshake
# --------------------------------------------------------------------------- #

def generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)  # 48 random bytes -> exactly 64 URL-safe chars
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class _CallbackServer(http.server.HTTPServer):
    allow_reuse_address = True

    def __init__(self, expected_state: str) -> None:
        super().__init__((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler)
        self.expected_state = expected_state
        self.result: dict[str, str] | None = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    server: _CallbackServer

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/callback":
            self._reply(404, "Not found.")  # e.g. /favicon.ico; keep waiting
            return
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if "error" in params:
            detail = params.get("error_description", "")
            self.server.result = {"error": f"{params['error']} {detail}".strip()}
            self._reply(400, f"Oura authorization failed: {params['error']}. You can close this tab.")
        elif params.get("state") != self.server.expected_state:
            self.server.result = {"error": "state mismatch (possible stale or forged callback)"}
            self._reply(400, "State mismatch. Please re-run the auth command.")
        elif not params.get("code"):
            self.server.result = {"error": "callback did not include an authorization code"}
            self._reply(400, "No authorization code received.")
        else:
            self.server.result = {"code": params["code"]}
            self._reply(200, "Oura authorization received. You can close this tab and return to the terminal.")

    def _reply(self, status: int, text: str) -> None:
        body = (text + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("callback server: " + fmt, *args)


def _wait_for_callback(server: _CallbackServer) -> dict[str, str]:
    deadline = time.monotonic() + AUTH_TIMEOUT_S
    while server.result is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise OuraError(f"Timed out after {AUTH_TIMEOUT_S}s waiting for the Oura callback.")
        server.timeout = remaining
        server.handle_request()
    return server.result


def run_auth_flow() -> dict[str, Any]:
    # Resolve up front: client_id is needed for the authorize URL, and failing here
    # avoids a wasted browser round-trip.
    client_id, client_secret = get_client_credentials()
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        quote_via=urllib.parse.quote,
    )
    auth_url = f"{AUTHORIZE_URL}?{query}"

    try:
        server = _CallbackServer(state)
    except OSError as exc:
        raise OuraError(f"Could not listen on {CALLBACK_HOST}:{CALLBACK_PORT} ({exc}). Is the port in use?") from None

    with server:
        logger.info("Opening the Oura authorization page in your browser.")
        logger.info("If it does not open, visit this URL manually:\n%s", auth_url)
        webbrowser.open(auth_url)
        result = _wait_for_callback(server)

    if "error" in result:
        raise OuraError(f"Authorization failed: {result['error']}")

    logger.info("Authorization code received; exchanging it for tokens.")
    payload = post_token(
        {
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
        }
    )
    tokens = tokens_from_response(payload)
    with token_lock():
        save_tokens(tokens)
    logger.info("Tokens saved to %s.", TOKEN_PATH)
    return tokens


# --------------------------------------------------------------------------- #
# API client with automatic refresh
# --------------------------------------------------------------------------- #

class OuraClient:
    def __init__(self, tokens: dict[str, Any]) -> None:
        self.tokens = tokens

    def _refresh(self, reason: str) -> None:
        with token_lock():
            on_disk = load_tokens()
            # Another process may have rotated the pair while we waited for the lock.
            if (
                on_disk
                and on_disk["access_token"] != self.tokens["access_token"]
                and time.time() < on_disk["expires_at"]
            ):
                logger.info("Tokens were already refreshed by another run; using those.")
                self.tokens = on_disk
                return
            current = on_disk or self.tokens
            client_id, client_secret = get_client_credentials()
            logger.info("Refreshing access token (%s).", reason)
            try:
                payload = post_token(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": current["refresh_token"],
                        "client_id": client_id,
                        "client_secret": client_secret,
                    }
                )
            except ApiHTTPError as exc:
                if exc.status in (400, 401):
                    raise OuraError(
                        "Oura rejected the refresh token (already used or revoked). Re-run with --auth."
                    ) from exc
                raise
            self.tokens = tokens_from_response(payload, previous_refresh=current["refresh_token"])
            save_tokens(self.tokens)  # persist the single-use pair before doing anything else
        expiry = dt.datetime.fromtimestamp(self.tokens["expires_at"]).strftime("%Y-%m-%d %H:%M")
        logger.info("New token pair saved; access token good until about %s.", expiry)

    def get_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if time.time() >= self.tokens["expires_at"]:
            self._refresh("access token expired")
        url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
        for attempt in (1, 2):
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.tokens['access_token']}"})
            try:
                return _request_json(req)
            except ApiHTTPError as exc:
                if exc.status == 401 and attempt == 1:
                    self._refresh("API returned 401")
                    continue
                raise
        raise AssertionError("unreachable")

    def fetch_collection(self, name: str, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
        params = {"start_date": start.isoformat(), "end_date": end.isoformat()}
        records: list[dict[str, Any]] = []
        while True:
            page = self.get_json(f"/v2/usercollection/{name}", params)
            records.extend(page.get("data") or [])
            next_token = page.get("next_token")
            if not next_token:
                break
            params = {**params, "next_token": next_token}
        logger.info("Fetched %d %s records (%s to %s).", len(records), name, start, end)
        return records


# --------------------------------------------------------------------------- #
# Telemetry & metabolic curve
# --------------------------------------------------------------------------- #

def _hours(seconds: Any) -> float | None:
    return round(seconds / 3600, 2) if isinstance(seconds, (int, float)) else None


def _round(value: Any, ndigits: int = 2) -> float | None:
    return round(float(value), ndigits) if isinstance(value, (int, float)) else None


def _parse_ts(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def classify_curve(nadir_pct: float) -> str:
    if nadir_pct < EARLY_DROP_BEFORE:
        return "early_drop"
    if nadir_pct <= LATE_SLOPE_AFTER:
        return "hammock"
    return "late_slope"


def analyze_hr_curve(record: dict[str, Any]) -> tuple[float | None, str | None]:
    """Locate the overnight HR nadir and express it as a fraction of the sleep window."""
    hr = record.get("heart_rate") or {}
    items = hr.get("items") or []
    valid = [(i, v) for i, v in enumerate(items) if isinstance(v, (int, float)) and v > 0]
    if not valid:
        return None, None
    nadir_idx = min(valid, key=lambda pair: pair[1])[0]

    pct: float | None = None
    start = _parse_ts(record.get("bedtime_start"))
    end = _parse_ts(record.get("bedtime_end"))
    series_start = _parse_ts(hr.get("timestamp")) or start
    interval = hr.get("interval") or 300
    try:
        if start and end and series_start and end > start:
            nadir_time = series_start + dt.timedelta(seconds=nadir_idx * interval)
            pct = (nadir_time - start).total_seconds() / (end - start).total_seconds()
    except TypeError:  # naive vs aware timestamps; fall back to sample position
        pct = None
    if pct is None:
        if len(items) < 2:
            return None, None
        pct = nadir_idx / (len(items) - 1)

    pct = min(max(pct, 0.0), 1.0)
    return round(pct, 3), classify_curve(pct)


def build_nights(sleep_records: list[dict[str, Any]], readiness_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    readiness_by_day = {r["day"]: r for r in readiness_records if r.get("day")}

    primary: dict[str, dict[str, Any]] = {}
    for rec in sleep_records:
        day = rec.get("day")
        if rec.get("type") != "long_sleep" or not day:
            continue
        # If Oura reports more than one long_sleep for a day, keep the longest.
        if (rec.get("total_sleep_duration") or 0) > (primary.get(day, {}).get("total_sleep_duration") or -1):
            primary[day] = rec

    nights = []
    for day in sorted(primary):
        rec = primary[day]
        readiness = readiness_by_day.get(day, {})
        temp_delta = readiness.get("temperature_deviation")
        if temp_delta is None:
            temp_delta = (rec.get("readiness") or {}).get("temperature_deviation")
        nadir_pct, curve = analyze_hr_curve(rec)
        nights.append(
            {
                "day": day,
                "bedtime_start": rec.get("bedtime_start"),
                "bedtime_end": rec.get("bedtime_end"),
                "total_sleep_hours": _hours(rec.get("total_sleep_duration")),
                "deep_sleep_hours": _hours(rec.get("deep_sleep_duration")),
                "rem_sleep_hours": _hours(rec.get("rem_sleep_duration")),
                "lowest_heart_rate": rec.get("lowest_heart_rate"),
                "average_heart_rate": _round(rec.get("average_heart_rate"), 1),
                "average_hrv": rec.get("average_hrv"),
                "temperature_delta": _round(temp_delta, 2),
                "respiratory_rate": _round(rec.get("average_breath"), 2),
                "readiness_score": readiness.get("score"),
                "nadir_timing_pct": nadir_pct,
                "hr_curve_shape": curve,
            }
        )
    return nights


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Oura API V2 sleep/readiness sync for metabolic calibration.")
    parser.add_argument("--auth", action="store_true", help="run the one-time OAuth2 browser handshake and exit")
    parser.add_argument("--days", type=int, default=7, help="number of past days to fetch (default: 7)")
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help=f"output file, or '-' for stdout (default: {DEFAULT_OUT.name} next to this script)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be at least 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    try:
        if args.auth:
            run_auth_flow()
            logger.info("Authorization complete. Run without --auth to fetch telemetry.")
            return 0

        tokens = load_tokens()
        if tokens is None:
            if not sys.stdin.isatty():
                logger.error("No tokens at %s. Run once interactively with --auth.", TOKEN_PATH)
                return 1
            logger.info("No tokens at %s yet; starting the one-time authorization.", TOKEN_PATH)
            tokens = run_auth_flow()

        client = OuraClient(tokens)
        today = dt.date.today()
        start = today - dt.timedelta(days=args.days)
        end = today + dt.timedelta(days=1)  # end_date is exclusive

        sleep = client.fetch_collection("sleep", start, end)
        readiness = client.fetch_collection("daily_readiness", start, end)
        nights = build_nights(sleep, readiness)

        report = {
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "nights": nights,
        }
        text = json.dumps(report, indent=2)
        if args.out == "-":
            print(text)
            logger.info("Summarized %d nights.", len(nights))
        else:
            out_path = Path(args.out)
            out_path.write_text(text + "\n", encoding="utf-8")
            logger.info("Wrote %d nights to %s.", len(nights), out_path)
        return 0
    except OuraError as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
