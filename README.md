# novi-browser

**No.VI agent browser** gives any AI coding agent a persistent browser without keeping one running all day. Use it from Claude Code, Codex, Cursor, a terminal, or any MCP client on Windows, macOS, and Linux.

Each profile (`No1`, `No2`, …) belongs to **one login identity** and holds the sites that identity uses. A browser starts when a command needs it, runs headless by default, and saves its login before closing after five idle minutes. A headed window waits thirty minutes. This keeps idle RAM use low while preserving logins, including session cookies that Chromium would otherwise discard on exit.

Several agents can share a profile: each session gets its own tab and Python variables, while a single detached worker serializes commands. Different identities use separate profile directories. Optional Patchright on installed Google Chrome helps with sites that reject automated browsers; it does not guarantee access. ARIA snapshots with short refs such as `e12` make page reading cheap in tokens, and an intent/done ledger guards against repeating an irreversible action after a lost response.

## Install

Python 3.10 or newer:

```sh
pip install git+https://github.com/mkt-henry/novi-browser
playwright install chromium
novi-browser list
```

For development, clone this repository and run `pip install -e .`. On Linux, `playwright install --with-deps chromium` can also install required system libraries (administrator privileges may be needed).

Optional integrations:

```sh
pip install 'novi-browser[stealth] @ git+https://github.com/mkt-henry/novi-browser'
pip install keyring
```

The stealth extra requires Google Chrome installed on the machine. The worker selects Patchright with installed Chrome when both are available; otherwise it uses Playwright Chromium. Set `NOVI_BROWSER_ENGINE=chromium` to force Chromium. The installed Chrome keeps the machine's locale and time zone: overriding them through emulation can affect site verification.

## Quick start

```sh
novi-browser list
novi-browser add No1 --site example.com --check https://example.com --signed-out /login
novi-browser exec No1 --site example.com -c "goto('https://example.com'); snap()"
novi-browser close No1
```

The example is a public page; the `/login` marker is absent, so its login check passes. For a real account, use a page that requires login and markers that reliably distinguish signed-in and signed-out states:

```sh
novi-browser add No2 --site Work --check https://work.example/account --signed-out /login --user user@example.com
novi-browser open No2 --site Work --headed
# Sign in in the visible window, then:
novi-browser check No2 --site Work
novi-browser exec No2 --site Work -c "snap(interactive=True)"
```

`open --headed` shows a local window for human logins and verification. A failed login check returns status 77 but leaves the window available. Do not bypass captchas or device verification: let the human finish, then check again. `--window` on `add` makes a site always use a real window. Reopening a shared headless browser as headed waits until other recently active sessions are no longer using it.

## CLI reference

`python -m novi_browser` is equivalent to `novi-browser`. Each command supports `--help`.

| Command | Purpose |
| --- | --- |
| `list` | Profiles, identities, sites, last login checks, active sessions and available RAM |
| `add No1 --site X --check URL --signed-out MARKER` | Add or update a site; `--signed-out` is repeatable |
| `open No1 --site X [--headed] [--note TEXT]` | Start on demand and check login; optionally show a window |
| `check No1 --site X` | Recheck login; may attempt a saved login once |
| `login No1 --site X` | Attempt the saved login method once |
| `exec No1 --site X [-c CODE] [--timeout 120]` | Execute Playwright Python; omit `-c` to read stdin |
| `agent No1 --site X "task and completion criteria"` | Delegate the browser task to `claude -p` |
| `close No1` / `close --all` | Save login and close the profile(s) |
| `close --session ID` | Release only that session's tabs; close the browser if no callers remain |
| `ledger No1` | Show the latest state of each irreversible action |
| `resolve No1 --key KEY --state done\|failed [--url URL]` | Resolve a previously inspected uncertain outcome |
| `remember No1 --site X "note"` | Append site know-how locally |
| `memory No1 --site X` | Read local site notes |
| `memory --search QUERY` / `memory --read KEY` | Search notes or read a complete note |
| `stats [--days 7]` | Summarize local worker runs and memory use |

`add` also accepts `--signed-in-text`, `--identity`, `--label`, `--home`, `--note`, `--secret`, `--window`, and a saved login method: `--login-url`, `--user-field`, `--password-field`, `--submit`. Both login URL and password field are required for a saved method. A refused or interrupted automatic login is not retried automatically until a successful login check clears it. A later explicit `login` can retry after a cooldown; inspect the page and correct credentials first.

One profile cannot contain different login users. Add a second identity in `No2`, even for the same website. Profile names are `No` followed by digits or a lowercase slug. The CLI normalizes `no001` to `No1`. Numbered names are recommended.

Exit codes: 0 success, 1 operation/code failure, 2 invalid arguments, 69 unavailable dependency or remote host, 73 profile busy during headed takeover, 75 insufficient memory or too many workers, 77 login expired, 78 unknown profile/site. Starts allow at most four workers and reserve roughly 3 GB of free RAM plus a 500 MB browser budget.

## Exec helpers

Variables survive across `exec` calls within the same session. The last expression is printed, as in a Python REPL. `page` and `ctx` are Playwright objects. Code runs with the caller's full local privileges.

| Helper | Use |
| --- | --- |
| `goto(url)` | Navigate and wait for DOM content |
| `text(selector='body', limit=3000)` | Read visible text |
| `snap()` | ARIA tree with refs; returned string has `.tree` and `.diff` |
| `snap(interactive=True)` | Compact view of actionable elements and context |
| `snap(selector='[role="dialog"]')` / `snap(ref='e12')` | Visible subtree; `limit=` controls output length |
| `click('e12')`, `fill('e12', value)`, `press('Enter')`, `select('e12', value)` | Act on a ref and return changed lines |
| `press('Enter', target='e12')` | Press in a specific element |
| `diff()` | Read changes since the last snapshot |
| `ref('e12')` | Get the locator for an observed ref |
| `shot('result.png', full_page=False)` | Save a screenshot in the caller's working directory |
| `pages()`, `use(index)` | Inspect tabs or select one; use another session's tabs only by agreement |
| `sites()`, `check(site)`, `login(site)` | Registered sites and authentication helpers |
| `secret(name)` | Resolve a local secret without printing it |
| `human_click(locator)`, `human_type(text)` | Move the mouse and type key by key |
| `fingerprint(*parts)` | Stable action key ignoring case and repeated whitespace |
| `intent(key, what='', site=None)` | Record an authorized action before its irreversible click; requires verified site login |
| `done(key, url='')`, `failed(key, why='')` | Record a confirmed outcome |

Read `snap()` before choosing a ref; never guess it. Stale refs and hidden or covered elements fail promptly with changes to inspect. Action helpers wait for the page to settle. Fixed sleeps and `page.wait_for_timeout` are shortened when consecutive snapshots agree. For a slow upload, inspect another snapshot instead of waiting on an invisible selector. Upload with `page.set_input_files(...)`. Patchright evaluates scripts in an isolated world: DOM access works, but the site's JavaScript globals may not be visible.

For an explicitly authorized submission:

```python
key = fingerprint('No1', 'message contents', 'one specific action')
intent(key, 'Submit the approved message', site='Work')
click('e12')  # Replace with the current ref observed in snap().
# Inspect confirmation, then:
done(key, page.url)
```

An unfinished `intent` means **unknown outcome**, and an existing `done` also blocks reuse of the key. Inspect the site before resolving an unknown action. Mark it failed only after establishing it did not happen. The ledger is an explicit agent protocol, not an interception layer: direct Playwright calls can bypass it, so agents must follow the guide.

## MCP

The stdio MCP server uses only the Python standard library; browser dependencies load only when needed. It exposes `list_profiles`, `add_site`, `open`, `exec`, `snap`, `close`, `remember`, and `memory`, using the same CLI functions and workers. Browser tools accept `profile` and optional `site`; `exec` also takes `code` and `timeout`. `snap` takes optional `selector` and `interactive`.

```sh
claude mcp add novi-browser -- novi-browser-mcp
```

Generic client configuration (use the full executable path if it is outside the client's PATH):

```json
{
  "mcpServers": {
    "novi-browser": {
      "command": "novi-browser-mcp",
      "args": [],
      "env": {
        "NOVI_BROWSER_SESSION": "research-session"
      }
    }
  }
}
```

Choose a different session value for independent callers. MCP sends newline-delimited JSON-RPC 2.0 over stdin/stdout; stdout contains protocol messages only. No separate MCP package or network listener is required for the MCP transport.

## Agent guides and delegation

Copy `skills/novi-browser/` into `~/.claude/skills/novi-browser/` for Claude Code. [AGENTS.md](AGENTS.md) provides the same operating guide for Codex and other coding agents; copy or reference it in the agent's project instructions.

`agent` requires an installed and authenticated Claude Code CLI. Its default model is the `sonnet` alias; override with `--model MODEL` or `NOVI_BROWSER_AGENT_MODEL`. It runs a lean `claude -p` with only the Bash tool, no inherited MCP configuration or slash commands, and a shared browser session. It uses `--dangerously-skip-permissions`, so invoke delegation only for trusted tasks in a suitable working directory. It reports a session ID for `--resume`. The child instructions require stopping before unapproved irreversible actions and human verification. Other agents can use `exec` or MCP directly without Claude Code.

## Local data and secrets

Default data home: `~/.novi-browser/`. Set `NOVI_BROWSER_HOME` before launching commands or the MCP server to change it.

```text
~/.novi-browser/
  No1/
    account.json       # Site settings and login identity (no secret values)
    profile/           # Persistent Chromium data
    session.json       # Saved cookies, including session-only cookies
    state.json         # Last authentication checks
    ledger.jsonl       # Action intent/outcome history
    lock.json          # Live worker port, PID and per-start token
  memory.jsonl         # Append-only site notes shared by hostname/site name
  memory-shown.json    # Which sessions have read each site's notes
  runs.jsonl           # Local run statistics
  worker.log          # Worker diagnostics
  secrets.json        # Optional plaintext secret fallback
```

`remember` appends JSON lines. `memory --site` reads them, and the first `open` or `exec` of a site in a session prints its notes. Notes contain shared site know-how; never put passwords or identity-specific confidential information in them.

`secret('work-password')` resolves in this order:

1. `NOVI_BROWSER_SECRET_WORK_PASSWORD` (uppercase name; each non-alphanumeric character becomes `_`). An explicitly empty environment value also takes precedence.
2. OS keyring, if `keyring` is importable: service `novi-browser`, username `work-password`.
3. `secrets.json` in the data home, as a JSON object: `{"work-password": "your-value"}`.

The local file is set to mode 600 where supported. On Windows, restrict access through the data home's ACL. Optional keyring setup: `python -m keyring set novi-browser work-password`. Set secrets before starting the worker; restart the worker after changing environment secrets because it retains its startup environment. Never print secrets in exec output or commit the data home.

## Environment variables and optional hooks

| Variable | Meaning |
| --- | --- |
| `NOVI_BROWSER_HOME` | Data directory; default `~/.novi-browser` |
| `NOVI_BROWSER_SESSION` | Stable session/tab identity; default parent process ID plus creation time |
| `NOVI_CARD_ID` | Legacy alias for session identity; used only when the new variable is absent |
| `NOVI_BROWSER_SECRET_<NAME>` | Environment secret (normalization described above) |
| `NOVI_BROWSER_ENGINE` | `chromium` forces Playwright instead of auto-selecting Patchright/Chrome |
| `NOVI_BROWSER_AGENT_MODEL` | Model for `agent`, default `sonnet` |
| `NOVI_BROWSER_REMOTE` | Optional SSH target `user@host`; unset means run locally on every OS |
| `NOVI_BROWSER_SHARE_CMD` | Optional executable and argument template for sharing a headed window |

Set a stable explicit session ID when a launcher creates a new parent process for each call. `--session ID` overrides it for open/exec/check/login/close/remember. `--card` remains a command-line compatibility alias.

`NOVI_BROWSER_SHARE_CMD` is invoked after `open --headed` with these placeholders: `{hwnd}` (Windows handle or `0` elsewhere), `{title}` (Windows window title or profile name), `{account}`, `{session}`, `{note}`. For example:

```sh
export NOVI_BROWSER_SHARE_CMD='my-window-share --handle "{hwnd}" --title "{title}" --profile "{account}" --session "{session}" --note "{note}"'
```

The template is split into arguments before substitution and executed **without a shell**. Use an executable or an explicit interpreter for a script; shell operators are not interpreted. `open --no-remote` skips this sharing hook (it does not disable SSH relay). Without a hook, headed mode just shows the local window. Hook lifetime/unsharing is managed by your integration; the browser clears its local sharing record on close or successful login. A successful share extends the headed idle allowance to one hour. Native window-handle lookup is Windows-only and guarded on other platforms.

To run on another machine, install this package and its browser there, configure SSH authentication, and set:

```sh
export NOVI_BROWSER_REMOTE=user@host
novi-browser exec No1 --site Work --put document.pdf -c "page.set_input_files('input[type=file]', 'document.pdf'); snap()"
```

The relay invokes `novi-browser _remote` on the target (the command must be on its SSH PATH). It forwards command arguments, stdin and explicit `--put` files as JSON over SSH. The remote machine uses its own data home and secrets. Newly created or changed top-level files up to 20 MB each, including screenshots, return to the current local directory. Use filenames rather than absolute local paths in remote code. Returned files replace same-named local files. Remote work folders are isolated by session under the remote data home. Profiles and logins remain on the remote machine. With the variable unset, no SSH connection is made; `--put` is a relay-only option.

## Security and operation

Profiles contain live logins and cookies. Keep the data home private, outside source control and shared folders; restrict Windows ACLs or POSIX directory permissions. POSIX JSON files use mode 600 and newly created data directories use mode 700. Do not expose the worker port or share its token. The worker binds only to `127.0.0.1`, uses a random per-start token, and holds an exclusive per-profile lock. Run it as your own user, with trusted callers. Exec and MCP exec deliberately run arbitrary Python; neither is a sandbox.

Nothing is sent to an application server or telemetry service by this package. Site visits contact the requested websites. SSH relay, window sharing, and Claude delegation run only when configured or invoked; those integrations may transmit task data to their respective services. Logs, notes, screenshots, ledger entries and cookies can contain sensitive data. No private service, vault or remote-control backend is required.

Cookie restoration cannot revive server-expired logins. Use headed mode for human assistance. Closing a profile affects all callers sharing it; release only your session when others are active. Variables live in the worker's memory and disappear on idle close, while disk login data persists.

## Benchmarks

Side-by-side runs against Ego Lite and Aside on a real X post and a LinkedIn ad draft (stopped before posting or launching), with time, tokens, cost and supervisor-graded accuracy: [benchmarks/](benchmarks/).

## Tests

No browser installation is needed for the unit suite:

```sh
python -m unittest discover -s tests
```

On Windows, set `$env:PYTHONUTF8=1` in PowerShell first. GitHub Actions runs the suite on Ubuntu and Windows with Python 3.10 and 3.14 after `pip install -e .`, without downloading browsers.

## 한국어 안내

No.VI 브라우저는 로그인 계정마다 전용 프로필을 만들고, 필요할 때만 브라우저를 실행합니다. 기본은 헤드리스이며 유휴 시간이 지나면 쿠키를 저장하고 종료합니다. 여러 에이전트가 같은 프로필을 쓰더라도 세션마다 탭과 변수가 나뉩니다.

`novi-browser list`로 프로필을 확인하고, `add`로 사이트를 등록한 뒤 `exec` 또는 MCP로 사용하세요. `snap()`에서 읽은 참조 번호로 클릭하고, 게시·결제 등 되돌릴 수 없는 작업은 승인된 범위 안에서 `intent()`와 `done()`으로 기록하세요. 로그인이나 사람의 확인이 필요하면 `open --headed`로 창을 띄우세요. 로그인 데이터와 비밀값은 로컬 데이터 폴더에 보관되므로 접근 권한을 제한하고 공개 저장소에 올리지 마세요.

Ego Lite·Aside와 같은 일(X 게시 직전·링크드인 광고 초안)을 시켜 시간·토큰·비용·정확도를 비교한 결과는 [benchmarks/](benchmarks/)에 있습니다.
