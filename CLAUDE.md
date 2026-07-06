# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FortiAutoConn — a macOS menu bar app (built on `rumps`) that automates connecting to a FortiClient SSL-VPN. It wraps the `openfortivpn` CLI, drives it via `pexpect`, and auto-fills the OTP by watching a Daum/Kakao IMAP mailbox for an authentication-code email. Only the two passwords (VPN + mail) live in the macOS Keychain (via `keyring`), gated behind Touch ID; everything else (host/port/username/folder/DNS/split-tunnel settings) lives in a plain local JSON file.

The README.md (in Korean) is the primary user-facing doc and describes the setup flow, IMAP prerequisites, and usage in detail — read it for product-level context.

## Commands

Setup (installs `openfortivpn` via Homebrew, Python deps into `.venv`, and a passwordless-sudo rule for `openfortivpn`/`route`):
```bash
./setup.sh
```

Run the app:
```bash
./run.sh        # picks .venv/bin/python3 (or system python3), and runs it via a 'forti-auto' launcher
```
`run.sh`/`autostart.sh` don't invoke the interpreter directly — they build `.venv/bin/forti-auto`, an independent *copy* of the interpreter binary, ad-hoc re-signed with identifier `com.dailyfunding.forti-auto`. This makes Touch ID / Keychain system prompts show "forti-auto" instead of "python3.12" (macOS shows a symlink's *target* name, so this requires a real copy — see comments in `run.sh`). Never re-sign the original interpreter file in place; that mutates a binary shared by other venvs/tools.

Login auto-start (installs/removes a LaunchAgent at `~/Library/LaunchAgents/com.dailyfunding.fortiautoconn.plist`):
```bash
./autostart.sh install|uninstall|status
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

- **app.py** — `FortiAutoConnApp` owns the menu bar UI (🔴/🟡/🟢 status icon), the Connect/Disconnect/Settings menu items, and the auto-reconnect state machine. It also embeds `SettingsHTTPServer`, a loopback-only (`127.0.0.1:18372`) HTTP server that serves an HTML settings form and writes submitted values via `FortiAutoConnApp.save_config()`. Config is split across two stores, both accessed only through `FortiAutoConnApp.load_config()` / `save_config(updates)` (a merged-dict interface — callers never touch the two stores directly): the two passwords (`vpn_pass`, `mail_pass`, `SECRET_FIELDS`) go to a single Keychain item (service `SERVICE_NAME`, account `CONFIG_ACCOUNT="config"`, JSON-encoded); everything else goes to a plain JSON file at `CONFIG_FILE` (`~/Library/Application Support/FortiAutoConn/config.json`, chmod 600). This split exists because macOS prompts for Keychain-access approval *per item* — keeping only the 2 secrets there means there's only ever one such prompt, ever. `load_config()` auto-migrates on first run from either of two older formats (a single combined Keychain blob, or the original one-Keychain-item-per-field layout) and deletes the stale per-field items once migrated. Connect requires a Touch ID prompt (`KeychainManager.authenticate_touch_id`) before credentials are read; on success, credentials are cached in memory (`self.cached_creds`) only for the process lifetime, enabling silent background reconnects without re-prompting Touch ID. Reconnects use a capped exponential backoff (10s → 30s → 60s, max 3 attempts) before auto-reconnect disables itself to avoid account lockout; it also inspects `VPNConnector.failure_reason` and disables auto-reconnect immediately (no retry) for non-retryable causes (`REASON_MAIL_AUTH`, `REASON_VPN_AUTH`, `REASON_SUDO`, `REASON_OTP`) to avoid hammering a locked-out account.

- **vpn_connector.py** — `VPNConnector` spawns `sudo openfortivpn <host>:<port> -u <user>` via `pexpect` on a background thread and drives it as a state machine matching on expect patterns: password prompt → send password; OTP/2FA prompt → block on `mail_checker.fetch_latest_otp()` and send the result; gateway cert trust confirmation → auto-accept; `Tunnel is up and running` → mark connected. It self-heals untrusted internal gateway certs: on unexpected EOF it greps the process output for a sha256 cert digest, retries once with `--trusted-cert <hash>` baked in. Supports `--pppd-no-peerdns --no-dns` (DNS bypass) and `--no-routes` + manual `route add -net ... -interface pppN` (split tunneling); enabling split tunneling force-enables DNS bypass too (the split routes rarely include the corporate DNS server, so without bypass all name resolution breaks and it looks like "the whole internet is down"). After connecting, a health-check loop polls every 5s — it checks *both* `process.isalive()` *and* that the `ppp` interface is still `UP,RUNNING` (`_is_ppp_interface_up`), because `self.process` is the `sudo` wrapper pexpect watches, not the actual `openfortivpn`/`pppd` child; the child can die (e.g. 8-hour FortiGate session expiry) while `sudo` lingers un-reaped, which previously left the UI showing 🟢 connected long after the tunnel was actually dead.

- **mail_checker.py** — `MailChecker.fetch_latest_otp()` logs into IMAP **once** and reuses that connection, re-selecting the mailbox and re-searching every 3s up to `max_wait_seconds` (re-logging in per poll previously caused ~30 logins per connection attempt and tripped the mail provider's brute-force lockout). It looks for mail from a given sender within the last ~60s whose subject/body matches `(?:AuthCode:\s*|Your authentication token code is\s*)(\d{6})`, and refuses to reuse an already-consumed OTP message id across reconnect attempts. `verify_login()` does a cheap pre-flight login check — `VPNConnector` calls it before submitting the VPN password at all, so a broken mail password can't trigger repeated "submit VPN password → wait for OTP → fail" cycles that spam auth-request emails and risk locking the account. If the server explicitly rejects login (bad password), `auth_failed` is set and callers must not retry. Because the target mailbox folder name is often Korean (e.g. "DF VPN 인증"), this module hand-rolls IMAP Modified UTF-7 encoding (`encode_imap_utf7`) and bypasses `imaplib`'s SELECT quoting bugs entirely by writing a raw `SELECT "<folder>"` frame directly to the socket (`direct_imap_select`). Folder matching against the configured mailbox name is done byte-for-byte with a fuzzy keyword fallback, since `imaplib`'s own folder listing decoding is unreliable for non-ASCII names.

- **keychain_manager.py** — thin static wrapper: `authenticate_touch_id()` (via PyObjC `LocalAuthentication`, spun synchronously on `NSRunLoop` since the underlying API is async-callback-based) and `get_password`/`save_password`/`delete_password` (via `keyring`, i.e. the macOS Keychain). Only used for the single consolidated secrets item now (see `app.py`'s config-split note above) — don't add new per-field Keychain items for non-secret settings.

- **logger.py** — module-level `logger` (name `"FortiAutoConn"`) writing to both stdout and a rotating file at `logs/fortiautoconn.log` (5MB × 5 backups). Every other module imports `from logger import logger` rather than configuring its own logging.

### Key constraints to keep in mind when editing

- This app only runs on macOS (PyObjC/`LocalAuthentication`/Keychain/`osascript` notifications throughout) and requires `openfortivpn` on PATH plus a `NOPASSWD` sudoers entry for it (and `/sbin/route` for split tunneling) — see `setup.sh`.
- All VPN/mail control flow is background-threaded (menu bar UI must stay responsive); UI updates from those threads are relayed back via `on_status_change` callbacks, never called directly from a worker thread.
- The two passwords must never be written to disk/logs in plaintext or added back to the local config file — Keychain is the only store for `SECRET_FIELDS`. `SettingsHTTPServer` binds to loopback only.
