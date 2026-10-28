from __future__ import annotations
import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import secrets as _secrets
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
HOME = Path(os.environ.get('NOVI_BROWSER_HOME') or Path.home() / '.novi-browser').expanduser().resolve()
CARD_ENV = 'NOVI_BROWSER_SESSION'


def session_id() -> str:
    """Keep successive CLI calls from one terminal in the same worker tab."""
    explicit = os.environ.get(CARD_ENV) or os.environ.get('NOVI_CARD_ID')  # Legacy alias only.
    if explicit:
        return explicit
    parent = os.getppid()
    try:
        import psutil
        started = psutil.Process(parent).create_time()
    except Exception:
        started = 0
    return f'terminal-{parent}-{started:.0f}'
ACCOUNT_ID = re.compile('^(?:No\\d{1,6}|(?!no\\d+$)[a-z0-9][a-z0-9-]{1,40})$')
IDLE_SECONDS = 5 * 60
HEADED_IDLE_SECONDS = 30 * 60
SHARED_SECONDS = 60 * 60
TAKEOVER_SECONDS = 2 * 60
SAVE_SECONDS = 30
AUTO_LOGIN_GAP = 30 * 60
JUST_SIGNED_IN_SECONDS = 120
EXEC_GRACE_SECONDS = 60
START_WAIT_SECONDS = 90
MIN_FREE_MB = 3072
WORKER_MB = 500
MAX_WORKERS = 4
MDNS_FEATURE = 'WebRtcHideLocalIpsWithMdns'
PLAYWRIGHT_DISABLED = ['AcceptCHFrame', 'AvoidUnnecessaryBeforeUnloadCheckSync', 'DestroyProfileOnBrowserClose', 'DialMediaRouteProvider', 'GlobalMediaControls', 'HttpsUpgrades', 'LensOverlay', 'MediaRouter', 'PaintHolding', 'ThirdPartyStoragePartitioning', 'Translate', 'AutoDeElevate', 'RenderDocument']

def installed_chrome() -> tuple[str, str]:
    # Patchright on installed Chrome can avoid automation checks; no engine guarantees access.
    if sys.platform == 'darwin':
        for root in (Path('/Applications'), Path.home() / 'Applications'):
            binary = root / 'Google Chrome.app/Contents/MacOS/Google Chrome'
            if binary.exists():
                return str(binary), chrome_version(binary)
    if not WINDOWS:
        import shutil
        binary = shutil.which('google-chrome') or shutil.which('google-chrome-stable')
        if binary:
            return binary, chrome_version(Path(binary))
    for root in filter(None, (os.environ.get(name) for name in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'))):
        app = Path(root) / 'Google' / 'Chrome' / 'Application'
        if (app / 'chrome.exe').exists():
            versions = [d.name for d in app.iterdir() if re.fullmatch('\\d+(\\.\\d+){3}', d.name)]
            newest = max(versions, key=lambda v: [int(x) for x in v.split('.')], default='')
            return (str(app / 'chrome.exe'), newest.split('.')[0])
    return ('', '')


def chrome_version(binary: Path) -> str:
    try:
        output = subprocess.run([str(binary), '--version'], capture_output=True, text=True, timeout=10)
        match = re.search(r'\b(\d+)\.', output.stdout)
        return match.group(1) if match else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''

def driver():
    if os.environ.get('NOVI_BROWSER_ENGINE') != 'chromium' and installed_chrome()[0]:
        with contextlib.suppress(ImportError):
            from patchright.sync_api import sync_playwright
            return (sync_playwright, 'chrome')
    from playwright.sync_api import sync_playwright
    return (sync_playwright, 'chromium')

def browser_args(engine: str='chromium') -> list[str]:
    # Disable the mDNS responder to avoid firewall prompts; retain the driver's other disabled features.
    disabled = PLAYWRIGHT_DISABLED
    with contextlib.suppress(Exception):
        package = __import__('patchright' if engine == 'chrome' else 'playwright')
        source = (Path(package.__file__).parent / 'driver' / 'package' / 'lib' / 'server' / 'chromium' / 'chromiumSwitches.js').read_text(encoding='utf-8')
        block = re.search('disabledFeatures\\s*=.*?\\[(.*?)\\]\\.filter', source, re.S)
        found = re.findall('^\\s*"([A-Za-z0-9]+)",?\\s*$', block.group(1), re.M) if block else []
        disabled = found or disabled
    return ['--disable-features=' + ','.join([*disabled, MDNS_FEATURE])]

def launch_options(headed: bool, start_url: str='', engine: str='chromium', chrome_major: str='') -> dict:
    options = {'headless': not headed, 'channel': engine, 'accept_downloads': True, 'args': browser_args(engine)}
    if engine == 'chrome':
        options['chromium_sandbox'] = True
    if not headed:
        options['viewport'] = {'width': 1440, 'height': 900}
        # Nobody looks at a headless page, so it is composited in software: the GPU and utility processes fall from
        # ~290 MB to ~80-140 MB (15-25% of the browser) while WebGL still reports the real GPU; --disable-gpu would
        # report a basic software renderer, a common bot signal. See benchmarks/README.md.
        options['args'] = [*options['args'], '--disable-gpu-compositing']
        if engine == 'chrome' and chrome_major:
            platform = ('Windows NT 10.0; Win64; x64' if WINDOWS else
                        'Macintosh; Intel Mac OS X 10_15_7' if sys.platform == 'darwin' else 'X11; Linux x86_64')
            options['user_agent'] = f'Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36'
    else:
        options['no_viewport'] = True
        options['ignore_default_args'] = ['--enable-automation']
        options['chromium_sandbox'] = True
        if engine == 'chrome':
            options['args'] = [*options['args'], '--test-type']
        if engine == 'chromium':
            options['env'] = {**os.environ, 'GOOGLE_API_KEY': 'no', 'GOOGLE_DEFAULT_CLIENT_ID': 'no', 'GOOGLE_DEFAULT_CLIENT_SECRET': 'no'}
        if re.match('https?://', start_url or ''):
            options['args'] = [*options['args'], f'--app={start_url}']
            options['ignore_default_args'] = ['about:blank', '--enable-automation']
    return options
EXIT_FAILED, EXIT_USAGE, EXIT_UNAVAILABLE, EXIT_LOCKED, EXIT_RESOURCE, EXIT_AUTH, EXIT_NO_ACCOUNT = (1, 2, 69, 73, 75, 77, 78)
WINDOWS = os.name == 'nt'

class BrowserError(Exception):

    def __init__(self, message: str, code: int=EXIT_FAILED):
        super().__init__(message)
        self.code = code

def profile_name(text: str) -> str:
    match = re.match('^no(\\d{1,6})$', text or '', re.IGNORECASE)
    return f'No{int(match.group(1))}' if match else text

def folder(account: str) -> Path:
    if not ACCOUNT_ID.match(account or ''):
        raise BrowserError(f'Invalid profile name; use No1, No2 or a lowercase slug: {account!r}', EXIT_USAGE)
    return HOME / account

def next_profile() -> str:
    numbers = [int(name[2:]) for name in accounts() if name.startswith('No')]
    return f'No{max(numbers, default=0) + 1}'

def logins(config: dict, skip: str='') -> dict[str, str]:
    names = [config.get('identity'), *(entry.get('user') for site, entry in (config.get('sites') or {}).items() if site != skip)]
    return {str(name).strip().lower(): str(name).strip() for name in names if str(name or '').strip()}

def identity(config: dict, skip: str='') -> str:
    return str(config.get('identity') or '').strip() or ', '.join(sorted(logins(config, skip).values()))

def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default

def write_json(path: Path, data) -> None:
    HOME.mkdir(parents=True, exist_ok=True, mode=0o777 if WINDOWS else 0o700)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o777 if WINDOWS else 0o700)
    temp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    with contextlib.suppress(OSError):
        temp.chmod(0o600)
    os.replace(temp, path)
SITE_FIELDS = ('check_url', 'signed_out', 'signed_in_text', 'user', 'secret', 'home', 'login', 'window')

def needs_window(config: dict, site: str | None=None) -> bool:
    with contextlib.suppress(BrowserError):
        return bool(site_config(config, site)[1].get('window'))
    return False

def normalize(config: dict) -> dict:
    if not isinstance(config.get('sites'), dict):
        name = config.get('site') or 'default'
        config['sites'] = {name: {field: config[field] for field in SITE_FIELDS if field in config}} if config.get('check_url') else {}
        config.setdefault('default', name if config['sites'] else '')
    if config.get('default') not in config['sites']:
        config['default'] = next(iter(config['sites']), '')
    return config

def load_account(account: str) -> dict:
    config = read_json(folder(account) / 'account.json')
    if not isinstance(config, dict):
        raise BrowserError(f'Unregistered profile: {account} (use list to find a profile or add to create one)', EXIT_NO_ACCOUNT)
    config['id'] = account
    return normalize(config)

def site_config(config: dict, name: str | None=None) -> tuple[str, dict]:
    sites = config.get('sites') or {}
    if not name:
        name = config.get('default') or ''
    if name in sites:
        return (name, sites[name])
    key = name.lower()
    found = [site for site, entry in sites.items() if key and (key in site.lower() or key in str(entry.get('check_url', '')).lower())]
    if len(found) == 1:
        return (found[0], sites[found[0]])
    raise BrowserError(f"{config.get('id')} has site '{name}' that is {('ambiguous' if found else 'missing')} (registered: {', '.join(sites) or 'none'}). Use add to register the site in this profile.", EXIT_NO_ACCOUNT)

def accounts() -> list[str]:
    if not HOME.is_dir():
        return []
    return sorted((path.parent.name for path in HOME.glob('*/account.json') if ACCOUNT_ID.match(path.parent.name)))

def add_account(account: str, *, site: str, check: str, signed_out: list[str], signed_in_text: str='', user: str='', secret: str='', home: str='', note: str='', login: dict | None=None, label: str='', window: bool=False, who: str='') -> dict:
    """A cookie jar belongs to one identity; several sites may share that identity."""
    if not site:
        raise BrowserError('--site requires a site name', EXIT_USAGE)
    if not re.match('^https?://', check or ''):
        raise BrowserError('--check must be an HTTP(S) URL used to verify login', EXIT_USAGE)
    if not signed_out and (not signed_in_text):
        raise BrowserError('Provide --signed-out URL markers or --signed-in-text to detect login state', EXIT_USAGE)
    login = {key: value for key, value in (login or {}).items() if value}
    if login and (not (login.get('url') and login.get('password_field'))):
        raise BrowserError('Saved login requires both --login-url and --password-field', EXIT_USAGE)
    path = folder(account)
    old = read_json(path / 'account.json')
    config = normalize(old) if isinstance(old, dict) else {'sites': {}, 'default': '', 'added_at': time.strftime('%Y-%m-%d %H:%M:%S')}
    for legacy in ('site', *SITE_FIELDS):
        config.pop(legacy, None)
    held = logins({**config, 'identity': who or config.get('identity')}, skip=site)
    names = {**held, **{name.strip().lower(): name.strip() for name in (user, who) if name.strip()}}
    if len(names) > 1:
        raise BrowserError(f"{account} belongs to {identity(config, skip=site) or ', '.join(held.values())}. One identity per profile: register {user or who} in a new profile such as {next_profile()}.", EXIT_USAGE)
    signed_out = [re.sub('^[A-Za-z]:/Program Files/Git(?=/)', '', part) for part in signed_out]
    entry = {'check_url': check, 'signed_out': [part for part in signed_out if part], 'signed_in_text': signed_in_text, 'user': user, 'secret': secret, 'home': home or check, 'login': login, 'window': window}
    config['sites'][site] = {key: value for key, value in entry.items() if value not in ('', [], {}, False)}
    config['default'] = config.get('default') or site
    for key, value in (('note', note), ('label', label), ('identity', who)):
        if value:
            config[key] = value
    config.pop('id', None)
    write_json(path / 'account.json', config)
    (path / 'profile').mkdir(parents=True, exist_ok=True)
    return config

def auth_state(account: str) -> dict:
    state = read_json(folder(account) / 'state.json', {}) or {}
    if 'auth' in state and 'sites' not in state:
        with contextlib.suppress(BrowserError, OSError):
            return {load_account(account)['default']: state}
    return state.get('sites') or {}

def set_auth_state(account: str, site: str, ok: bool, url: str) -> dict:
    entry = {'auth': 'READY' if ok else 'AUTH_EXPIRED', 'checked_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'url': url[:300]}
    sites = auth_state(account)
    tried = (sites.get(site) or {}).get('auto_login')
    if tried and (not (ok and tried.get('ok') is not True)):
        entry['auto_login'] = tried
    sites[site] = entry
    write_json(folder(account) / 'state.json', {'sites': sites})
    return entry

def auto_login_record(account: str, site: str) -> dict:
    return (auth_state(account).get(site) or {}).get('auto_login') or {}

def set_auto_login(account: str, site: str, record: dict) -> None:
    sites = auth_state(account)
    sites.setdefault(site, {})['auto_login'] = dict(record)
    write_json(folder(account) / 'state.json', {'sites': sites})

def pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except ImportError:
        pass
    except Exception:
        return False
    if WINDOWS:
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(4096, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True

def lock_path(account: str) -> Path:
    return folder(account) / 'lock.json'

def read_lock(account: str) -> dict | None:
    path = lock_path(account)
    lock = read_json(path)
    if lock is None:
        if path.exists():
            try:
                if time.time() - path.stat().st_mtime > 60:
                    path.unlink()
            except OSError:
                pass
        return None
    if pid_alive(lock.get('pid')):
        return lock
    if (read_json(path) or {}).get('pid') == lock.get('pid'):
        with contextlib.suppress(OSError):
            path.unlink()
    return None

def take_lock(account: str, info: dict) -> bool:
    path = lock_path(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if read_lock(account) is not None:
                return False
            continue
        with os.fdopen(handle, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps(info, ensure_ascii=False))
        return True
    return False

def update_lock(account: str, **fields) -> None:
    lock = read_json(lock_path(account)) or {}
    if lock.get('pid') != os.getpid():
        return
    lock.update(fields)
    write_json(lock_path(account), lock)

def release_lock(account: str) -> None:
    lock = read_json(lock_path(account)) or {}
    if lock.get('pid') in (os.getpid(), None):
        with contextlib.suppress(OSError):
            lock_path(account).unlink()

def ledger(account: str) -> dict[str, dict]:
    latest = {}
    try:
        lines = (folder(account) / 'ledger.jsonl').read_text(encoding='utf-8').splitlines()
    except OSError:
        return latest
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get('key'):
            latest[entry['key']] = entry
    return latest

def note_ledger(account: str, key: str, state: str, **fields) -> dict:
    entry = {'key': key, 'state': state, 'at': time.strftime('%Y-%m-%d %H:%M:%S'), **{k: v for k, v in fields.items() if v}}
    path = folder(account) / 'ledger.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return entry

def begin_post(account: str, key: str, what: str='', card: str='', verified: bool=False) -> dict:
    if not key:
        raise BrowserError('intent(key) requires a unique key per action (use fingerprint(identity, content, date))')
    if not verified:
        raise BrowserError(f'{account}: action blocked: login has not been verified in this browser (run check())', EXIT_AUTH)
    before = ledger(account).get(key)
    if before and before['state'] == 'intent':
        raise BrowserError(f"UNKNOWN_OUTCOME: '{before.get('what') or key}' at {before['at']} started but was never confirmed. Inspect the site before retrying, then use `novi-browser resolve {account} --key {key} --state done|failed` after checking the outcome. Never retry through another tool.")
    if before and before['state'] == 'done':
        raise BrowserError(f"Already completed: '{before.get('what') or key}' ({before['at']}{(' · ' + before['url'] if before.get('url') else '')}). Do not repeat this action.")
    return note_ledger(account, key, 'intent', what=what, card=card)

def end_post(account: str, key: str, state: str, url: str='', why: str='') -> dict:
    if state not in ('done', 'failed'):
        raise BrowserError('--state must be done or failed', EXIT_USAGE)
    if key not in ledger(account):
        raise BrowserError(f'{account}: unknown action key: {key}')
    return note_ledger(account, key, state, url=url, why=why)

def fingerprint(*parts) -> str:
    text = '\n'.join((re.sub('\\s+', ' ', str(part)).strip().lower() for part in parts))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]

def running() -> dict[str, dict]:
    return {account: lock for account in accounts() if (lock := read_lock(account))}

def free_mb() -> int | None:
    try:
        import psutil
        return int(psutil.virtual_memory().available / 2 ** 20)
    except Exception:
        return None

def room_for_one(workers: int, available: int | None) -> tuple[bool, str]:
    if workers >= MAX_WORKERS:
        return (False, f'Already running browsers: {workers} (maximum {MAX_WORKERS})')
    if available is not None and available - WORKER_MB < MIN_FREE_MB:
        return (False, f'Available memory: {available / 1024:.1f}GB available; starting another browser requires {MIN_FREE_MB / 1024:.0f}GB free memory threshold would be crossed')
    return (True, '')

def profile_processes(account: str) -> list:
    try:
        import psutil
    except ImportError:
        return []
    key = str(folder(account) / 'profile').lower()
    found = {}
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            name = (proc.info['name'] or '').lower()
            if ('chrom' in name or 'headless' in name) and key in ' '.join(proc.info['cmdline'] or []).lower():
                found[proc.pid] = proc
                found.update(((child.pid, child) for child in proc.children(recursive=True)))
        except Exception:
            continue
    return list(found.values())

def browser_window(account: str) -> int:
    if not WINDOWS:
        return 0
    import ctypes
    from ctypes import wintypes
    pids = {proc.pid for proc in profile_processes(account)}
    user = ctypes.windll.user32
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user.IsWindowVisible(hwnd) and user.GetWindowTextLengthW(hwnd) and (not user.GetWindow(hwnd, 4)):
            found.append(int(hwnd))
            return False
        return True
    user.EnumWindows(each, 0)
    return found[0] if found else 0

def share_window(account: str, card: str, note: str, project: str='', notify: bool=True) -> str:
    import shlex
    command = os.environ.get('NOVI_BROWSER_SHARE_CMD')
    if not command:
        return 'Browser window is available locally.'
    hwnd = browser_window(account)
    title = account
    if WINDOWS and hwnd:
        import ctypes
        buffer = ctypes.create_unicode_buffer(1024)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, 1024)
        title = buffer.value
    fields = dict(hwnd=str(hwnd), title=title, account=account, session=card, note=note)
    argv = shlex.split(command, posix=not WINDOWS)
    if WINDOWS:
        argv = [arg[1:-1] if arg.startswith('"') and arg.endswith('"') else arg for arg in argv]
    done = subprocess.run([arg.format_map(fields) for arg in argv], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    if done.returncode:
        raise BrowserError('Window share hook failed: ' + done.stderr[-200:])
    write_json(folder(account) / 'remote.json', dict(card=card, hwnd=hwnd, at=time.time()))
    return 'Window share hook completed. ' + done.stdout.strip()

def shared_until(account: str) -> float:
    shown = read_json(folder(account) / 'remote.json') or {}
    return float(shown.get('at') or 0) + SHARED_SECONDS if shown else 0

def unshare_window(account: str, card: str) -> bool:
    path = folder(account) / 'remote.json'
    shown = read_json(path) or {}
    if not shown or (card and shown.get('card') != card):
        return False
    path.unlink(missing_ok=True)
    return True

def private_mb(procs) -> float:
    total = 0
    for proc in procs:
        try:
            info = proc.memory_full_info()
            total += getattr(info, 'private', 0) or getattr(info, 'uss', 0)
        except Exception:
            continue
    return round(total / 2 ** 20, 1)

def end_processes(account: str) -> int:
    left = profile_processes(account)
    for proc in left:
        with contextlib.suppress(Exception):
            proc.kill()
    return len(left)

def record_run(row: dict) -> None:
    row.setdefault('at', time.strftime('%Y-%m-%d %H:%M:%S'))
    HOME.mkdir(parents=True, exist_ok=True)
    with (HOME / 'runs.jsonl').open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + '\n')

def secret_value(name: str) -> str:
    """Resolve secrets locally without logging their values."""
    variable = 'NOVI_BROWSER_SECRET_' + re.sub('[^A-Z0-9]', '_', name.upper())
    if variable in os.environ:
        return os.environ[variable]
    try:
        import keyring
        value = keyring.get_password('novi-browser', name)
        if value is not None:
            return value
    except Exception:
        pass
    path = HOME / 'secrets.json'
    if path.exists():
        with contextlib.suppress(OSError):
            path.chmod(384)
    values = read_json(path, {})
    if isinstance(values, dict) and isinstance(values.get(name), str):
        return values[name]
    raise BrowserError(f'Secret not found: {name}')

def last_expression(code: str):
    tree = ast.parse(code, '<exec>', 'exec')
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        tail = ast.Expression(tree.body.pop().value)
        return (compile(tree, '<exec>', 'exec'), compile(tail, '<exec>', 'eval'))
    return (compile(tree, '<exec>', 'exec'), None)

def signed_in(url: str, body: str, config: dict) -> bool:
    if any((part and part in url for part in config.get('signed_out') or [])):
        return False
    text = config.get('signed_in_text')
    return not text or text in body

def human_click(page, locator, pause=time.sleep) -> None:
    import random
    locator.scroll_into_view_if_needed(timeout=10000)
    box = locator.bounding_box(timeout=10000)
    if not box:
        locator.click()
        return
    x = box['x'] + box['width'] * random.uniform(0.3, 0.7)
    y = box['y'] + box['height'] * random.uniform(0.35, 0.65)
    page.mouse.move(x, y, steps=random.randint(18, 35))
    pause(random.uniform(0.15, 0.4))
    page.mouse.click(x, y)

def human_type(page, text: str, pause=time.sleep) -> None:
    import random
    for char in text:
        page.keyboard.type(char)
        pause(random.uniform(0.07, 0.22))
REF = re.compile('^f?\\d*e\\d+$')
INTERACTIVE_ROLES = {'button', 'link', 'textbox', 'searchbox', 'combobox', 'listbox', 'option', 'checkbox', 'radio', 'switch', 'slider', 'spinbutton', 'menuitem', 'menuitemcheckbox', 'menuitemradio', 'tab', 'treeitem', 'gridcell', 'columnheader', 'dialog', 'alertdialog', 'alert', 'heading', 'iframe'}
SNAP_LIMIT = 40000

def snap_role(line: str) -> str:
    match = re.match('\\s*- ([a-z]+)\\b', line)
    return match.group(1) if match else ''

def interactive_lines(tree: str) -> str:
    lines = tree.splitlines()
    keep = []
    for i, line in enumerate(lines):
        if not (snap_role(line) in INTERACTIVE_ROLES or ('[cursor=pointer]' in line and '[ref=' in line)):
            continue
        if not re.match('\\s*- \'?[a-z]+ "[^"]', line) and line.rstrip().endswith(':'):
            depth = len(line) - len(line.lstrip())
            words = []
            for child in lines[i + 1:]:
                if len(child) - len(child.lstrip()) <= depth:
                    break
                body = child.strip()
                if body.startswith('- /'):
                    continue
                found = re.match('- [a-z]+ "([^"]*)"', body) or re.search('\\]: (.+)$', body) or re.match('- [a-z]+: (.+)$', body)
                if found and found.group(1).strip():
                    words.append(found.group(1).strip())
            if words:
                line = line.rstrip()[:-1] + ': ' + ' '.join(words)[:80]
        keep.append(line)
    return '\n'.join(keep)

def subtree(tree: str, ref: str) -> str:
    lines = tree.splitlines()
    for i, line in enumerate(lines):
        if f'[ref={ref}]' in line:
            depth = len(line) - len(line.lstrip())
            end = i + 1
            while end < len(lines) and len(lines[end]) - len(lines[end].lstrip()) > depth:
                end += 1
            return '\n'.join((line[depth:] for line in lines[i:end]))
    return ''

def snapshot_diff(before: str, after: str, limit: int=8000) -> str:
    if not before:
        return after[:limit]
    import difflib
    out = [line[0] + ' ' + line[1:].strip() for line in difflib.unified_diff(before.splitlines(), after.splitlines(), n=0, lineterm='') if line[:1] in '+-' and (not line.startswith(('+++', '---'))) and line[1:].strip()]
    text = '\n'.join(out) if out else '(no changes)'
    return text if len(text) <= limit else text[:limit] + f'\n… (Changed lines: {len(out)} total; use snap() to read the full snapshot)'

def ai_snapshot(page, selector: str | None=None, timeout: float=10000) -> tuple[str, str]:
    """Read the whole tree last so every returned ref stays available for subsequent actions."""
    root = head = ''
    new = hasattr(page, 'aria_snapshot')
    if selector:
        found = page.locator(selector)
        index = found.evaluate_all('els => { for (let i = els.length - 1; i >= 0; i--) { const e = els[i];\n            const shown = e.checkVisibility ? e.checkVisibility() : e.getClientRects().length > 0;\n            if (shown && !e.closest(\'[aria-hidden="true"]\')) return i; } return -1; }')
        if index < 0:
            return ('', '')
        element = found.nth(index)
        scoped = element.aria_snapshot(mode='ai', timeout=timeout) if new else element.aria_snapshot(timeout=timeout)
        first = scoped.splitlines()[0] if scoped else ''
        found = re.search('\\[ref=([^\\]]+)\\]', first)
        root, head = (found.group(1), '') if found else ('', first.rstrip(':').strip())
    if new:
        tree = page.aria_snapshot(mode='ai', timeout=timeout)
    else:
        tree = page._sync(page._impl_obj._channel.send('snapshotForAI', None, {'timeout': timeout}))
    if head:
        for line in tree.splitlines():
            found = re.search('\\[ref=([^\\]]+)\\]', line)
            if found and line.strip().startswith(head):
                root = found.group(1)
                break
    return (tree, root)
QUICK_WAIT = 0.3
HIDDEN_GRACE = 1.5
BLOCKED_GRACE = 3.0

def calm(page, seconds, sleep=time.sleep, clock=time.monotonic, read=None) -> float:
    """Shorten fixed waits once two snapshots agree, without exceeding the requested wait."""
    seconds = max(float(seconds or 0), 0.0)
    start = clock()
    if seconds <= QUICK_WAIT:
        sleep(seconds)
        return clock() - start
    read = read or (lambda: ai_snapshot(page, timeout=5000)[0])
    end = start + seconds
    sleep(QUICK_WAIT)
    last = None
    while clock() < end:
        try:
            tree = read()
        except Exception:
            tree = None
        if tree is not None and tree == last:
            break
        last = tree
        sleep(max(min(0.4, end - clock()), 0))
    return clock() - start

class Snap(str):
    tree = diff = ''

def locate(page, target):
    if not isinstance(target, str):
        return target
    return page.locator(f'aria-ref={target}' if REF.match(target) else target)

class Worker:
    """One persistent context per identity; serialized commands, tabs and namespaces per session."""

    def __init__(self, account: str, card: str, headed: bool, site: str=''):
        self.account, self.card, self.headed, self.site = (account, card, headed, site or None)
        self.active_site = self.site
        self.config = load_account(account)
        self.dir = folder(account)
        self.verified: set[str] = set()
        self.used = time.time()
        self.saved = 0.0
        self.closing = ''
        self.execs = self.errors = 0
        self.peak_mb = 0.0
        self.engine = ''
        self.spaces: dict[str, dict] = {}
        self.snaps: dict[str, str] = {}
        self.owned: dict[str, list] = {}
        self.cards: dict[str, float] = {card or '-': time.time()}
        self.current = card or '-'
        self.busy_until = 0.0
        self.quick = False
        self.cut = 0.0

    @contextlib.contextmanager
    def own_pace(self):
        quick, self.quick = (self.quick, False)
        try:
            yield
        finally:
            self.quick = quick

    def paced(self, method):

        def call(*args, **kwargs):
            with self.own_pace():
                return method(*args, **kwargs)
        return call

    def card_wait(self, page, seconds, asleep=time.sleep) -> None:
        if not self.quick:
            asleep(seconds)
            return
        asked = max(float(seconds or 0), 0.0)
        self.cut += max(asked - calm(page, asked), 0.0)

    @contextlib.contextmanager
    def card_pace(self, space: dict):
        import builtins
        import types
        page_type = type(self.page)
        original = page_type.wait_for_timeout
        worker = self

        def wait_for_timeout(page, timeout):
            if not worker.quick:
                return original(page, timeout)
            worker.card_wait(page, float(timeout or 0) / 1000)
            return None
        card_time = types.ModuleType('time')
        card_time.__dict__.update(time.__dict__)
        card_time.sleep = lambda seconds: worker.card_wait(worker.page, seconds)

        def card_import(name, globals=None, locals=None, fromlist=(), level=0):
            module = builtins.__import__(name, globals, locals, fromlist, level)
            return card_time if name == 'time' and level == 0 else module
        space['__builtins__'] = dict(builtins.__dict__, __import__=card_import)
        if isinstance(space.get('time'), types.ModuleType) and space['time'] is time:
            space['time'] = card_time
        load_state = page_type.wait_for_load_state

        def wait_for_load_state(page, state=None, **kwargs):
            if not worker.quick or state != 'networkidle':
                return load_state(page, state, **kwargs)
            worker.card_wait(page, min(float(kwargs.get('timeout') or 10000), 10000) / 1000)
            return None
        page_type.wait_for_timeout, page_type.wait_for_load_state = (wait_for_timeout, wait_for_load_state)
        self.quick, self.cut = (True, 0.0)
        try:
            yield
        finally:
            self.quick = False
            page_type.wait_for_timeout, page_type.wait_for_load_state = (original, load_state)

    def save_session(self):
        # Chromium drops session-only cookies at shutdown; explicit persistence preserves those logins.
        try:
            cookies = self.ctx.cookies()
        except Exception:
            return
        write_json(self.dir / 'session.json', cookies)
        self.saved = time.time()

    def restore_session(self):
        saved = read_json(self.dir / 'session.json', []) or []
        now = time.time()
        keep = [c for c in saved if isinstance(c, dict) and (c.get('expires') in (-1, None) or c['expires'] > now)]
        if keep:
            with contextlib.suppress(Exception):
                self.ctx.add_cookies(keep)

    def space(self, card: str | None=None) -> dict:
        return self.spaces.setdefault(card or self.current, {})

    def page_for(self, card: str | None=None):
        card = card or self.current
        space = self.space(card)
        page = space.get('page')
        if page is None or page.is_closed():
            held = {id(p) for other, pages in self.owned.items() if other != card for p in pages}
            free = [p for p in self.ctx.pages if not p.is_closed() and id(p) not in held]
            page = free[-1] if free else self.ctx.new_page()
            space['page'] = page
            if not any((page is p for p in self.owned.setdefault(card, []))):
                self.owned[card].append(page)
        return page

    @property
    def page(self):
        return self.page_for()

    def check(self, site: str | None=None) -> bool:
        name, config = site_config(self.config, site)
        page = self.page
        page.goto(config['check_url'], wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(2000)
        body = ''
        if config.get('signed_in_text'):
            with contextlib.suppress(Exception):
                body = page.locator('body').inner_text(timeout=5000)
        ok = signed_in(page.url, body, config)
        if self.headed:
            with contextlib.suppress(Exception):
                page.bring_to_front()
        (self.verified.add if ok else self.verified.discard)(name)
        set_auth_state(self.account, name, ok, page.url)
        return ok

    def login(self, site: str | None=None) -> bool:
        name, config = site_config(self.config, site)
        how = config.get('login') or {}
        if not how:
            raise BrowserError(f'{name}: no saved login method. Use exec or open --headed to sign in.')
        page = self.page
        page.goto(how['url'], wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(2500)
        if how.get('user_field') and config.get('user'):
            field = page.locator(how['user_field']).first
            human_click(page, field)
            field.fill('')
            human_type(page, config['user'])
            page.wait_for_timeout(800)
        field = page.locator(how['password_field']).first
        human_click(page, field)
        human_type(page, secret_value(config['secret']))
        page.wait_for_timeout(1000)
        if how.get('submit'):
            human_click(page, page.locator(f"{how['submit']} >> visible=true").first)
        else:
            field.press('Enter')
        page.wait_for_timeout(5000)
        self.login_page = {}
        if signed_in(page.url, '', {'signed_out': config.get('signed_out')}):
            return self.check(name)
        shot = folder(self.account) / 'login-failed.png'
        with contextlib.suppress(Exception):
            page.screenshot(path=str(shot))
        body = ''
        with contextlib.suppress(Exception):
            body = page.locator('body').inner_text(timeout=5000)
        self.login_page = {'url': page.url, 'text': re.sub('\\s+', ' ', body).strip()[:600], 'shot': str(shot) if shot.exists() else ''}
        self.verified.discard(name)
        set_auth_state(self.account, name, False, page.url)
        return False

    def signed_in_or_login(self, site: str | None=None) -> bool:
        self.login_page = {}
        name, config = site_config(self.config, site)
        last = auto_login_record(self.account, name)
        if last and last.get('ok') is not True and (time.time() - float(last.get('at') or 0) < JUST_SIGNED_IN_SECONDS):
            self.login_page = last.get('page') or {'url': '', 'text': 'The last login outcome is unknown', 'shot': ''}
            return False
        if self.check(site):
            return True
        if not config.get('login') or not config.get('secret'):
            return False
        if last and (last.get('ok') is not True or time.time() - float(last.get('at') or 0) < AUTO_LOGIN_GAP):
            return False
        at = time.time()
        record = {'at': at, 'when': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(at)), 'ok': None}
        set_auto_login(self.account, name, record)
        try:
            ok = self.login(name)
        except Exception as exc:
            ok, self.login_page = (False, {'url': '', 'text': f'{type(exc).__name__}: {exc}'[:300], 'shot': ''})
        record.update(ok=ok, at=time.time(), when=time.strftime('%Y-%m-%d %H:%M:%S'))
        if not ok:
            record['page'] = self.login_page or {}
        set_auto_login(self.account, name, record)
        return ok

    def login_once(self, site: str | None=None) -> bool:
        name = site_config(self.config, site)[0]
        last = auto_login_record(self.account, name)
        if last and time.time() - float(last.get('at') or 0) < JUST_SIGNED_IN_SECONDS:
            if last.get('ok'):
                return self.check(name)
            self.login_page = last.get('page') or {'url': '', 'text': 'The last login outcome is unknown', 'shot': ''}
            return False
        return self.login(name)

    def helpers(self, cwd: str) -> dict:

        def here(name):
            path = Path(name)
            return path if path.is_absolute() else Path(cwd or '.') / path

        def goto(url):
            self.page.goto(url, wait_until='domcontentloaded', timeout=45000)
            return self.page.url

        def shot(name='browser.png', full_page=False):
            path = here(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(path), full_page=full_page)
            return str(path)

        def text(selector='body', limit=3000):
            return self.page.locator(selector).first.inner_text(timeout=10000)[:limit]

        def read(selector=None):
            tree, root = ai_snapshot(self.page, selector)
            before = self.snaps.get(self.current, '')
            self.snaps[self.current] = tree
            return (tree, root, before)

        def snap(selector=None, interactive=False, ref=None, limit=SNAP_LIMIT):
            if isinstance(selector, int):
                selector, limit = (None, selector)
            tree, root, before = read(selector)
            if selector and (not (ref or root)):
                return Snap(f'({selector}: no visible match. Use snap() to read the whole page)')
            part = subtree(tree, ref or root) if ref or root else tree
            if interactive:
                part = interactive_lines(part)
            if len(part) > limit:
                part = part[:limit] + f"""\n… ({len(part)} characters total; showing {limit} characters. Narrow with interactive=True or selector='[role="dialog"]')"""
            out = Snap(part)
            out.tree, out.diff = (part, snapshot_diff(before, tree))
            return out

        def settle(wait=0.3):
            time.sleep(wait)
            before = self.snaps.get(self.current, '')
            tree = ai_snapshot(self.page)[0]
            for _ in range(4):
                time.sleep(0.4)
                again = ai_snapshot(self.page)[0]
                if again == tree:
                    break
                tree = again
            self.snaps[self.current] = tree
            return snapshot_diff(before, tree)

        def diff():
            return settle(0)

        def find(target, force=False):
            found = locate(self.page, target)
            if not isinstance(target, str):
                return found
            count = found.count()
            if REF.match(target) and (not count):
                raise BrowserError(f'Ref {target} is stale. Read the changed lines and use a current ref.\n{settle(0)}')
            if count and (not force):
                deadline = time.monotonic() + HIDDEN_GRACE
                while not any((found.nth(i).is_visible() for i in range(min(count, 5)))):
                    if time.monotonic() > deadline:
                        raise BrowserError(f'{target} is hidden. Use a visible element from snap(interactive=True).\n{settle(0)}')
                    self.page.wait_for_timeout(100)
            return found

        def click(target, **kwargs):
            found = find(target, kwargs.get('force', False))
            if not kwargs.get('force') and (not kwargs.get('trial')) and ('timeout' not in kwargs):
                try:
                    found.click(trial=True, timeout=BLOCKED_GRACE * 1000)
                except Exception as exc:
                    if 'Timeout' not in type(exc).__name__:
                        raise
                    log = str(exc)
                    why = 'covered by another element' if 'intercepts pointer events' in log else 'disabled' if 'not enabled' in log else 'moving' if 'not stable' in log else f'{BLOCKED_GRACE:.0f} seconds without becoming actionable'
                    raise BrowserError(f"{target} is {why}; click refused. Read snap(interactive=True), or close an overlay with press('Escape').\n{settle(0)}")
            found.click(**kwargs)
            return settle()

        def fill(target, value, **kwargs):
            find(target, kwargs.get('force', False)).fill(value, **kwargs)
            return settle()

        def press(key, target=None):
            find(target).press(key) if target else self.page.keyboard.press(key)
            return settle()

        def select(target, value):
            find(target).select_option(value)
            return settle()

        def pages():
            return [(i, p.url, p.title()) for i, p in enumerate(self.ctx.pages)]

        def use(index):
            page = self.ctx.pages[index]
            self.space()['page'] = page
            if not any((page is p for p in self.owned.setdefault(self.current, []))):
                self.owned[self.current].append(page)
            page.bring_to_front()
            return page.url

        def intent(key, what='', site=None):
            # Always gate on the target site, even if another site in this profile is signed in.
            verified = site_config(self.config, site or self.active_site or None)[0] in self.verified
            begin_post(self.account, key, what, self.current, verified)
        return {'ctx': self.ctx, 'goto': goto, 'shot': shot, 'text': text, 'snap': snap, 'pages': pages, 'use': use, 'diff': diff, 'click': click, 'fill': fill, 'press': press, 'select': select, 'ref': lambda target: locate(self.page, target), 'check': self.paced(self.check), 'login': self.paced(self.login), 'sites': lambda: list(self.config['sites']), 'secret': secret_value, 'fingerprint': fingerprint, 'intent': intent, 'human_click': lambda locator: human_click(self.page, locator), 'human_type': lambda value: human_type(self.page, value), 'done': lambda key, url='': end_post(self.account, key, 'done', url=url) and None, 'failed': lambda key, why='': end_post(self.account, key, 'failed', why=why) and None}

    def touch(self, card: str) -> None:
        self.current = card or '-'
        self.used = self.cards[self.current] = time.time()
        with contextlib.suppress(BrowserError, OSError, ValueError):
            self.config = load_account(self.account)

    def release(self, card: str) -> None:
        card = card or '-'
        self.spaces.pop(card, None)
        self.snaps.pop(card, None)
        self.cards.pop(card, None)
        pages = [p for p in self.owned.pop(card, []) if not p.is_closed()]
        if not self.cards:
            self.closing = 'card over'
            return
        for page in pages:
            with contextlib.suppress(Exception):
                if len([p for p in self.ctx.pages if not p.is_closed()]) > 1:
                    page.close()
                else:
                    page.goto('about:blank')
        update_lock(self.account, cards=self.cards)

    def run_code(self, code: str, cwd: str, timeout: float=120, card: str='', site: str='') -> dict:
        self.touch(card)
        self.active_site = site_config(self.config, site or None)[0]
        self.busy_until = self.used + max(float(timeout or 0), 30) + EXEC_GRACE_SECONDS
        update_lock(self.account, used=self.used, busy=True, card_now=self.current, cards=self.cards)
        self.execs += 1
        space = self.space()
        space.update(self.helpers(cwd))
        _ = self.page
        before = {id(p) for p in self.ctx.pages}
        out = io.StringIO()
        result = {'ok': True}
        try:
            if site and site_config(self.config, site)[0] not in self.verified:
                result['signed_in'] = self.signed_in_or_login(site)
            body, tail = last_expression(code)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out), self.card_pace(space):
                exec(body, space)
                if tail is not None:
                    value = eval(tail, space)
                    if value is not None:
                        print(value if isinstance(value, str) else repr(value))
            if self.cut >= 1:
                out.write(f'\n(Skipped fixed wait: {self.cut:.0f} seconds because the page settled. Action helpers already wait; inspect snap() for further changes.)\n')
        except BrowserError as exc:
            result.update(ok=False, error=str(exc), code=exc.code)
        except Exception:
            result.update(ok=False, error=traceback.format_exc(limit=6))
        if not result['ok']:
            self.errors += 1
        result['out'] = out.getvalue()[-20000:]
        mine = self.owned.setdefault(self.current, [])
        mine.extend((p for p in self.ctx.pages if id(p) not in before and (not any((p is q for q in mine)))))
        with contextlib.suppress(Exception):
            result['url'] = self.page.url
            result['title'] = self.page.title()
        self.peak_mb = max(self.peak_mb, private_mb(profile_processes(self.account)))
        self.used = time.time()
        self.busy_until = 0.0
        update_lock(self.account, used=self.used, busy=False)
        return result

    def watchdog(self, started: float):
        while True:
            time.sleep(5)
            if self.busy_until and time.time() > self.busy_until:
                with contextlib.suppress(Exception):
                    self.peak_mb = max(self.peak_mb, private_mb(profile_processes(self.account)))
                leftover = end_processes(self.account)
                release_lock(self.account)
                with contextlib.suppress(Exception):
                    record_run({'account': self.account, 'card': self.card, 'headed': self.headed, 'seconds': round(time.time() - started, 1), 'execs': self.execs, 'errors': self.errors + 1, 'signed_in': sorted(self.verified), 'peak_mb': self.peak_mb, 'leftover': leftover, 'closed': 'exec timeout'})
                os._exit(3)

    def serve(self, nonce: str):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        started = time.time()
        result_file = self.dir / f'start-{nonce}.json'
        info = {'pid': os.getpid(), 'card': self.card, 'cards': self.cards, 'headed': self.headed, 'started': started, 'used': started}
        if not take_lock(self.account, info):
            write_json(result_file, {'ok': False, 'code': EXIT_LOCKED, 'error': 'Another session is starting this profile'})
            return
        try:
            sync_playwright, engine = driver()
            self.engine = engine
        except ImportError:
            release_lock(self.account)
            write_json(result_file, {'ok': False, 'code': EXIT_UNAVAILABLE, 'error': 'Playwright is unavailable. Install novi-browser and run playwright install chromium.'})
            return
        worker = self
        reason = 'error'
        playwright = None
        try:
            end_processes(self.account)
            playwright = sync_playwright().start()
            start_url = ''
            with contextlib.suppress(Exception):
                start_url = site_config(self.config, self.site)[1].get('check_url') or ''
            self.ctx = playwright.chromium.launch_persistent_context(str(self.dir / 'profile'), **launch_options(self.headed, start_url, engine, installed_chrome()[1]))
            self.ctx.set_default_timeout(10000)
            self.ctx.set_default_navigation_timeout(30000)
            self.restore_session()
            token = _secrets.token_hex(16)

            class Handler(BaseHTTPRequestHandler):

                def log_message(self, *args):
                    pass

                def do_POST(self):
                    if self.headers.get('X-Token') != token:
                        self.send_error(403)
                        return
                    payload = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
                    card, site = (payload.get('card') or '-', payload.get('site') or None)
                    try:
                        if self.path == '/exec':
                            answer = worker.run_code(payload.get('code') or '', payload.get('cwd') or '', payload.get('timeout') or 120, card=card, site=site or '')
                        elif self.path == '/close':
                            worker.closing = payload.get('reason') or 'closed'
                            answer = {'ok': True}
                        elif self.path == '/release':
                            worker.release(card)
                            answer = {'ok': True, 'closing': bool(worker.closing), 'cards': sorted(worker.cards)}
                        elif self.path in ('/check', '/login'):
                            worker.touch(card)
                            update_lock(worker.account, used=worker.used, cards=worker.cards)
                            ok = worker.signed_in_or_login(site) if self.path == '/check' else worker.login_once(site)
                            answer = {'ok': True, 'signed_in': ok, 'site': site_config(worker.config, site)[0], 'url': worker.page.url}
                            if not ok and getattr(worker, 'login_page', None):
                                answer['login_page'] = worker.login_page
                        else:
                            answer = {'ok': False, 'error': 'unknown'}
                    except BrowserError as exc:
                        answer = {'ok': False, 'error': str(exc), 'code': exc.code}
                    except Exception as exc:
                        answer = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:500]}
                    data = json.dumps(answer, ensure_ascii=False).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            threading.Thread(target=self.watchdog, args=(started,), daemon=True).start()
            server = HTTPServer(('127.0.0.1', 0), Handler)
            server.timeout = 1.0
            update_lock(self.account, port=server.server_address[1], token=token)
            ok, site = (False, '')
            with contextlib.suppress(Exception):
                site = site_config(self.config, self.site)[0]
                ok = self.signed_in_or_login(site)
            if self.headed and (not ok) and (not getattr(self, 'login_page', None)):
                with contextlib.suppress(Exception):
                    self.page.goto(site_config(self.config, site or None)[1].get('home'), wait_until='domcontentloaded')
            self.save_session()
            write_json(result_file, {'ok': True, 'signed_in': ok, 'site': site, 'url': self.page.url})
            idle_limit = HEADED_IDLE_SECONDS if self.headed and (not needs_window(self.config, self.site)) else IDLE_SECONDS
            while not self.closing:
                server.handle_request()
                if not [p for p in self.ctx.pages if not p.is_closed()]:
                    self.closing = 'window closed'
                elif time.time() - self.used > idle_limit and time.time() > shared_until(self.account):
                    self.closing = 'idle'
                elif time.time() - self.saved > SAVE_SECONDS:
                    self.save_session()
            reason = self.closing
            server.server_close()
        except Exception as exc:
            reason = f'error: {exc}'[:300]
            if not result_file.exists():
                write_json(result_file, {'ok': False, 'code': EXIT_FAILED, 'error': f'Could not start browser: {exc}'[:500]})
        finally:
            self.peak_mb = max(self.peak_mb, private_mb(profile_processes(self.account)))
            if hasattr(self, 'ctx'):
                self.save_session()
                with contextlib.suppress(Exception):
                    self.ctx.close()
            if playwright:
                with contextlib.suppress(Exception):
                    playwright.stop()
            for _ in range(20):
                if not profile_processes(self.account):
                    break
                time.sleep(0.5)
            leftover = end_processes(self.account)
            release_lock(self.account)
            with contextlib.suppress(Exception):
                unshare_window(self.account, '')
            record_run({'account': self.account, 'card': self.card, 'headed': self.headed, 'seconds': round(time.time() - started, 1), 'execs': self.execs, 'errors': self.errors, 'signed_in': sorted(self.verified), 'peak_mb': self.peak_mb, 'leftover': leftover, 'closed': reason, 'engine': self.engine})

def call(lock: dict, path: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(f"http://127.0.0.1:{lock['port']}{path}", data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-Token': lock['token']}, method='POST')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))

def refused(exc: BaseException) -> bool:
    return isinstance(getattr(exc, 'reason', exc), ConnectionRefusedError)

def call_fresh(account: str, card: str, lock: dict, path: str, payload: dict, timeout: float, headed: bool=False, site: str='') -> dict:
    try:
        return call(lock, path, payload, timeout)
    except (OSError, ValueError) as exc:
        if not refused(exc):
            raise
    deadline = time.time() + START_WAIT_SECONDS
    while time.time() < deadline and (read_lock(account) or {}).get('pid') == lock.get('pid'):
        time.sleep(0.5)
    lock, _ = ensure(account, card, headed=headed, site=site)
    lock = wait_turn(account, card) or lock
    return call(lock, path, payload, timeout)

def spawn(account: str, card: str, headed: bool, nonce: str, site: str='') -> None:
    args = ['_serve', account, '--nonce', nonce] + (['--card', card] if card else []) + (['--site', site] if site else []) + (['--headed'] if headed else [])
    launch_detached(args, folder(account), nonce, 'worker.log')

def launch_detached(args: list, private: Path, nonce: str, log_name: str) -> None:
    """Run this file with args in a process that outlives the caller and its job object."""
    script = str(Path(__file__).resolve())
    if WINDOWS:
        # WMI detaches from the caller's job, but does not inherit its environment.
        # Transfer it through a private, short-lived file rather than exposing secrets in argv.
        environment = private / f'environment-{nonce}.json'
        write_json(environment, dict(os.environ, NOVI_BROWSER_HOME=str(HOME.resolve())))
        exe = Path(sys.executable)
        quiet = exe.with_name('pythonw.exe')
        bootstrap = ('import json,os,runpy,sys;from pathlib import Path;'
                     'p=Path(sys.argv.pop(1));os.environ.update(json.loads(p.read_text(encoding="utf-8")));'
                     'p.unlink();runpy.run_path(sys.argv.pop(1),run_name="__main__")')
        line = subprocess.list2cmdline([str(quiet if quiet.exists() else exe), '-X', 'utf8', '-c', bootstrap,
                                       str(environment.resolve()), script, *args])
        command = "$ErrorActionPreference='Stop'; $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=" + "'" + line.replace("'", "''") + "'}; exit $r.ReturnValue"
        try:
            done = subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True, timeout=60, creationflags=134217728)
            if done.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        environment.unlink(missing_ok=True)
        # Restricted Windows installations may deny WMI. Native detachment still works outside caller job cleanup.
        with (HOME / log_name).open('a', encoding='utf-8') as log:
            child = [str(quiet if quiet.exists() else exe), '-X', 'utf8', script, *args]
            options = dict(stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                           env=dict(os.environ, NOVI_BROWSER_HOME=str(HOME.resolve())), close_fds=True)
            try:
                subprocess.Popen(child, creationflags=0x01000000 | 0x00000008 | 0x00000200, **options)
            except OSError:
                subprocess.Popen(child, creationflags=0x00000008 | 0x00000200, **options)
    else:
        HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
        log = (HOME / log_name).open('a')
        subprocess.Popen([sys.executable, script, *args], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)

def close_worker(account: str, reason: str='closed', wait: float=30, pid=None) -> bool:
    lock = read_lock(account)
    if not lock or (pid is not None and lock.get('pid') != pid):
        return False
    pid = lock.get('pid')

    def still_there():
        now = read_lock(account)
        return bool(now) and now.get('pid') == pid
    if lock.get('port'):
        with contextlib.suppress(OSError, ValueError):
            call(lock, '/close', {'reason': reason}, timeout=10)
    deadline = time.time() + wait
    while time.time() < deadline and still_there():
        time.sleep(0.5)
    if still_there():
        with contextlib.suppress(Exception):
            import psutil
            psutil.Process(int(pid)).kill()
        end_processes(account)
        if (read_json(lock_path(account)) or {}).get('pid') == pid:
            with contextlib.suppress(OSError):
                lock_path(account).unlink()
    return True

def others_using(lock: dict, card: str) -> list[str]:
    now = time.time()
    cards = lock.get('cards') or ({lock['card']: lock.get('used') or 0} if lock.get('card') else {})
    recent = [other for other, used in cards.items() if other not in (card, '-') and now - float(used or 0) < TAKEOVER_SECONDS]
    if lock.get('busy') and lock.get('card_now') not in (None, card) and (lock['card_now'] not in recent):
        recent.append(lock['card_now'])
    return recent

def ensure(account: str, card: str, headed: bool=False, site: str='', _retry: bool=False) -> tuple[dict, dict]:
    load_account(account)
    lock = read_lock(account)
    if lock and lock.get('port'):
        if not headed or lock.get('headed'):
            return (lock, {})
        others = others_using(lock, card)
        if others:
            raise BrowserError(f"Another session ({', '.join((o[:8] for o in others))}) is using {account} browser is in use; cannot reopen headed. Retry in {TAKEOVER_SECONDS // 60} minutes.", EXIT_LOCKED)
        close_worker(account, 'reopened')
    elif lock:
        deadline = time.time() + START_WAIT_SECONDS
        while time.time() < deadline and lock and (not lock.get('port')):
            time.sleep(0.5)
            lock = read_lock(account)
        if lock and lock.get('port'):
            return ensure(account, card, headed, site, _retry)
    ok, why = room_for_one(len(running()), free_mb())
    if not ok:
        raise BrowserError(f'WAITING_RESOURCE: {why}. Close unused profiles and retry.', EXIT_RESOURCE)
    nonce = _secrets.token_hex(6)
    result_file = folder(account) / f'start-{nonce}.json'
    spawn(account, card, headed, nonce, site)
    deadline = time.time() + START_WAIT_SECONDS
    while time.time() < deadline and (not result_file.exists()):
        time.sleep(0.3)
    answer = read_json(result_file, {}) or {}
    with contextlib.suppress(OSError):
        result_file.unlink()
    if not answer:
        raise BrowserError(f'{account} browser took {START_WAIT_SECONDS} seconds without starting. Retry after a minute.')
    if not answer.get('ok'):
        if answer.get('code') == EXIT_LOCKED and (not _retry) and read_lock(account):
            return ensure(account, card, headed, site, _retry=True)
        raise BrowserError(answer.get('error') or 'Could not start browser', int(answer.get('code') or EXIT_FAILED))
    lock = read_lock(account)
    if not lock or not lock.get('port'):
        raise BrowserError(f'{account} browser exited immediately after starting')
    return (lock, answer)
MEMORY_SHOW_CHARS = 12000
MEMORY_SHOWN_DAYS = 3

def memory_post(payload: dict, timeout: float=30) -> dict:
    """Append-only local site notes; no network requests."""
    from urllib.parse import urlsplit

    def host(value):
        return urlsplit(value if '://' in value else 'https://' + value).netloc.lower()
    path = HOME / 'memory.jsonl'
    notes = []
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            with contextlib.suppress(ValueError):
                notes.append(json.loads(line))
    action = payload.get('action')
    if action == 'note':
        text = str(payload.get('text') or '').strip()
        if not text:
            raise BrowserError('A note must contain text', EXIT_USAGE)
        note = dict(key=_secrets.token_hex(12), title=payload.get('site') or host(payload.get('host', '')), body=text, line=text, host=host(payload.get('host', '')), site=payload.get('site', ''), source='local', kind='site', at=time.time(), session=payload.get('card', ''))
        HOME.mkdir(parents=True, exist_ok=True, mode=0o777 if WINDOWS else 0o700)
        with path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(note, ensure_ascii=False) + '\n')
        return note
    if action == 'log':
        text = ' '.join(str(payload.get('text') or '').split())
        if not text or not payload.get('site'):
            raise BrowserError('A work-log line needs a site and text', EXIT_USAGE)
        note = dict(key=_secrets.token_hex(12), title=time.strftime('%Y-%m-%d') + ' work log', body=text, line=text, host='', site=payload.get('site', ''), source='local', kind='episodic', at=time.time(), session=payload.get('card', ''), profile=payload.get('account', ''))
        HOME.mkdir(parents=True, exist_ok=True, mode=0o777 if WINDOWS else 0o700)
        with path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(note, ensure_ascii=False) + '\n')
        return note
    if action == 'read':
        for note in notes:
            if note['key'] == payload.get('key'):
                return note
        raise BrowserError('No note with that key')
    if action == 'search':
        query = str(payload.get('query', '')).casefold()
        found = [dict(n, snippet=n['body'][:300]) for n in reversed(notes) if query in (n['title'] + ' ' + n['body']).casefold() and (not payload.get('kinds') or n['kind'] in payload['kinds'])]
        return dict(total=len(found), results=found[:payload.get('limit', 15)])
    if action == 'site':
        hosts = {host(h) for h in payload.get('hosts', [])}
        names = {n.casefold() for n in payload.get('names', [])}
        found = [n for n in reversed(notes) if n.get('kind', 'site') == 'site' and (n['host'] in hosts or n['site'].casefold() in names)]
        return dict(notes=found[:payload.get('limit', 8)])
    raise BrowserError('Unknown memory action', EXIT_USAGE)

def site_hosts(entry: dict) -> list[str]:
    login = entry.get('login') if isinstance(entry.get('login'), dict) else {}
    return list(dict.fromkeys((url for url in (entry.get('check_url'), entry.get('home'), login.get('url')) if url)))

def format_notes(notes: list[dict], limit: int) -> str:
    shown, rest, used = ([], [], 0)
    for note in notes:
        block = f"### {note['title'] or note['key']} · {note.get('source') or ''} · {note['key']}\n{note['body'].strip()}\n"
        if used and used + len(block) > limit:
            rest.append(note['key'])
            continue
        shown.append(block if len(block) <= limit else block[:limit] + f"\n… (Truncated: `memory --read {note['key']}`)\n")
        used += len(shown[-1])
    if rest:
        shown.append('More: ' + ', '.join((f'`memory --read {key}`' for key in rest)))
    return '\n'.join(shown)

def site_memory(config: dict, site: str, limit: int=8, timeout: float=30) -> list[dict]:
    entry = site_config(config, site)[1]
    return memory_post({'action': 'site', 'hosts': site_hosts(entry), 'names': [site], 'limit': limit}, timeout=timeout)['notes']
def show_site_memory(account: str, config: dict, site: str, card: str, out=None) -> None:
    marker = HOME / 'memory-shown.json'
    shown = read_json(marker, {}) or {}
    key = f'{card}|{account}|{site}'
    if key in shown:
        return
    notes = site_memory(config, site)
    if notes:
        print(f'--- {site}: local site notes ---\n{format_notes(notes, MEMORY_SHOW_CHARS)}\n--- end notes ---', file=out or sys.stdout)
    cutoff = time.time() - MEMORY_SHOWN_DAYS * 86400
    shown = {key: at for key, at in shown.items() if at > cutoff}
    shown[key] = time.time()
    write_json(marker, shown)

def login_line(account: str, signed: bool, config: dict, site: str='') -> str:
    name, entry = site_config(config, site or None)
    if signed:
        return f"{account}: {name} signed in ({entry.get('user') or 'identity unspecified'})"
    tried = auto_login_record(account, name)
    detail = ''
    if tried and tried.get('ok') is not True:
        detail = ' Saved login was refused or its outcome is unknown; it will not be retried automatically.'
    return f'{account}: {name} AUTH_EXPIRED.{detail} Use open {account} --site {name} --headed for human login, then check.'

def card_ids(lock: dict) -> list[str]:
    return [card for card in lock.get('cards') or {lock.get('card') or '-': 0} if card and card != '-']

def release(account: str, card: str, pid=None) -> bool:
    lock = read_lock(account)
    if not lock or not lock.get('port') or (pid is not None and lock.get('pid') != pid):
        return False
    try:
        answer = call(lock, '/release', {'card': card}, timeout=60)
    except (OSError, ValueError):
        return close_worker(account, 'card over', pid=lock.get('pid')) if card_ids(lock) == [card] else False
    return bool(answer.get('ok'))

def sweep(over, log=lambda text: None, busy=lambda: set()) -> list[str]:
    locks = {account: lock for account, lock in running().items() if card_ids(lock)}
    held = {card for lock in locks.values() for card in card_ids(lock)}
    if not held:
        return []
    finished = set(over(sorted(held)) or []) - set(busy())
    touched = []
    for account, lock in locks.items():
        for card in card_ids(lock):
            if card in finished and release(account, card, pid=lock.get('pid')):
                if account not in touched:
                    touched.append(account)
                log(f'Browser cleanup: {account} (session {card[:8]} ended)')
    return touched

def wait_turn(account: str, card: str, limit: float=180) -> dict | None:
    deadline = time.time() + limit
    lock = read_lock(account)
    while lock and lock.get('busy') and (lock.get('card_now') not in (None, card)) and (time.time() < deadline):
        time.sleep(1)
        lock = read_lock(account)
    return lock

def stats(days: int) -> dict:
    since = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - days * 86400))
    rows = []
    with contextlib.suppress(OSError):
        for line in (HOME / 'runs.jsonl').read_text(encoding='utf-8').splitlines():
            with contextlib.suppress(ValueError):
                row = json.loads(line)
                if row.get('at', '') >= since:
                    rows.append(row)
    per = {}
    for row in rows:
        entry = per.setdefault(row.get('account', '?'), {'runs': 0, 'execs': 0, 'errors': 0, 'signed_out': 0, 'mb': [], 'leftover': 0})
        entry['runs'] += 1
        entry['execs'] += row.get('execs', 0)
        entry['errors'] += row.get('errors', 0)
        entry['signed_out'] += 0 if row.get('signed_in') else 1
        entry['leftover'] += row.get('leftover', 0)
        if row.get('peak_mb'):
            entry['mb'].append(row['peak_mb'])
    for entry in per.values():
        mb = entry.pop('mb')
        entry['avg_mb'] = round(sum(mb) / len(mb)) if mb else None
        entry['max_mb'] = round(max(mb)) if mb else None
    return per
AGENT_ENV = 'NOVI_BROWSER_AGENT'
AGENT_MODEL = os.environ.get('NOVI_BROWSER_AGENT_MODEL', 'sonnet')
AGENT_FLAGS = ['--tools', 'Bash', '--strict-mcp-config', '--disable-slash-commands']
AGENT_DROP_ENV = ('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDE_CODE_MESSAGING_SOCKET', 'CLAUDE_CODE_MESSAGING_TOKEN', 'CLAUDE_CODE_SESSION_ID')
AGENT_RULES = 'You are a browser task agent. Complete the assigned task using only:\n{exec_cmd} exec {account} --site {site} -c \'<Playwright Python>\'\nRead snap() before using refs such as e12 or f1e2. Use snap(interactive=True) or\nsnap(selector=\'[role="dialog"]\') to narrow the view. Never invent refs.\nUse click(ref), fill(ref, value), press(key), select(ref, value). These settle the page\nand return changed lines; avoid fixed waits. Use goto, text, diff, pages, use, check,\nlogin, secret, human_click, human_type, page.set_input_files, and shot as needed.\nVariables persist between exec calls. Keep screenshots under {cwd}.\nRead the local notes printed on first open/exec. Save useful discoveries with:\n{exec_cmd} remember {account} --site {site} "<note>"\nSearch with {exec_cmd} memory --search "<query>". Never print secret values.\nStop before posting, sending, deleting, purchasing or final submission unless explicitly\nauthorized in the task. For authorized irreversible actions, call intent(key, what,\nsite="{site}") immediately before the click and done(key, url) after confirmation.\nAn unresolved intent requires inspection and resolve; never blindly retry.\nFor expired login, try login once. For captchas or human verification, report the\nblocker and screenshot path for the human; use open --headed for assistance.\nDo not start another agent. Leave the task tab open. Return a concise result,\nevidence or screenshot path, and any remaining blocker.'

def find_claude() -> str:
    import shutil
    found = shutil.which('claude')
    if found:
        return found
    for candidate in (Path.home() / '.local' / 'bin' / ('claude.exe' if WINDOWS else 'claude'), Path('/opt/homebrew/bin/claude')):
        if candidate.exists():
            return str(candidate)
    raise BrowserError('claude executable not found; install Claude Code to use agent mode.', EXIT_UNAVAILABLE)

def agent_command(account: str, site: str, task: str, *, resume: str='', model: str=AGENT_MODEL, session: str='', cwd: str='') -> tuple[list, dict]:
    exec_cmd = f'"{Path(sys.executable).as_posix()}" "{Path(__file__).resolve().as_posix()}"'
    rules = AGENT_RULES.format(exec_cmd=exec_cmd, account=account, site=site, cwd=cwd or os.getcwd())
    argv = [find_claude(), '-p', '--output-format', 'json', '--model', model, '--dangerously-skip-permissions', *AGENT_FLAGS, '--append-system-prompt', rules]
    argv += ['--resume', resume] if resume else ['--session-id', session] if session else []
    argv.append(task)
    env = {k: v for k, v in os.environ.items() if k not in AGENT_DROP_ENV}
    env[AGENT_ENV] = '1'
    env[CARD_ENV] = session_id()
    return (argv, env)

LOG_TASK_CHARS, LOG_RESULT_CHARS = 200, 600

def squash(text, limit: int) -> str:
    flat = ' '.join(str(text or '').split())
    return flat if len(flat) <= limit else flat[:limit - 1] + '…'

def agent_log_line(task: str, answer: dict, resumed: bool) -> str:
    """One work-log line cut from the task and the agent's own last answer (no second model call)."""
    head = ('(resumed) ' if resumed else '') + squash(task, LOG_TASK_CHARS)
    state = '[stopped/error] ' if answer.get('is_error') else ''
    return f"{head} -> {state}{squash(answer.get('result'), LOG_RESULT_CHARS) or '(no answer)'}"

def log_agent_run(args, site: str, task: str, answer: dict) -> None:
    """Every agent run appends one work-log line (kind episodic): never printed at a site's first open, found with
    `memory --search`. Best effort: the run already happened."""
    try:
        memory_post({'action': 'log', 'site': site, 'account': args.account, 'card': os.environ.get(CARD_ENV, ''), 'text': agent_log_line(task, answer, bool(args.resume))})
    except Exception as exc:
        print(f'(Could not write the work log: {exc})', file=sys.stderr)

def run_agent(args) -> int:
    if os.environ.get(AGENT_ENV):
        raise BrowserError('An agent cannot start another agent. Use exec.', EXIT_USAGE)
    config = load_account(args.account)
    site = site_config(config, args.site or None)[0]
    task = args.task if args.task != '-' else sys.stdin.read()
    if not task.strip():
        raise BrowserError('agent <profile> --site <site> "<task and completion criteria>"', EXIT_USAGE)
    import uuid
    session = args.resume or str(uuid.uuid4())
    argv, env = agent_command(args.account, site, task, resume=args.resume, model=args.model, session='' if args.resume else session, cwd=os.getcwd())

    def again(sid):
        return f'{Path(__file__).name} agent {args.account} --site {site} --resume {sid} "<continuation task>"'
    started = time.monotonic()
    try:
        done = subprocess.run(argv, env=env, cwd=os.getcwd(), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=args.timeout)
    except subprocess.TimeoutExpired:
        raise BrowserError(f'Agent took {args.timeout:.0f} seconds without completing. Inspect snap() or resume: {again(session)}')
    seconds = time.monotonic() - started
    try:
        answer = json.loads(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else {}
    except ValueError:
        answer = {}
    if not answer:
        raise BrowserError(f'Agent returned no answer (exit {done.returncode}).\n{(done.stderr or done.stdout)[-1500:]}')
    print((answer.get('result') or '').strip())
    log_agent_run(args, site, task, answer)
    cost, session = (answer.get('total_cost_usd'), answer.get('session_id') or session)
    print(f"\n[Agent session {session} · {answer.get('num_turns', '?')} turns{(f' · ${cost:.2f}' if isinstance(cost, (int, float)) else '')} · {seconds:.0f} seconds] Resume: {again(session)}")
    return EXIT_FAILED if answer.get('is_error') else 0
REMOTE_HOST = os.environ.get('NOVI_BROWSER_REMOTE', '')
REMOTE_FILES = '@@NOVI_BROWSER_FILES@@ '
REMOTE_FILE_MB = 20

def forward_payload(argv: list[str], stdin_text: str, card: str, cwd: Path) -> dict:
    rest, files = ([], {})
    items = iter(argv)
    for item in items:
        if item == '--put':
            path = Path(next(items, ''))
            path = path if path.is_absolute() else cwd / path
            if not path.is_file():
                raise BrowserError(f'--put file not found: {path}', EXIT_USAGE)
            files[path.name] = base64_text(path.read_bytes())
        else:
            rest.append(item)
    return {'argv': rest, 'stdin': stdin_text, 'card': card, 'files': files}

def base64_text(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode('ascii')

def forward(argv: list[str]) -> int:
    import base64
    stdin_text = '' if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    try:
        payload = forward_payload(argv, stdin_text, session_id(), Path.cwd())
    except BrowserError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', REMOTE_HOST, 'novi-browser _remote']
    try:
        done = subprocess.run(ssh, input=json.dumps(payload).encode('utf-8'), capture_output=True, timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f'Remote browser unreachable ({exc}).', file=sys.stderr)
        return EXIT_UNAVAILABLE
    if done.returncode == 255:
        print('Remote browser unreachable: ' + done.stderr.decode('utf-8', 'replace').strip(), file=sys.stderr)
        return EXIT_UNAVAILABLE
    out = done.stdout.decode('utf-8', 'replace')
    if REMOTE_FILES in out:
        out, _, blob = out.rpartition(REMOTE_FILES)
        for name, data in (json.loads(blob.strip() or '{}') or {}).items():
            target = Path.cwd() / Path(name).name
            target.write_bytes(base64.b64decode(data))
            out += f'Received remote file: {target}\n'
    sys.stdout.write(out)
    sys.stderr.write(done.stderr.decode('utf-8', 'replace'))
    return done.returncode

def serve_remote() -> int:
    import base64
    payload = json.loads(sys.stdin.buffer.read().decode('utf-8'))
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    card = str(payload.get('card') or '')
    work = HOME / 'remote' / (re.sub('[^0-9A-Za-z_-]', '', card) or 'none')
    work.mkdir(parents=True, exist_ok=True)
    for name, data in (payload.get('files') or {}).items():
        (work / Path(name).name).write_bytes(base64.b64decode(data))
    before = {p.name: p.stat().st_mtime for p in work.iterdir() if p.is_file()}
    if card:
        os.environ[CARD_ENV] = card
    os.chdir(work)
    sys.stdin = io.StringIO(payload.get('stdin') or '')
    try:
        code = main(list(payload.get('argv') or []))
    finally:
        sys.stdout.flush()
    back = {p.name: base64_text(p.read_bytes()) for p in work.iterdir() if p.is_file() and before.get(p.name) != p.stat().st_mtime and (p.stat().st_size <= REMOTE_FILE_MB * 1024 * 1024)}
    if back:
        sys.stdout.write('\n' + REMOTE_FILES + json.dumps(back) + '\n')
    return code

REPO_URL = 'https://github.com/mkt-henry/novi-browser'
# Forks point both at their own copy: a URL of __init__.py and a pip requirement.
VERSION_URL = os.environ.get('NOVI_BROWSER_VERSION_URL') or 'https://raw.githubusercontent.com/mkt-henry/novi-browser/main/novi_browser/__init__.py'
UPDATE_SOURCE = os.environ.get('NOVI_BROWSER_UPDATE_SOURCE') or f'git+{REPO_URL}'
UPDATE_ENV = 'NOVI_BROWSER_NO_UPDATE_CHECK'
AUTO_UPDATE_ENV = 'NOVI_BROWSER_AUTO_UPDATE'
GUIDE_ENV = 'NOVI_BROWSER_NO_GUIDE_INSTALL'
UPDATE_CHECK_HOURS = 24
UPDATE_WAIT_SECONDS = 2 * 3600
UPDATE_LOCK_STALE = 30 * 60
GUIDE = Path(__file__).with_name('SKILL.md')
# Read beside this file: workers and agents run cli.py by path, where package imports fail.
__version__ = (re.findall(r"__version__\s*=\s*['\"]([^'\"]+)", Path(__file__).with_name('__init__.py').read_text(encoding='utf-8')) or ['0'])[0]

def version_tuple(text) -> tuple:
    return tuple(int(part) for part in re.findall(r'\d+', str(text or ''))[:3])

def latest_version(timeout: float=3.0) -> str:
    with urllib.request.urlopen(VERSION_URL, timeout=timeout) as response:
        found = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", response.read(4096).decode('utf-8', 'replace'))
    return found.group(1) if found else ''

def guide_targets() -> list[Path]:
    """Skill folders of agents installed for this user; an agent that is absent gets nothing."""
    user = Path.home()
    return [user / agent / 'skills' / 'novi-browser' / 'SKILL.md' for agent in ('.claude', '.codex') if (user / agent).is_dir()]

def install_guides() -> list[Path]:
    """Copy the packaged agent guide into each agent's skills; rewrite only when it changed."""
    if os.environ.get(GUIDE_ENV) or not GUIDE.is_file():
        return []
    text, written = GUIDE.read_text(encoding='utf-8'), []
    for target in guide_targets():
        try:
            if target.is_file() and target.read_text(encoding='utf-8') == text:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
            written.append(target)
        except OSError:
            continue
    return written

def git_clone() -> bool:
    return (Path(__file__).resolve().parent.parent / '.git').exists()

def auto_update_on() -> bool:
    # Clones belong to developers: they pull themselves.
    return os.environ.get(AUTO_UPDATE_ENV, '1').strip().lower() not in ('0', 'false', 'no', 'off') and not git_clone()

def update_busy() -> bool:
    lock = HOME / 'update.lock'
    try:
        return time.time() - lock.stat().st_mtime < UPDATE_LOCK_STALE
    except OSError:
        return False

def start_background_update(latest: str) -> bool:
    if update_busy():
        return False
    try:
        launch_detached(['_autoupdate', latest], HOME, f'update-{_secrets.token_hex(6)}', 'update.log')
        return True
    except OSError:
        return False

def update_notice(always: bool=False, now: float | None=None) -> str:
    """Asks GitHub at most once a day; a newer version installs itself in the background."""
    if os.environ.get(UPDATE_ENV):
        return ''
    now = time.time() if now is None else now
    path = HOME / 'update-check.json'
    seen = read_json(path, {}) or {}
    done = seen.pop('updated', None)
    if done:
        with contextlib.suppress(OSError):
            write_json(path, seen)
        return f"novi-browser updated itself {done.get('from')} -> {done.get('to')}; agent guides refreshed. Profiles, logins and notes are kept."
    checked = now - float(seen.get('at') or 0) >= UPDATE_CHECK_HOURS * 3600
    if checked:
        try:
            seen = {'at': now, 'latest': latest_version()}
        except (OSError, ValueError):
            # Offline: wait a day instead of slowing every command.
            seen = {'at': now, 'latest': seen.get('latest') or ''}
        with contextlib.suppress(OSError):
            write_json(path, seen)
    latest = seen.get('latest') or ''
    if not latest or version_tuple(latest) <= version_tuple(__version__):
        return ''
    if auto_update_on():
        if checked and start_background_update(latest):
            return f'novi-browser {latest} found (installed {__version__}); it installs itself in the background once no browser is running.'
        return ''
    if always or checked:
        return f'novi-browser {latest} is available (installed {__version__}). Run `novi-browser update`; profiles, logins and notes are kept.'
    return ''

def wait_for_update(limit: float=180) -> None:
    """Commands pause while files are being replaced, so no half-installed code runs."""
    deadline = time.time() + limit
    while update_busy() and time.time() < deadline:
        try:
            if not (HOME / 'update.lock').read_text(encoding='utf-8', errors='replace').startswith('installing'):
                return
        except OSError:
            return
        time.sleep(2)

def installed_version() -> str:
    # -I keeps a clone in the current folder from shadowing the installed package.
    done = subprocess.run([sys.executable, '-I', '-c', 'import novi_browser; print(novi_browser.__version__)'], capture_output=True, text=True, timeout=60)
    return done.stdout.strip() or '?'

def upgrade_command() -> list[str]:
    if git_clone():
        return ['git', '-C', str(Path(__file__).resolve().parent.parent), 'pull', '--ff-only']
    return [sys.executable, '-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check', UPDATE_SOURCE]

def refresh_guides_from_new_code() -> None:
    # The running interpreter still holds the old guide text; ask the newly installed code.
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run([sys.executable, '-I', '-c', 'from novi_browser import cli; cli.install_guides()'], capture_output=True, timeout=60)

def take_update_lock() -> bool:
    lock = HOME / 'update.lock'
    HOME.mkdir(parents=True, exist_ok=True, mode=0o777 if WINDOWS else 0o700)
    for _ in range(2):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            return True
        except FileExistsError:
            if update_busy():
                return False
            with contextlib.suppress(OSError):
                lock.unlink()
    return False

def auto_update(latest: str) -> int:
    """Detached updater: waits until no browser runs, then replaces the package."""
    if not take_update_lock():
        return 0
    lock = HOME / 'update.lock'
    try:
        deadline = time.time() + UPDATE_WAIT_SECONDS
        while running() and time.time() < deadline:
            # Keep the lock fresh while waiting for workers to close after their idle time.
            lock.write_text(f'waiting {os.getpid()}', encoding='utf-8')
            time.sleep(20)
        if running():
            print(f'{time.strftime("%Y-%m-%d %H:%M")} browsers stayed busy; update to {latest} retries tomorrow.', flush=True)
            return 0
        lock.write_text(f'installing {os.getpid()}', encoding='utf-8')
        before = __version__
        code = subprocess.call(upgrade_command(), stdout=sys.stdout, stderr=sys.stderr)
        after = installed_version()
        if code == 0:
            refresh_guides_from_new_code()
            path = HOME / 'update-check.json'
            write_json(path, dict(read_json(path, {}) or {}, updated={'from': before, 'to': after, 'at': time.time()}))
        print(f'{time.strftime("%Y-%m-%d %H:%M")} update to {latest}: exit {code}, installed {after}', flush=True)
        return code
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()

def self_update() -> int:
    command = upgrade_command()
    print('Running: ' + ' '.join(command), flush=True)
    code = subprocess.call(command)
    if code:
        raise BrowserError(f'Update failed (exit {code}). Profiles, logins and notes were not touched.', EXIT_FAILED)
    with contextlib.suppress(OSError):
        (HOME / 'update-check.json').unlink()
    refresh_guides_from_new_code()
    print(f'novi-browser {__version__} -> {installed_version()}. Profiles, logins and notes are kept; agent guides refreshed. Running browsers switch after they close (five idle minutes) or now with `novi-browser close --all`.')
    return 0

def setup(browser: bool=True) -> int:
    """One step after pip install: the agent guide for each agent, then Chromium."""
    written = install_guides()
    for target in guide_targets():
        print(f"Agent guide: {target}{' (written)' if target in written else ' (up to date)'}")
    if not guide_targets():
        print('No Claude Code or Codex folder found; MCP clients receive the guide from novi-browser-mcp. See AGENTS.md for other agents.')
    if browser:
        print('Installing Chromium for Playwright…', flush=True)
        code = subprocess.call([sys.executable, '-m', 'playwright', 'install', 'chromium'])
        if code:
            raise BrowserError(f'Chromium install failed (exit {code}). Run `python -m playwright install chromium`.', EXIT_UNAVAILABLE)
    print('Ready. Updates install automatically once a day; set NOVI_BROWSER_AUTO_UPDATE=0 to only be told.')
    return 0

def main(argv=None) -> int:
    if (argv if argv is not None else sys.argv[1:])[:1] == ['_remote']:
        return serve_remote()
    parser = argparse.ArgumentParser(prog='novi-browser', description='No.VI agent browser: one persistent profile per identity')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list')
    sub.add_parser('update', help='Install the latest version from GitHub now')
    sp = sub.add_parser('setup', help='Install the agent guides and Chromium')
    sp.add_argument('--no-browser', action='store_true', help='Skip the Chromium download')
    auto = sub.add_parser('_autoupdate')
    auto.add_argument('latest')
    add = sub.add_parser('add')
    add.add_argument('account', type=profile_name)
    add.add_argument('--site', required=True)
    add.add_argument('--check', required=True)
    add.add_argument('--signed-out', action='append', default=[])
    add.add_argument('--signed-in-text', default='')
    add.add_argument('--user', default='')
    add.add_argument('--secret', default='')
    add.add_argument('--home', default='')
    add.add_argument('--note', default='')
    add.add_argument('--label', default='')
    add.add_argument('--identity', default='', help='Login identity when sites have no user field')
    add.add_argument('--login-url', default='')
    add.add_argument('--user-field', default='')
    add.add_argument('--password-field', default='')
    add.add_argument('--submit', default='')
    add.add_argument('--window', action='store_true', help='Always use a visible window for this site')
    for name in ('open', 'exec', 'close', 'check', 'login'):
        cmd = sub.add_parser(name)
        cmd.add_argument('account', nargs='?' if name == 'close' else None, type=profile_name)
        cmd.add_argument('--session', '--card', dest='card', default=session_id())
        if name != 'close':
            cmd.add_argument('--site', default='')
        if name == 'open':
            cmd.add_argument('--headed', action='store_true')
            cmd.add_argument('--note', default='', help='Note passed to the optional window share hook')
            cmd.add_argument('--project', default='', help='Optional project label')
            cmd.add_argument('--no-remote', action='store_true', help='Skip the optional window share hook')
            cmd.add_argument('--no-notify', action='store_true', help='Compatibility flag; hooks manage notifications')
        if name == 'exec':
            cmd.add_argument('-c', '--code')
            cmd.add_argument('--timeout', type=float, default=120)
        if name == 'close':
            cmd.add_argument('--all', action='store_true')
    ag = sub.add_parser('agent')
    ag.add_argument('account', type=profile_name)
    ag.add_argument('task', help='Task and completion criteria (- reads stdin)')
    ag.add_argument('--site', default='')
    ag.add_argument('--resume', default='', help='Resume an agent session')
    ag.add_argument('--model', default=AGENT_MODEL)
    ag.add_argument('--timeout', type=float, default=570, help='Agent timeout in seconds; reports the session for resuming')
    led = sub.add_parser('ledger')
    led.add_argument('account', type=profile_name)
    res = sub.add_parser('resolve')
    res.add_argument('account', type=profile_name)
    res.add_argument('--key', required=True)
    res.add_argument('--state', required=True, choices=('done', 'failed'))
    res.add_argument('--url', default='')
    st = sub.add_parser('stats')
    st.add_argument('--days', type=int, default=7)
    mem = sub.add_parser('memory')
    mem.add_argument('account', nargs='?', type=profile_name)
    mem.add_argument('--site', default='')
    mem.add_argument('--url', default='', help='URL of a site without a registered profile')
    mem.add_argument('--search', default='', help='Search local site notes')
    mem.add_argument('--kind', action='append', default=[], help='Filter search by note kind (site, episodic)')
    mem.add_argument('--read', default='', help='Read a full note by key')
    rem = sub.add_parser('remember')
    rem.add_argument('account', nargs='?', type=profile_name)
    rem.add_argument('text')
    rem.add_argument('--site', default='')
    rem.add_argument('--url', default='')
    rem.add_argument('--session', '--card', dest='card', default=session_id())
    serve = sub.add_parser('_serve')
    serve.add_argument('account', type=profile_name)
    serve.add_argument('--card', default='')
    serve.add_argument('--site', default='')
    serve.add_argument('--headed', action='store_true')
    serve.add_argument('--nonce', required=True)
    tokens = list(sys.argv[1:] if argv is None else argv)
    # Two positional arguments, one optional, need intermixing for `remember No1 --site X "note"`.
    if tokens[:1] == ['remember']:
        args = sub.choices['remember'].parse_intermixed_args(tokens[1:])
        args.cmd = 'remember'
    else:
        args = parser.parse_args(tokens)
    if hasattr(sys.stdout, 'reconfigure'):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding='utf-8')
    if args.cmd not in ('_serve', '_autoupdate', 'update', 'setup'):
        wait_for_update()
        install_guides()
        notice = update_notice(always=args.cmd == 'list')
        if notice:
            print(notice, file=sys.stderr)
    try:
        return run(args)
    except BrowserError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code

def run(args) -> int:
    if args.cmd == '_serve':
        if sys.stdout is None or sys.stderr is None or WINDOWS:
            log = (HOME / 'worker.log').open('a', encoding='utf-8')
            sys.stdout = sys.stderr = log
        Worker(args.account, args.card, args.headed, args.site).serve(args.nonce)
        return 0
    if args.cmd == 'agent':
        return run_agent(args)
    if args.cmd == 'update':
        return self_update()
    if args.cmd == 'setup':
        return setup(browser=not args.no_browser)
    if args.cmd == '_autoupdate':
        if sys.stdout is None or sys.stderr is None or WINDOWS:
            log = (HOME / 'update.log').open('a', encoding='utf-8')
            sys.stdout = sys.stderr = log
        return auto_update(args.latest)
    if args.cmd == 'list':
        live = running()
        for account in accounts():
            config, state, lock = (load_account(account), auth_state(account), live.get(account))
            pending = [k for k, e in ledger(account).items() if e['state'] == 'intent']
            who = identity(config) or config.get('label') or '-'
            line = f'{account} · {who}'
            if lock:
                cards = ', '.join((card[:8] for card in card_ids(lock))) or '-'
                line += f" · running (sessions {cards}{(', headed' if lock.get('headed') else '')}, {int(time.time() - float(lock.get('used') or 0))} seconds since use)"
            if pending:
                line += f' · unknown outcomes: {len(pending)}'
            print(line)
            for site, entry in config['sites'].items():
                seen = state.get(site) or {}
                print(f"  - {site} {entry.get('user') or ''} · {seen.get('auth', 'UNKNOWN')} {seen.get('checked_at', '')}{(' · saved login available' if entry.get('login') else '')}".replace('  ·', ' ·'))
        available = free_mb()
        print(f'No.VI browsers: {len(live)} running · available memory {available / 1024:.1f}GB' if available is not None else f'No.VI browsers: {len(live)} running')
        return 0
    if args.cmd == 'add':
        login = {'url': args.login_url, 'user_field': args.user_field, 'password_field': args.password_field, 'submit': args.submit}
        add_account(args.account, site=args.site, check=args.check, signed_out=args.signed_out, signed_in_text=args.signed_in_text, user=args.user, secret=args.secret, home=args.home, note=args.note, login=login, label=args.label, window=args.window, who=args.identity)
        how = f'login {args.account} --site {args.site}' if args.login_url else f'open {args.account} --site {args.site} --headed'
        print(f'{args.account}: {args.site} registered. Use `{how}` to sign in once.')
        return 0
    if args.cmd == 'close':
        if args.account:
            for account in [args.account]:
                unshare_window(account, '')
                print(f"{account}: {('saved login and closed' if close_worker(account) else 'not running')}")
        elif args.all:
            for account in list(running()):
                unshare_window(account, '')
                print(f"{account}: {('saved login and closed' if close_worker(account) else 'not running')}")
        elif args.card:
            for account, lock in running().items():
                unshare_window(account, args.card)
                if args.card in card_ids(lock) and release(account, args.card):
                    print(f'{account}: session tabs released')
        else:
            raise BrowserError('close <profile> | --session <session> | --all', EXIT_USAGE)
        return 0
    if args.cmd == 'ledger':
        for key, entry in ledger(args.account).items():
            print(f"{key} · {entry['state']} · {entry['at']} · {entry.get('what') or ''} {entry.get('url') or ''}".rstrip())
        return 0
    if args.cmd == 'resolve':
        end_post(args.account, args.key, args.state, url=args.url)
        print(f'{args.key}: {args.state}')
        return 0
    if args.cmd == 'stats':
        print(json.dumps(stats(args.days), ensure_ascii=False, indent=1))
        return 0
    if args.cmd == 'memory':
        if args.read:
            note = memory_post({'action': 'read', 'key': args.read})
            print(f"### {note['title']} · {note['source']} · {note['key']}\n{note['body']}")
        elif args.search:
            found = memory_post({'action': 'search', 'query': args.search, 'kinds': args.kind, 'limit': 15})
            for hit in found['results']:
                print(f"- {hit['key']} · {hit['title']} · {hit['source']}\n  …{hit['snippet']}…")
            print(f"{found['total']} total; showing {len(found['results'])}. Read complete notes with memory --read <key>." if found['total'] else 'No matching notes.')
        elif args.url:
            notes = memory_post({'action': 'site', 'hosts': [args.url], 'names': [], 'limit': 20})['notes']
            print(format_notes(notes, 60000) if notes else f'{args.url}: no site notes.')
        elif args.account:
            config = load_account(args.account)
            site = site_config(config, args.site or None)[0]
            notes = site_memory(config, site, limit=20)
            print(format_notes(notes, 60000) if notes else f'{site}: no site notes.')
        else:
            raise BrowserError('memory <profile> --site <site> | --url <url> | --search <query> | --read <key>', EXIT_USAGE)
        return 0
    if args.cmd == 'remember':
        if args.account:
            config = load_account(args.account)
            site, entry = site_config(config, args.site or None)
            host = (site_hosts(entry) or [''])[0]
        elif args.url:
            site, host = ('', args.url)
        else:
            raise BrowserError('remember <profile> --site <site> "<note>" | --url <url> "<note>"', EXIT_USAGE)
        saved = memory_post({'action': 'note', 'host': host, 'site': site, 'text': args.text, 'card': args.card})
        print(f"Saved: {saved['line']}")
        return 0
    config = load_account(args.account)
    site = site_config(config, args.site or None)[0]
    card = args.card or '-'
    if args.cmd in ('open', 'exec'):
        show_site_memory(args.account, config, site, card)
    headed = getattr(args, 'headed', False) or needs_window(config, site)
    lock, started = ensure(args.account, card, headed=headed, site=site)
    lock = wait_turn(args.account, card) or lock
    if args.cmd in ('open', 'check', 'login'):
        if started and args.cmd == 'open' and (started.get('site') == site):
            answer = started
        else:
            try:
                answer = call_fresh(args.account, card, lock, f"/{('login' if args.cmd == 'login' else 'check')}", {'card': card, 'site': site}, timeout=120, headed=headed, site=site)
            except (OSError, ValueError) as exc:
                raise BrowserError(f'Browser did not respond ({exc})')
            if not answer.get('ok'):
                raise BrowserError(answer.get('error') or 'Could not verify login', int(answer.get('code') or EXIT_FAILED))
        signed = bool(answer.get('signed_in'))
        stuck = answer.get('login_page') or {}
        if stuck:
            print(f"{args.account}: {site} saved login was attempted once and refused. No automatic retry.\nURL: {stuck.get('url')}\nText: {stuck.get('text')}\nScreenshot: {stuck.get('shot')}\nHuman verification required. Use `open {args.account} --site {site} --headed` for human assistance.")
            return EXIT_AUTH
        print(login_line(args.account, signed, config, site))
        if args.cmd == 'open' and getattr(args, 'headed', False):
            print(f'Window opened for human login; afterward use `check {args.account} --site {site}` to verify the login.')
            if not args.no_remote:
                print(share_window(args.account, card, args.note or f"{site} {('verify' if signed else 'sign in')}", args.project, notify=not args.no_notify))
        elif signed and unshare_window(args.account, card):
            print('Window sharing record cleared after successful login.')
        return 0 if signed else EXIT_AUTH
    code = args.code if args.code is not None else sys.stdin.read()
    if started and started.get('site') == site and (not started.get('signed_in')):
        print(login_line(args.account, False, config, site), file=sys.stderr)
    try:
        answer = call_fresh(args.account, card, lock, '/exec', {'code': code, 'cwd': os.getcwd(), 'timeout': args.timeout, 'card': card, 'site': site if args.site else ''}, timeout=args.timeout + 30, headed=headed, site=site)
    except (OSError, ValueError) as exc:
        raise BrowserError(f'Browser took {args.timeout:.0f} seconds without responding ({exc}). If an irreversible action was running, check its outcome before retrying.')
    if answer.get('signed_in') is False:
        print(login_line(args.account, False, config, site), file=sys.stderr)
    if answer.get('out'):
        sys.stdout.write(answer['out'] if answer['out'].endswith('\n') else answer['out'] + '\n')
    print(f"[{answer.get('url', '')}] {answer.get('title', '')}".rstrip())
    if not answer.get('ok'):
        print(answer.get('error', ''), file=sys.stderr)
        return int(answer.get('code') or EXIT_FAILED)
    return 0
def entrypoint() -> int:
    argv = sys.argv[1:]
    if REMOTE_HOST and argv[:1] not in (['_remote'], ['_serve']):
        return forward(argv)
    return main(argv)


if __name__ == '__main__':
    sys.exit(entrypoint())
