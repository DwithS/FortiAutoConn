# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FortiAutoConn — a macOS menu bar app (built on `rumps`) that automates connecting to a FortiClient SSL-VPN. It wraps the `openfortivpn` CLI, drives it via `pexpect`, and auto-fills the OTP by watching a Daum/Kakao IMAP mailbox for an authentication-code email. Credentials are never stored in files — they live in the macOS Keychain (via `keyring`), gated behind Touch ID.

The README.md (in Korean) is the primary user-facing doc and describes the setup flow, IMAP prerequisites, and usage in detail — read it for product-level context.

## Commands

Setup (installs `openfortivpn` via Homebrew, Python deps into `.venv`, and a passwordless-sudo rule for `openfortivpn`/`route`):
```bash
./setup.sh
```

Run the app:
```bash
python3 app.py
```

Install/sync deps directly (uv is preferred; `uv.lock` is checked in):
```bash
uv pip install -r requirements.txt
# or
uv sync
```

There is no pytest suite. `tests/test_keychain.py` and `tests/test_mail.py` are standalone interactive scripts that require a live Touch ID prompt and/or real IMAP credentials already saved in Keychain (via the app's Settings UI). Run them directly:
```bash
python3 tests/test_keychain.py   # exercises Touch ID + Keychain read/write/delete
python3 tests/test_mail.py       # exercises IMAP login + live OTP-email polling
```

There is no linter/formatter configured in this repo.

## Architecture

Four modules compose around `app.py`, the `rumps.App` entry point:

- **app.py** — `FortiAutoConnApp` owns the menu bar UI (🔴/🟡/🟢 status icon), the Connect/Disconnect/Settings menu items, and the auto-reconnect state machine. It also embeds `SettingsHTTPServer`, a loopback-only (`127.0.0.1:18372`) HTTP server that serves an HTML settings form and writes submitted values straight to Keychain — this is how credentials get in, there is no config file. Connect requires a Touch ID prompt (`KeychainManager.authenticate_touch_id`) before credentials are read from Keychain; on success, credentials are cached in memory (`self.cached_creds`) only for the process lifetime, enabling silent background reconnects without re-prompting Touch ID. Reconnects use a capped exponential backoff (10s → 30s → 60s, max 3 attempts) before auto-reconnect disables itself to avoid account lockout.

- **vpn_connector.py** — `VPNConnector` spawns `sudo openfortivpn <host>:<port> -u <user>` via `pexpect` on a background thread and drives it as a state machine matching on expect patterns: password prompt → send password; OTP/2FA prompt → block on `mail_checker.fetch_latest_otp()` and send the result; gateway cert trust confirmation → auto-accept; `Tunnel is up and running` → mark connected. It self-heals untrusted internal gateway certs: on unexpected EOF it greps the process output for a sha256 cert digest, retries once with `--trusted-cert <hash>` baked in. Supports optional `--pppd-no-peerdns --no-dns` (DNS bypass) and `--no-routes` + manual `route add -net ... -interface pppN` (split tunneling) flags, both driven by Keychain-stored settings. After connecting, a second loop polls `process.isalive()` every 5s to detect session drops (e.g. 8-hour FortiGate session expiry).

- **mail_checker.py** — `MailChecker.fetch_latest_otp()` polls IMAP (SSL) every 3s up to `max_wait_seconds`, looking for a mail from a given sender within the last ~3 minutes whose subject/body matches `(?:AuthCode:\s*|Your authentication token code is\s*)(\d{6})`. Because the target mailbox folder name is often Korean (e.g. "DF VPN 인증"), this module hand-rolls IMAP Modified UTF-7 encoding (`encode_imap_utf7`) and bypasses `imaplib`'s SELECT quoting bugs entirely by writing a raw `SELECT "<folder>"` frame directly to the socket (`direct_imap_select`). Folder matching against the configured mailbox name is done byte-for-byte with a fuzzy keyword fallback, since `imaplib`'s own folder listing decoding is unreliable for non-ASCII names.

- **keychain_manager.py** — thin static wrapper: `authenticate_touch_id()` (via PyObjC `LocalAuthentication`, spun synchronously on `NSRunLoop` since the underlying API is async-callback-based) and `get_password`/`save_password`/`delete_password` (via `keyring`, i.e. the macOS Keychain). All credentials — VPN host/port/user/pass, IMAP host/port/user/pass/folder, and the DNS-bypass/split-tunnel/split-routes flags — are stored under the single Keychain service name `"FortiAutoConn"` (`FortiAutoConnApp.SERVICE_NAME`), keyed by field name.

- **logger.py** — module-level `logger` (name `"FortiAutoConn"`) writing to both stdout and a rotating file at `logs/fortiautoconn.log` (5MB × 5 backups). Every other module imports `from logger import logger` rather than configuring its own logging.

### Key constraints to keep in mind when editing

- This app only runs on macOS (PyObjC/`LocalAuthentication`/Keychain/`osascript` notifications throughout) and requires `openfortivpn` on PATH plus a `NOPASSWD` sudoers entry for it (and `/sbin/route` for split tunneling) — see `setup.sh`.
- All VPN/mail control flow is background-threaded (menu bar UI must stay responsive); UI updates from those threads are relayed back via `on_status_change` callbacks, never called directly from a worker thread.
- Credentials must never be written to disk/logs in plaintext — Keychain is the only persistence layer, and `SettingsHTTPServer` binds to loopback only.
