"""Windows helper entry point for FortiAutoConn.

This is a Windows MVP/fallback path. Full FortiClient CLI automation (A안) is
not assumed: local probing shows the installed FortiVPN.exe only exposes help
for `-h/--help` and `-s/--scheduler`, with no documented stdin-friendly
connect/password/OTP interface. Therefore this module implements B안:

- store settings in %APPDATA% + secrets in Windows Credential Manager via keyring
- open the FortiClient VPN UI
- watch the configured IMAP mailbox for the OTP
- copy the OTP to the Windows clipboard so the user can paste it into FortiClient
"""

from __future__ import annotations

import argparse
import ctypes
import html
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import keyring

from logger import logger
from mail_checker import MailChecker


SERVICE_NAME = "FortiAutoConn"
CONFIG_ACCOUNT = "windows-config"
SECRET_FIELDS = {"vpn_pass", "mail_pass"}
CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "FortiAutoConn"
CONFIG_FILE = CONFIG_DIR / "config.json"
SETTINGS_PORT = 18372
TRAY_MUTEX_NAME = "Local\\FortiAutoConn.Tray"
STARTUP_LAUNCHER_NAME = "FortiAutoConn.vbs"
LEGACY_STARTUP_CMD_NAME = "FortiAutoConn.cmd"
DEFAULT_FORTICLIENT_PATHS = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Fortinet" / "FortiClient" / "FortiVPN.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Fortinet" / "FortiClient" / "FortiClient.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Fortinet" / "FortiClient" / "FortiVPN.exe",
]


def get_startup_launcher_path() -> Path:
    return (
        Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / STARTUP_LAUNCHER_NAME
    )


def get_legacy_startup_cmd_path() -> Path:
    return get_startup_launcher_path().with_name(LEGACY_STARTUP_CMD_NAME)


def get_startup_target() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(__file__).with_name("run_windows.bat")


def is_startup_enabled() -> bool:
    return get_startup_launcher_path().exists() or get_legacy_startup_cmd_path().exists()


def set_startup_enabled(enabled: bool) -> None:
    startup_launcher = get_startup_launcher_path()
    legacy_startup_cmd = get_legacy_startup_cmd_path()
    if not enabled:
        for path in (startup_launcher, legacy_startup_cmd):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        return

    target = get_startup_target()
    startup_launcher.parent.mkdir(parents=True, exist_ok=True)
    try:
        legacy_startup_cmd.unlink()
    except FileNotFoundError:
        pass
    command = f'"{target}" tray'
    startup_launcher.write_text(
        "Set shell = CreateObject(\"WScript.Shell\")\n"
        f"shell.CurrentDirectory = \"{str(target.parent).replace(chr(34), chr(34) + chr(34))}\"\n"
        f"shell.Run \"{command.replace(chr(34), chr(34) + chr(34))}\", 0, False\n",
        encoding="utf-8",
    )


class SingleInstanceLock:
    """Best-effort single-instance guard for the Windows tray process."""

    def __init__(self, name: str, timeout_seconds: float = 0.0):
        self.name = name
        self.timeout_seconds = timeout_seconds
        self._handle = None
        self._owns_mutex = False
        self._lock_file: Path | None = None

    def acquire(self) -> bool:
        if os.name == "nt":
            return self._acquire_windows_mutex()
        return self._acquire_lock_file()

    def release(self) -> None:
        if os.name == "nt":
            self._release_windows_mutex()
            return
        self._release_lock_file()

    def _acquire_windows_mutex(self) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        kernel32.WaitForSingleObject.restype = ctypes.c_uint

        ERROR_ALREADY_EXISTS = 183
        WAIT_OBJECT_0 = 0x00000000
        WAIT_ABANDONED = 0x00000080
        WAIT_TIMEOUT = 0x00000102
        INFINITE = 0xFFFFFFFF

        self._handle = kernel32.CreateMutexW(None, True, self.name)
        if not self._handle:
            err = ctypes.get_last_error()
            logger.warning(f"[Windows] 중복 실행 방지 mutex 생성 실패: last_error={err}")
            return True

        if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
            self._owns_mutex = True
            return True

        wait_ms = INFINITE if self.timeout_seconds < 0 else int(self.timeout_seconds * 1000)
        wait_result = kernel32.WaitForSingleObject(self._handle, wait_ms)
        if wait_result in (WAIT_OBJECT_0, WAIT_ABANDONED):
            self._owns_mutex = True
            return True
        if wait_result != WAIT_TIMEOUT:
            logger.warning(f"[Windows] 중복 실행 방지 mutex 대기 실패: result={wait_result}")
        self._release_windows_mutex()
        return False

    def _release_windows_mutex(self) -> None:
        if not self._handle:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        if self._owns_mutex:
            kernel32.ReleaseMutex(self._handle)
        kernel32.CloseHandle(self._handle)
        self._handle = None
        self._owns_mutex = False

    def _acquire_lock_file(self) -> bool:
        self._lock_file = CONFIG_DIR / "tray.lock"
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                fd = os.open(str(self._lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as fp:
                    fp.write(str(os.getpid()))
                return True
            except FileExistsError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.1)

    def _release_lock_file(self) -> None:
        if not self._lock_file:
            return
        try:
            self._lock_file.unlink()
        except FileNotFoundError:
            pass
        self._lock_file = None


class WindowsConfig:
    @staticmethod
    def _read_plain() -> dict:
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}

    @staticmethod
    def _write_plain(data: dict) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _read_secret() -> dict:
        raw = keyring.get_password(SERVICE_NAME, CONFIG_ACCOUNT)
        try:
            return json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _write_secret(data: dict) -> None:
        keyring.set_password(SERVICE_NAME, CONFIG_ACCOUNT, json.dumps(data, ensure_ascii=False))

    @classmethod
    def load(cls) -> dict:
        merged = cls._read_plain()
        # Windows tray MVP keeps OTP watching and safe auto-paste enabled by default.
        # The tray no longer exposes toggles for these internal defaults.
        merged["auto_watch_otp"] = "true"
        merged["auto_paste_otp"] = "true"
        merged.update(cls._read_secret())
        return merged

    @classmethod
    def save(cls, updates: dict) -> dict:
        plain_updates = {k: v for k, v in updates.items() if k not in SECRET_FIELDS}
        secret_updates = {k: v for k, v in updates.items() if k in SECRET_FIELDS and v}
        if plain_updates:
            plain = cls._read_plain()
            plain.update(plain_updates)
            cls._write_plain(plain)
        if secret_updates:
            secret = cls._read_secret()
            secret.update(secret_updates)
            cls._write_secret(secret)
        return cls.load()


def find_forticlient() -> Path | None:
    configured = WindowsConfig.load().get("forticlient_path")
    candidates = [Path(configured)] if configured else []
    candidates.extend(DEFAULT_FORTICLIENT_PATHS)
    for path in candidates:
        if path and path.exists():
            return path
    return None


def probe_forticlient_cli(path: Path) -> str:
    """Return a short, non-secret CLI capability summary for FortiClient."""
    def _run(args: list[str]) -> str:
        proc = subprocess.run(
            [str(path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return (proc.stdout + proc.stderr).strip()

    try:
        cli_output = _run(["--cli"])
    except Exception as exc:
        return f"CLI probe 실행 실패: {exc}"

    if "Option 'cli' does not exist" in cli_output or "Option 'cli'" in cli_output:
        try:
            help_output = _run(["--help"])
        except Exception:
            help_output = ""
        return (
            "이 FortiClient는 FortiVPN.exe --cli를 지원하지 않습니다. "
            "문서상 --cli 자동 연결은 FortiClient Standalone 7.4.7+ 및 FortiClient 8.0.0에서 확인되며, "
            "현재 설치본에서는 B안(Tray + OTP 클립보드)만 사용 가능합니다.\n"
            + help_output[:800]
        ).strip()
    if "--connect" in cli_output and "--tunnel" in cli_output:
        return (
            "FortiVPN.exe --cli 자동 연결 기능이 감지되었습니다. "
            "단, 문서상 이미 FortiClient GUI/EMS에 구성된 터널만 연결할 수 있고 새 터널 생성은 불가합니다. "
            "또한 OTP 인자 옵션은 문서에 없어 이메일 OTP 2차 인증은 별도 확인이 필요합니다.\n"
            + cli_output[:1200]
        ).strip()
    if not cli_output:
        return "FortiVPN.exe --cli 출력이 비어 있어 자동 연결 지원 여부를 확인하지 못했습니다."
    return cli_output[:1200]


def copy_to_clipboard(text: str) -> bool:
    if os.name == "nt":
        if copy_to_clipboard_win32(text):
            return True

    try:
        import tkinter  # stdlib on normal Python installs; fallback for non-Windows/dev mode

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception as exc:
        logger.warning(f"[Windows] 클립보드 복사 실패: {exc}")
        return False


def copy_to_clipboard_win32(text: str) -> bool:
    """Copy Unicode text via Win32 clipboard APIs; more reliable in PyInstaller/windowed exe than tkinter."""
    if os.name != "nt":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    handle = None
    opened = False
    try:
        # The clipboard can be briefly busy; retry instead of dropping the OTP.
        for _ in range(10):
            if user32.OpenClipboard(None):
                opened = True
                break
            time.sleep(0.05)
        if not opened:
            err = ctypes.get_last_error()
            logger.warning(f"[Windows] 클립보드 열기 실패: last_error={err}")
            return False

        if not user32.EmptyClipboard():
            err = ctypes.get_last_error()
            logger.warning(f"[Windows] 클립보드 비우기 실패: last_error={err}")
            return False

        data = (text + "\0").encode("utf-16-le")
        kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
        kernel32.GlobalUnlock.restype = ctypes.c_bool
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            err = ctypes.get_last_error()
            logger.warning(f"[Windows] 클립보드 메모리 할당 실패: last_error={err}")
            return False
        locked = kernel32.GlobalLock(handle)
        if not locked:
            err = ctypes.get_last_error()
            logger.warning(f"[Windows] 클립보드 메모리 잠금 실패: last_error={err}")
            return False
        ctypes.memmove(locked, data, len(data))
        kernel32.GlobalUnlock(handle)

        user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
        user32.SetClipboardData.restype = ctypes.c_void_p
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            err = ctypes.get_last_error()
            logger.warning(f"[Windows] 클립보드 데이터 설정 실패: last_error={err}")
            return False
        # Ownership transferred to the OS after SetClipboardData succeeds.
        handle = None
        return True
    except Exception as exc:
        logger.warning(f"[Windows] Win32 클립보드 복사 실패: {exc}")
        return False
    finally:
        if opened:
            user32.CloseClipboard()
        if handle:
            try:
                kernel32.GlobalFree.argtypes = (ctypes.c_void_p,)
                kernel32.GlobalFree(handle)
            except Exception:
                pass


def is_running_as_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:
        logger.warning(f"[Windows] 관리자 권한 확인 실패: {exc}")
        return False


def relaunch_tray_as_admin() -> bool:
    """Ask UAC to start a new elevated tray process. The current process cannot elevate in-place."""
    if os.name != "nt":
        return False
    try:
        app_path = Path(__file__).with_name("app.py")
        params = f'"{app_path}" tray'
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, str(Path.cwd()), 1)
        return int(result) > 32
    except Exception as exc:
        logger.warning(f"[Windows] 관리자 권한 재실행 실패: {exc}")
        return False


def get_active_window_title() -> str:
    """Return the foreground window title on Windows; empty on failure/non-Windows."""
    if os.name != "nt":
        return ""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value or ""
    except Exception as exc:
        logger.warning(f"[Windows] 활성 창 제목 확인 실패: {exc}")
        return ""


def _window_title_matches(title: str) -> bool:
    allowed = ("forticlient", "fortivpn", "forticlient vpn")
    return any(token in title.lower() for token in allowed)


def find_forticlient_window_title() -> str:
    """Return a visible FortiClient/FortiVPN window title without changing focus."""
    if os.name != "nt":
        return ""
    try:
        user32 = ctypes.windll.user32
        matches: list[str] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value or ""
            if _window_title_matches(title):
                matches.append(title)
                return False
            return True

        user32.EnumWindows(enum_proc, 0)
        return matches[0] if matches else ""
    except Exception as exc:
        logger.warning(f"[Windows] FortiClient 창 검색 실패: {exc}")
        return ""


def focus_forticlient_window() -> tuple[bool, str]:
    """Bring an existing FortiClient/FortiVPN window to the foreground before SendInput."""
    if os.name != "nt":
        return False, ""
    try:
        user32 = ctypes.windll.user32
        matches: list[tuple[int, str]] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value or ""
            if _window_title_matches(title):
                matches.append((int(hwnd), title))
            return True

        user32.EnumWindows(enum_proc, 0)
        if not matches:
            return False, "FortiClient/FortiVPN 창을 찾지 못했습니다."

        hwnd, title = matches[0]
        SW_RESTORE = 9
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.25)
        active_title = get_active_window_title()
        if _window_title_matches(active_title):
            return True, active_title
        return False, f"FortiClient 창 전면 전환 실패 (찾은 창: {title}, 현재 창: {active_title or '알 수 없음'})."
    except Exception as exc:
        logger.warning(f"[Windows] FortiClient 창 전면 전환 실패: {exc}")
        return False, str(exc)


def send_keyboard_shortcut_to_active_window(keys: list[int]) -> bool:
    """Send a keyboard shortcut to the active window via SendInput."""
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002

        ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", ctypes.c_ulong),
                ("wParamL", ctypes.c_ushort),
                ("wParamH", ctypes.c_ushort),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]

        def key(vk: int, flags: int = 0) -> INPUT:
            return INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(vk, 0, flags, 0, 0)))

        event_list = [key(vk) for vk in keys] + [key(vk, KEYEVENTF_KEYUP) for vk in reversed(keys)]
        events = (INPUT * len(event_list))(*event_list)
        user32.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int)
        user32.SendInput.restype = ctypes.c_uint
        sent = user32.SendInput(len(events), events, ctypes.sizeof(INPUT))
        if sent != len(events):
            err = ctypes.get_last_error()
            logger.warning(f"[Windows] SendInput shortcut 실패: keys={keys}, sent={sent}/{len(events)}, last_error={err}")
            return False
        return True
    except Exception as exc:
        logger.warning(f"[Windows] 키 입력 전송 실패: {exc}")
        return False


def send_key_to_active_window(vk: int) -> bool:
    return send_keyboard_shortcut_to_active_window([vk])


def send_ctrl_v_to_active_window() -> bool:
    return send_keyboard_shortcut_to_active_window([0x11, 0x56])


def replace_active_field_with_clipboard_and_submit() -> bool:
    """Select the active field contents, clear it, paste current clipboard contents, then press Enter."""
    # Ctrl+A selects stale OTP, Delete clears it, Ctrl+V inserts the new clipboard OTP, Enter submits.
    return (
        send_keyboard_shortcut_to_active_window([0x11, 0x41])
        and send_key_to_active_window(0x2E)
        and send_ctrl_v_to_active_window()
        and send_key_to_active_window(0x0D)
    )


def maybe_auto_paste_otp(config: dict) -> tuple[bool, str]:
    """Safely paste only into a FortiClient/FortiVPN window."""
    if config.get("auto_paste_otp") != "true":
        return False, ""
    title = get_active_window_title()
    if not _window_title_matches(title):
        focused, focus_message = focus_forticlient_window()
        if not focused:
            return False, f"FortiClient 창이 활성 상태가 아니라 자동 붙여넣기는 건너뜀 (현재 창: {title or '알 수 없음'} / {focus_message})."
        title = focus_message
    # Give the user/GUI a tiny moment after clipboard update, then paste and submit.
    time.sleep(0.15)
    if replace_active_field_with_clipboard_and_submit():
        return True, f"FortiClient 창({title})의 기존 입력값을 선택/삭제 후 새 OTP 자동 붙여넣기와 Enter 입력을 시도했습니다."
    return False, "FortiClient 창은 활성 상태였지만 자동 붙여넣기에 실패했습니다. FortiClient가 관리자/보호 권한으로 떠 있으면 Windows가 입력 주입을 차단할 수 있습니다. 수동으로 Ctrl+V 해 주세요."


def build_mail_checker(config: dict) -> MailChecker | None:
    required = ["mail_host", "mail_port", "mail_user", "mail_pass"]
    if not all(config.get(k) for k in required):
        return None
    return MailChecker(
        host=config["mail_host"],
        port=config["mail_port"],
        username=config["mail_user"],
        password=config["mail_pass"],
        mailbox=config.get("mail_folder") or "INBOX",
        otp_sender=config.get("otp_sender") or None,
    )


def watch_otp_once(config: dict, max_wait_seconds: int = 120) -> int:
    checker = build_mail_checker(config)
    if checker is None:
        print("메일 설정이 부족합니다. 먼저 settings를 실행해 주세요.")
        return 2
    if not checker.verify_login():
        print("메일 로그인이 거부되었습니다. 메일 비밀번호/앱 비밀번호를 확인해 주세요.")
        return 3
    print(f"OTP 메일 감시 중... 최대 {max_wait_seconds}초 대기")
    otp = checker.fetch_latest_otp(max_wait_seconds=max_wait_seconds)
    if not otp:
        print("OTP를 찾지 못했습니다.")
        return 4
    copied = copy_to_clipboard(otp)
    if copied:
        print("OTP를 클립보드에 복사했습니다. FortiClient OTP 입력 칸에 붙여넣으세요.")
    else:
        print(f"OTP: {otp}")
    return 0


def watch_otp_to_clipboard(config: dict, max_wait_seconds: int = 120) -> tuple[bool, str]:
    """Tray-friendly OTP watcher: never prints the secret OTP in the success path."""
    checker = build_mail_checker(config)
    if checker is None:
        return False, "메일 설정이 부족합니다. Settings를 먼저 저장해 주세요."
    if not checker.verify_login():
        return False, "메일 로그인이 거부되었습니다. 메일 비밀번호/앱 비밀번호를 확인해 주세요."
    otp = checker.fetch_latest_otp(max_wait_seconds=max_wait_seconds)
    if not otp:
        return False, "OTP를 찾지 못했습니다. FortiClient 연결 시작 후 다시 시도해 주세요."
    if not copy_to_clipboard(otp):
        return False, "OTP는 찾았지만 클립보드 복사에 실패했습니다."
    pasted, paste_message = maybe_auto_paste_otp(config)
    if paste_message:
        logger.info(f"[Windows OTP] 자동 붙여넣기 결과: pasted={pasted}, {paste_message}")
    return True, f"토큰값: {otp}"


def launch_forticlient() -> bool:
    path = find_forticlient()
    if not path:
        print("FortiClient 실행 파일을 찾지 못했습니다. Settings에서 FortiClient Path를 지정해 주세요.")
        return False
    subprocess.Popen([str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"FortiClient 실행: {path}")
    return True


class SettingsServer:
    def __init__(self, port: int = SETTINGS_PORT):
        self.port = port
        self.token = secrets.token_urlsafe(32)
        self.server: HTTPServer | None = None

    def bind(self) -> None:
        token = self.token

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _deny(self, code: int, message: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(message.encode("utf-8"))

            def _host_allowed(self) -> bool:
                host = self.headers.get("Host", "")
                return host in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

            def _token_valid(self, supplied: str) -> bool:
                return bool(supplied) and secrets.compare_digest(supplied, token)

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                    return
                if not self._host_allowed():
                    self._deny(403, "Forbidden")
                    return
                if parsed.path != "/":
                    self._deny(404, "Not Found")
                    return
                supplied = (urllib.parse.parse_qs(parsed.query).get("token") or [""])[0]
                if not self._token_valid(supplied):
                    # Browsers can revisit a stale settings URL from history after the
                    # previous one-shot server was closed. GET has no side effects, so
                    # issue a fresh in-process token URL instead of showing a scary
                    # Forbidden page. POST remains token-strict below.
                    self.send_response(302)
                    self.send_header("Location", f"/?token={token}")
                    self.end_headers()
                    return
                config = WindowsConfig.load()
                esc = lambda v: html.escape(v or "", quote=True)
                forticlient_path = esc(config.get("forticlient_path") or str(find_forticlient() or ""))
                mail_host = esc(config.get("mail_host") or "imap.daum.net")
                mail_port = esc(config.get("mail_port") or "993")
                mail_user = esc(config.get("mail_user") or "")
                mail_folder = esc(config.get("mail_folder") or "INBOX")
                otp_sender = esc(config.get("otp_sender") or MailChecker.DEFAULT_OTP_SENDER)
                form_token = esc(supplied)
                page = f"""<!doctype html><html lang='ko'><head><meta charset='utf-8'>
<title>FortiAutoConn Windows 설정</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#111827;color:#e5e7eb;margin:0;padding:32px}}.card{{max-width:720px;margin:auto;background:#1f2937;border:1px solid #374151;border-radius:16px;padding:28px}}label{{display:block;margin-top:14px;color:#cbd5e1}}input{{width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #4b5563;background:#111827;color:#e5e7eb}}button{{margin-top:24px;width:100%;padding:12px;border:0;border-radius:10px;background:#60a5fa;color:#111827;font-weight:700}}.guide{{margin-top:18px;padding:14px;border-radius:12px;background:#111827;border:1px solid #374151;color:#cbd5e1;line-height:1.55}}code{{color:#93c5fd}}</style>
</head><body><div class='card'><h1>FortiAutoConn Windows 설정</h1>
<p>Windows MVP는 FortiClient를 열고 OTP를 감지해 클립보드에 복사합니다. 비밀번호는 Windows Credential Manager(keyring)에 저장됩니다.</p>
<div class='guide'><strong>IMAP 설정 방법</strong><ul>
<li>Daum 메일: <code>mail.daum.net</code> 로그인 → 좌측 하단 <strong>환경설정</strong> → <strong>IMAP/POP3</strong> → <strong>IMAP/SMTP 사용함</strong> 저장.</li>
<li>Kakao/Daum 2단계 인증 사용자: 일반 비밀번호 대신 카카오 계정 관리 → 보안 → 2단계 인증 → <strong>앱 비밀번호</strong>를 생성해 Mail Password에 입력합니다.</li>
<li>IMAP Host 예: Daum <code>imap.daum.net</code>, Kakao <code>imap.kakao.com</code> / Port: SSL 기본 <code>993</code></li>
<li>Mail Address / ID에는 실제 로그인 메일 주소 또는 ID를 입력합니다.</li>
<li>Mail Folder는 OTP 메일이 도착하는 폴더입니다. 한글 폴더명도 가능하며, 모르겠으면 <code>INBOX</code>로 시작하세요.</li>
<li>Mail Password는 빈 칸으로 저장하면 기존 저장값을 유지합니다.</li>
<li>OTP Sender는 OTP 발신자 메일 주소입니다. 기본값이 맞지 않으면 실제 발신자로 바꿔 주세요.</li>
</ul></div>
<form method='post' action='/save'><input type='hidden' name='token' value='{form_token}'>
<label>FortiClient Path</label><input name='forticlient_path' value='{forticlient_path}' placeholder='C:\\Program Files\\Fortinet\\FortiClient\\FortiVPN.exe'>
<label>IMAP Host</label><input name='mail_host' value='{mail_host}' required>
<label>IMAP Port</label><input name='mail_port' value='{mail_port}' required>
<label>Mail Address / ID</label><input name='mail_user' value='{mail_user}' required>
<label>Mail Folder</label><input name='mail_folder' value='{mail_folder}' required>
<label>Mail Password</label><input type='password' name='mail_pass' placeholder='기존 비밀번호 유지 시 빈 칸'>
<label>OTP Sender</label><input name='otp_sender' value='{otp_sender}' required>
<p style='color:#9ca3af;font-size:13px;line-height:1.5'>FortiClient 창이 열려 있을 때만 OTP 메일 감시가 활성화됩니다. OTP를 찾으면 토큰 칸에 Ctrl+A → Delete → Ctrl+V → Enter를 시도합니다.</p>
<button type='submit'>저장</button></form></div></body></html>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(page.encode("utf-8"))

            def do_POST(self):
                if self.path != "/save" or not self._host_allowed():
                    self._deny(404, "Not Found")
                    return
                try:
                    content_length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    content_length = 0
                if content_length <= 0 or content_length > 1_000_000:
                    self._deny(400, "Bad Request")
                    return
                params = urllib.parse.parse_qs(self.rfile.read(content_length).decode("utf-8"))
                data = {k: v[0].strip() for k, v in params.items()}
                if not self._token_valid(data.get("token", "")):
                    self._deny(403, "Forbidden")
                    return
                updates = {
                    "forticlient_path": data.get("forticlient_path", ""),
                    "mail_host": data.get("mail_host", ""),
                    "mail_port": data.get("mail_port", ""),
                    "mail_user": data.get("mail_user", ""),
                    "mail_folder": data.get("mail_folder", "INBOX"),
                    "otp_sender": data.get("otp_sender", ""),
                }
                if data.get("mail_pass"):
                    updates["mail_pass"] = data["mail_pass"]
                WindowsConfig.save(updates)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<meta charset='utf-8'><h1>저장 완료</h1><p>이 창을 닫아도 됩니다.</p>".encode("utf-8"))
                threading.Thread(target=self.server.shutdown, daemon=True).start()

        self.server = HTTPServer(("127.0.0.1", self.port), Handler)

    def serve(self) -> None:
        if self.server is None:
            self.bind()
        self.server.serve_forever()
        self.server.server_close()


def open_settings() -> int:
    server = SettingsServer()
    try:
        server.bind()
    except OSError as exc:
        print(f"설정 서버 포트({SETTINGS_PORT})를 열 수 없습니다: {exc}")
        return 2
    url = f"http://127.0.0.1:{SETTINGS_PORT}/?token={server.token}"
    print(f"설정 페이지 열기: {url}")
    webbrowser.open(url)
    server.serve()
    return 0


def show_status_window(message: str) -> None:
    """Show a closeable status window instead of a transient notification."""
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("FortiAutoConn 상태")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        frame = ttk.Frame(root, padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text=message, justify="left", wraplength=520).grid(row=0, column=0, sticky="w")
        ttk.Button(frame, text="확인", command=root.destroy).grid(row=1, column=0, pady=(16, 0), sticky="e")
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
    except Exception as exc:
        logger.warning(f"[Windows Status] 상태 창 표시 실패: {exc}")
        print(message)


def connect_flow() -> int:
    config = WindowsConfig.load()
    if not launch_forticlient():
        return 2
    print("FortiClient에서 VPN 연결을 시작하세요. OTP 메일이 오면 자동 감지해 클립보드에 복사합니다.")
    return watch_otp_once(config)


class WindowsTrayApp:
    def __init__(self):
        self.icon = None
        self._worker: threading.Thread | None = None
        self._auto_watch_thread: threading.Thread | None = None
        self._auto_watch_stop = threading.Event()
        self._lock = threading.Lock()
        self._active_action: str | None = None

    def _set_title(self, title: str) -> None:
        if self.icon:
            self.icon.title = title

    def _update_menu(self) -> None:
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception as exc:
                logger.debug(f"[Windows Tray] 메뉴 갱신 실패: {exc}")

    def _is_active(self, action: str):
        return lambda _item: self._active_action == action

    def _auto_paste_enabled(self, _item=None) -> bool:
        return WindowsConfig.load().get("auto_paste_otp") == "true"

    def _auto_watch_enabled(self, _item=None) -> bool:
        return bool(self._auto_watch_thread and self._auto_watch_thread.is_alive())

    def _notify(self, title: str, message: str) -> None:
        """Use non-modal tray notifications; never open a blocking message box."""
        log_message = re.sub(r"(토큰값:\s*)(\d{1})(\d+)", lambda m: m.group(1) + m.group(2) + "*" * len(m.group(3)), message)
        logger.info(f"[Windows Notify] {title}: {log_message}")
        if not self.icon:
            print(f"{title}: {message}")
            return
        try:
            self.icon.notify(message, title)
        except Exception as exc:
            logger.warning(f"[Windows Notify] tray 알림 표시 실패: {exc}")

    def _run_worker(self, target, busy_title: str, action: str) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                self._notify("FortiAutoConn", "이미 작업이 진행 중입니다.")
                return
            self._active_action = action
            self._set_title(busy_title)
            self._worker = threading.Thread(target=target, daemon=True)
            self._worker.start()
            self._update_menu()

    def _clear_active(self) -> None:
        self._active_action = None
        self._set_title("FortiAutoConn")
        self._update_menu()

    def _ensure_auto_watch_running(self) -> None:
        if self._auto_watch_thread and self._auto_watch_thread.is_alive():
            return
        self._auto_watch_stop.clear()
        self._auto_watch_thread = threading.Thread(target=self._auto_watch_loop, daemon=True)
        self._auto_watch_thread.start()

    def _auto_watch_loop(self) -> None:
        self._active_action = "auto_watch"
        self._set_title("FortiAutoConn - 자동 OTP 감시 중")
        self._update_menu()
        self._notify("FortiAutoConn", "자동 OTP 메일 감시를 시작했습니다. FortiClient에서 연결하면 OTP를 자동 처리합니다.")
        dormant_notified = False
        try:
            while not self._auto_watch_stop.is_set():
                forticlient_window = find_forticlient_window_title()
                if not forticlient_window:
                    if not dormant_notified:
                        self._set_title("FortiAutoConn - 휴면 중")
                        logger.info("[Windows Tray] FortiClient 창이 없어 OTP 메일 감시를 휴면합니다.")
                        dormant_notified = True
                    self._auto_watch_stop.wait(5)
                    continue

                if dormant_notified:
                    self._set_title("FortiAutoConn - 자동 OTP 감시 중")
                    logger.info(f"[Windows Tray] FortiClient 창 감지, OTP 메일 감시를 활성화합니다: {forticlient_window}")
                    dormant_notified = False

                ok, message = watch_otp_to_clipboard(WindowsConfig.load(), max_wait_seconds=600)
                if ok:
                    self._notify("FortiAutoConn", message)
                    # Keep watching for the next VPN reconnect. Duplicate OTP messages are
                    # skipped by MailChecker's consumed Message-ID cache.
                    self._auto_watch_stop.wait(0.5)
                elif "OTP를 찾지 못했습니다" not in message:
                    self._notify("FortiAutoConn", message)
                    break
        finally:
            if self._active_action == "auto_watch":
                self._clear_active()

    def connect_and_watch(self, _icon=None, _item=None) -> None:
        def worker():
            try:
                if not launch_forticlient():
                    self._notify("FortiAutoConn", "FortiClient 실행 파일을 찾지 못했습니다. Settings에서 경로를 지정해 주세요.")
                    return
                self._ensure_auto_watch_running()
                self._notify("FortiAutoConn", "FortiClient를 실행했고 자동 OTP 메일 감시를 켰습니다.")
            finally:
                if not self._auto_watch_enabled():
                    self._clear_active()

        self._run_worker(worker, "FortiAutoConn - OTP 감시 중", "connect")

    def watch_otp_only(self, _icon=None, _item=None) -> None:
        def worker():
            try:
                _ok, message = watch_otp_to_clipboard(WindowsConfig.load())
                self._notify("FortiAutoConn", message)
            finally:
                self._clear_active()

        self._run_worker(worker, "FortiAutoConn - OTP 감시 중", "otp")

    def open_settings(self, _icon=None, _item=None) -> None:
        threading.Thread(target=open_settings, daemon=True).start()

    def show_status(self, _icon=None, _item=None) -> None:
        path = find_forticlient()
        config = WindowsConfig.load()
        mail_ok = all(config.get(k) for k in ("mail_host", "mail_port", "mail_user", "mail_pass"))
        msg = (
            f"FortiClient: {path or 'not found'}\n"
            f"Mail configured: {'yes' if mail_ok else 'no'}\n"
            f"Auto watch: {'on' if config.get('auto_watch_otp') == 'true' else 'off'}\n"
            f"Auto paste: {'on' if config.get('auto_paste_otp') == 'true' else 'off'}\n"
            f"Startup: {'on' if is_startup_enabled() else 'off'}\n"
            f"Admin: {'yes' if is_running_as_admin() else 'no'}"
        )
        threading.Thread(target=show_status_window, args=(msg,), daemon=True).start()

    def toggle_auto_paste(self, _icon=None, _item=None) -> None:
        enabled = WindowsConfig.load().get("auto_paste_otp") == "true"
        if not enabled and not is_running_as_admin():
            WindowsConfig.save({"auto_paste_otp": "true"})
            self._update_menu()
            if relaunch_tray_as_admin():
                self._notify("FortiAutoConn", "UAC 승인 후 관리자 권한 tray로 다시 실행합니다. 기존 tray는 종료됩니다.")
                if self.icon:
                    threading.Timer(1.0, self.icon.stop).start()
            else:
                self._notify("FortiAutoConn", "관리자 권한 재실행을 시작하지 못했습니다. 수동으로 run_windows_admin.bat을 실행해 주세요.")
            return
        WindowsConfig.save({"auto_paste_otp": "false" if enabled else "true"})
        self._update_menu()
        self._notify("FortiAutoConn", f"안전 자동 붙여넣기: {'OFF' if enabled else 'ON'}")

    def toggle_startup(self, _icon=None, _item=None) -> None:
        enabled = is_startup_enabled()
        try:
            set_startup_enabled(not enabled)
        except Exception as exc:
            logger.warning(f"[Windows Startup] 시작 시 자동실행 설정 실패: {exc}")
            self._notify("FortiAutoConn", f"시작 시 자동실행 설정 실패: {exc}")
            return
        self._update_menu()
        self._notify("FortiAutoConn", f"Windows 시작 시 자동실행: {'OFF' if enabled else 'ON'}")

    def toggle_auto_watch(self, _icon=None, _item=None) -> None:
        enabled = WindowsConfig.load().get("auto_watch_otp") == "true"
        WindowsConfig.save({"auto_watch_otp": "false" if enabled else "true"})
        if enabled:
            self._auto_watch_stop.set()
            self._notify("FortiAutoConn", "자동 OTP 메일 감시: OFF")
        else:
            self._ensure_auto_watch_running()
            self._notify("FortiAutoConn", "자동 OTP 메일 감시: ON")
        self._update_menu()

    def quit(self, icon, _item=None) -> None:
        self._auto_watch_stop.set()
        icon.stop()

    @staticmethod
    def _create_icon_image():
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((8, 8, 56, 56), fill=(37, 99, 235, 255))
        draw.rectangle((28, 18, 36, 46), fill=(255, 255, 255, 255))
        draw.rectangle((18, 28, 46, 36), fill=(255, 255, 255, 255))
        return image

    def run(self) -> int:
        try:
            import pystray
        except ImportError:
            print("pystray/Pillow가 설치되지 않았습니다. `uv pip install -r requirements.txt` 후 다시 실행해 주세요.")
            return 2

        menu = pystray.Menu(
            pystray.MenuItem("Settings", self.open_settings),
            pystray.MenuItem("Status", self.show_status),
            pystray.MenuItem("Run at Windows startup", self.toggle_startup, checked=lambda _item: is_startup_enabled()),
            pystray.MenuItem("Quit", self.quit),
        )
        self.icon = pystray.Icon("FortiAutoConn", self._create_icon_image(), "FortiAutoConn", menu)
        print("FortiAutoConn tray 시작. Windows 알림 영역 아이콘을 우클릭해 사용하세요.")
        self._ensure_auto_watch_running()
        self.icon.run()
        return 0


def run_tray() -> int:
    # Prevent multiple tray instances from starting duplicate OTP watchers.
    # A short wait allows the intentional admin relaunch path to acquire the lock
    # after the old unelevated tray exits.
    lock = SingleInstanceLock(TRAY_MUTEX_NAME, timeout_seconds=3.0)
    if not lock.acquire():
        print("FortiAutoConn tray가 이미 실행 중입니다.")
        logger.info("[Windows Tray] 이미 실행 중인 tray 인스턴스가 있어 새 인스턴스를 종료합니다.")
        return 0
    try:
        return WindowsTrayApp().run()
    finally:
        lock.release()


def status() -> int:
    path = find_forticlient()
    print(f"Config file: {CONFIG_FILE}")
    print(f"FortiClient: {path or 'not found'}")
    if path:
        print("CLI probe:")
        print(probe_forticlient_cli(path))
    config = WindowsConfig.load()
    print(f"Mail configured: {'yes' if all(config.get(k) for k in ('mail_host', 'mail_port', 'mail_user', 'mail_pass')) else 'no'}")
    print(f"Auto watch: {'on' if config.get('auto_watch_otp') == 'true' else 'off'}")
    print(f"Auto paste: {'on' if config.get('auto_paste_otp') == 'true' else 'off'}")
    print(f"Startup: {'on' if is_startup_enabled() else 'off'}")
    print(f"Admin: {'yes' if is_running_as_admin() else 'no'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FortiAutoConn Windows helper")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("settings", help="open local settings page")
    sub.add_parser("connect", help="open FortiClient and copy the next OTP to clipboard")
    sub.add_parser("otp", help="copy the next OTP to clipboard without opening FortiClient")
    sub.add_parser("status", help="show non-secret local status and FortiClient CLI probe")
    sub.add_parser("tray", help="run Windows system tray app")
    args = parser.parse_args(argv)

    if args.command == "settings":
        return open_settings()
    if args.command == "connect":
        return connect_flow()
    if args.command == "otp":
        return watch_otp_once(WindowsConfig.load())
    if args.command == "status":
        return status()
    if args.command == "tray":
        return run_tray()

    # On Windows, no subcommand should behave like a normal tray application.
    if os.name == "nt":
        return run_tray()

    print("FortiAutoConn Windows helper")
    print("1) settings  2) connect  3) otp  4) status  5) tray  6) quit")
    choice = input("> ").strip()
    return main({"1": ["settings"], "2": ["connect"], "3": ["otp"], "4": ["status"], "5": ["tray"], "6": []}.get(choice, ["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
