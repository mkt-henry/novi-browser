# Benchmarks

Head-to-head runs of the No.VI browser against other agent browsers on two real, logged-in tasks.
Every run stops right before the irreversible step: nothing was posted, no ad was launched and nothing was paid for.

| Date | Comparison | Report |
|---|---|---|
| 2026-10-28 | No.VI browser vs **Ego Lite** | [2026-10-28-novi-vs-ego-lite/report.md](2026-10-28-novi-vs-ego-lite/report.md) |
| 2026-10-27 | No.VI browser vs **Aside** (8 rounds, with the engine fixes made between them) | [2026-10-27-novi-vs-aside/report.md](2026-10-27-novi-vs-aside/report.md) |

The reports are written in Korean. The tables below summarize them.

## All three at a glance: No.VI · Ego Lite · Aside

| Criterion | No.VI browser | Ego Lite | Aside | Better |
|---|---|---|---|---|
| Accuracy (X 7 + LinkedIn 17) | 24/24 | 24/24 | 24/24 | tie |
| X post, up to the Post button | **1:15 · $0.34** | 1:54 · $0.47 | 1:54 · $0.36 | No.VI |
| LinkedIn ad draft | **6:13 · $1.56** | 7:11 · $1.81 | 6:22 · $2.00 | No.VI |
| Both tasks | **7:28 · $1.90** | 9:05 · $2.28 | 8:16 · $2.36 | No.VI |
| Headless | **Headless by default**; a window opens only for login or verification | Needs a visible window; refuses commands when launched headless | The agent drives the visible Aside app; the CLI has no headless option | **No.VI** |
| Separate accounts (separate logins) | **Yes.** One profile per login account (18 now), each started and stopped on its own | Limited. Profiles exist, but an empty one cannot be created, only imported from another browser (1 here). Spaces share one login, so they do not separate accounts | **Yes.** 10 profile slots with separate logins and cookies, but all run inside one browser process, so one hang means restarting every profile | No.VI · Aside |
| Sessions within one account | A tab and variables per card | A tab group per space | A tab group per agent session; sessions can be resumed or steered; shares the user's own windows | tie |
| Ending a session | Closes only that card's tab | Ending the last page of a space reportedly exits the browser | Closes only that session's tabs | No.VI · Aside |
| Memory, 1 page | **450 MB** (694 before the fix below) | 540 MB | 830 MB (browser 501 + resident agent daemon 329) | **No.VI** |
| Memory, 3 sessions | **~1,000 MB** (950 · 1,057; 1,180-1,386 before) | 1,202 MB | 1,283 MB (browser 954 + daemon 329) | **No.VI** |
| Memory, idle | **Shuts down after 5 idle minutes: 0 MB** | 430 MB in the background after closing its window | Always on (it is the user's everyday browser) plus the 329 MB daemon | **No.VI** |
| Site notes / memory | Saved per site, read by the next run | None | Largest store of site memories and site skills | Aside |
| Duplicate irreversible clicks | Recorded and blocked | No such feature found | No such feature found | No.VI |
| Setup | Installed | Install, then a 10-step onboarding | Installed | No.VI · Aside |

- Aside's time and cost come from the 2026-10-27 rounds (LinkedIn round 6, X round 8). In those same rounds No.VI took 5:48 · $1.95 and 2:02 · $0.46.
- Aside memory was measured on a separate, signed-out Aside instance with its own temporary profile folder and a visible window, with the same three pages, 15 seconds after loading ([mem_aside.py](2026-10-28-novi-vs-ego-lite/harness/mem_aside.py)). The everyday Aside runs every profile in one process, so it cannot be measured on its own. The daemon figure is the live `aside-daemon` process. The No.VI figures likewise include its driver processes.
- Aside's browser engine does load pages with `--headless=new` (965 MB for three pages), but the Aside agent and CLI attach to the running app and open tabs in its profile windows, so they cannot use a headless engine.

## Tasks

Both scenarios live in [`scenarios/`](scenarios/). `{M}` is replaced by the round code, for example `A7` or `XE1`.

- **X post up to the Post button** ([x-post.md](scenarios/x-post.md)) — 7 graded items: a two-line text with hashtag and link, one image, the image's ALT text, a second post in the thread, reply setting "Accounts you follow", composer left open, nothing posted.
- **LinkedIn ad draft up to the Review step** ([linkedin-ad.md](scenarios/linkedin-ad.md)) — 17 graded items: objective, location, language, industry, four seniorities, audience expansion off, Audience Network off, single-image format, daily budget, schedule, ad name, intro text, headline, URL, CTA and image. The ad account has no payment method, so a draft cannot be launched even by mistake.

## How a run is scored

- **Same agent on both sides.** Each side is a lean `claude -p` (Claude Opus 5.5) with Bash as its only tool, on the same Claude account and the same scenario text. Only the browser and its rules differ.
- **Same login.** Both browsers were logged into the same X and LinkedIn accounts.
- **Rounds of one scenario run at the same time**, so they see the same site state.
- **Time** is wall clock from start to end. **Cost** is the list-price cost reported by `claude -p`. **Tokens** are counted from the session transcript, deduplicated by message id ([tokens.py](2026-10-28-novi-vs-ego-lite/harness/tokens.py)).
- **Accuracy is graded by a supervisor, not taken from the agent's report.**
  - For X, the supervisor reads the open composer and then discards it.
  - For LinkedIn, the supervisor reads the saved draft back from Campaign Manager's own API ([verify_linkedin.py](2026-10-28-novi-vs-ego-lite/harness/verify_linkedin.py), [check.py](2026-10-28-novi-vs-ego-lite/harness/check.py)).

The runner is [harness/run.sh](2026-10-28-novi-vs-ego-lite/harness/run.sh). The Ego Lite side gets [ego_rules.md](2026-10-28-novi-vs-ego-lite/harness/ego_rules.md) as its appended system prompt. These rules match the No.VI agent's rules: stop before irreversible buttons, never ask questions, leave the page open for the supervisor.

## Results: No.VI vs Ego Lite (2026-10-28)

| | X: No.VI | X: Ego Lite | LinkedIn: No.VI | LinkedIn: Ego Lite |
|---|---|---|---|---|
| Time | **1:15** | 1:54 | **6:13** | 7:11 |
| Cost (list price) | **$0.34** | $0.47 | **$1.56** | $1.81 |
| Tool calls | **13** | 16 | 63 | **49** |
| Cache-write tokens | **26k** | 33k | **78k** | 108k |
| Cache-read tokens | **228k** | 383k | 3.00M | 3.00M |
| Output tokens | **4,203** | 6,575 | **16,798** | 17,404 |
| Accuracy | 7/7 | 7/7 | 17/17 | 17/17 |

Across both tasks, No.VI took 7:28 and $1.90, and Ego Lite took 9:05 and $2.28.

- **Accuracy:** both browsers got every graded item right.
- **Speed and cost:** No.VI used about 18% less time and 17% less money, mostly thanks to the per-site notes it had saved in earlier rounds.
- **Ego Lite's strengths:** its dense page snapshots needed fewer steps on LinkedIn, and its own guide is good enough to finish an unfamiliar site without help.
- **Ego Lite's drawbacks:**
  - It needs a visible window.
  - It has no way to create a new empty profile, so accounts are hard to separate.
  - Each run puts a global "prefer Ego" skill link into every local agent's skill folder.

### Every criterion

| Criterion | No.VI browser | Ego Lite | Better |
|---|---|---|---|
| Accuracy | 24/24 | 24/24 | tie |
| Time, both tasks | **7:28** | 9:05 | No.VI |
| Cost, both tasks | **$1.90** | $2.28 | No.VI |
| Headless | Headless by default; a window opens only for login or verification | Needs a visible window. Launched with `--headless=new`, the CLI refused with "complete the onboarding process first" (Windows, 0.6.1.13, tried twice). Users report headless use on macOS, but it is not an official mode (#445, #446) | **No.VI** |
| Account separation | One profile per login account (18 now), with separate cookies | Profiles exist, but there is no way to create an empty one; only importing from another browser works (#536). One profile was available here | **No.VI** |
| Sessions within one account | A tab and variables per card; the login is shared | A tab group per task space; the login is shared (per-space logins are only requested, #447) | tie |
| Ending a session | Closes only that card's tab | Finishing the last page of a space reportedly exits the whole browser (#446) | No.VI |
| Memory, 1 page | **450 MB** (694 before) | 540 MB | **No.VI** |
| Memory, 3 sessions | **~1,000 MB** (1,386 before) | 1,202 MB | **No.VI** |
| Memory, idle | **Shuts itself down after 5 idle minutes: 0 MB** | Keeps running, 430 MB in the background even after its window is closed | **No.VI** |
| Setup | Already installed | Install, then a 10-step onboarding before the CLI works | No.VI |
| Site notes | Saved per site and read by the next run | None | No.VI |
| Safeguards | Records and blocks duplicate irreversible clicks | Prompt rules only | No.VI |
| Page snapshots | Normal | Dense, so fewer steps on LinkedIn | Ego |

Memory is the private memory of the browser's whole process tree ([mem_tree.py](2026-10-28-novi-vs-ego-lite/harness/mem_tree.py)), measured once with Wikipedia, BBC News and GitHub Explore open in three sessions. Each added session costs about the same on both sides (about 350 MB for No.VI, 330 MB for Ego Lite). The first measurement put No.VI about 15% above Ego Lite; the gap was mostly No.VI's two driver processes (about 160 MB) and its GPU process. The same day No.VI switched headless pages to software compositing (`--disable-gpu-compositing`; windows the user sees are unchanged). On a real account profile, measured twice with the same three pages, one page went from 698 to 450 MB and three sessions from 1,180 · 1,225 to 950 · 1,057 MB; the GPU and utility processes fell from about 290 MB to 80-140 MB. `--disable-gpu` cuts about as much but makes WebGL report a basic software renderer, a common bot signal, so it was not used. With software compositing WebGL still reports the real GPU, and X sign-in checks and screenshots behave as before.

## Results: No.VI vs Aside (2026-10-27)

| Round | Task | No.VI browser | Aside agent | Note |
|---|---|---|---|---|
| 1 | LinkedIn | 9:01 · $2.23 · 17/17 | **6:23 · $2.04** · 17/17 | Aside had a saved memory of this ad account |
| 6 | LinkedIn | **5:48 · $1.95** · 17/17 | 6:22 · $2.00 · 17/17 | after fixing stale element refs and misleading wait advice |
| 7 | X | 2:12 · $0.41 · 7/7 (lean agent) | **1:54 · $0.36** · 7/7 | same tool calls; cost gap came from prompt size |
| 8 | X | 2:02 · $0.46 · 7/7 | 1:54 · $0.36 · 7/7 | card hands the whole task to the No.VI browser agent |

Each round fixed what the previous one exposed: snapshot format, fixed waits, stale element ids, hidden or covered buttons, and agent prompt size. The report lists every round.

## Limits

- Each scenario ran once per side per round. On the X task, the No.VI time varied from 1:55 to 2:47 across rounds.
- Starting with Round 6, the No.VI side benefits from site notes saved by earlier rounds. Ego Lite started each run from nothing.

## 한국어 요약

- **세 브라우저 종합 (No.VI · Ego Lite · Aside):**
  - 정확도는 셋 다 만점이다.
  - 두 일 합계: No.VI 7분 28초·$1.90, Aside 8분 16초·$2.36, Ego Lite 9분 05초·$2.28.
  - 창 없이 돌리기·메모리(돌아갈 때·쉴 때)는 No.VI가 가장 낫다. Aside 에이전트는 화면에 뜬 Aside 창에서만 돈다.
  - 같은 계정 안 세션 나누기는 셋 다 된다. 다른 계정 나누기는 No.VI·Aside가 되고(Aside는 모든 프로필이 한 프로그램 안에서 돈다), Ego Lite는 스페이스가 로그인을 같이 써서 계정 분리가 안 된다.
  - 세션 3개 메모리: No.VI 약 1,000MB, Ego Lite 1,202MB, Aside 1,283MB. 처음엔 No.VI가 1,386MB로 가장 무거웠지만, 창 없는 페이지의 화면 그리기를 CPU로 돌리게 고쳐 가장 가벼워졌다.
  - 사이트 기억은 Aside가 가장 많이 쌓여 있다.
- **Ego Lite 비교 (2026-10-28):**
  - 정확도는 둘 다 만점이다(X 7/7, 링크드인 17/17).
  - 두 일을 합치면 No.VI는 7분 28초·$1.90, Ego Lite는 9분 05초·$2.28이 걸렸다. No.VI가 약 18% 빠르고 17% 쌌다.
  - 창 없이 돌리기·계정 나누기·쉴 때 메모리는 No.VI가 낫다. Ego Lite는 창이 떠야 돌고, 빈 프로필을 새로 만들 수 없으며, 창을 닫아도 뒤에서 430MB를 쓴다. No.VI는 5분 쉬면 스스로 꺼진다.
  - 돌아가는 동안 메모리는 처음엔 Ego Lite가 약 15% 가벼웠지만(No.VI 1,386MB, Ego Lite 1,202MB), No.VI를 고친 뒤 No.VI가 약 1,000MB로 더 가볍다.
  - 같은 계정 안에서 세션을 나누는 단위는 둘이 비슷하다.
  - Ego Lite는 실행할 때마다 다른 AI 에이전트에 "Ego를 먼저 써라" 스킬을 깐다.
- **Aside 비교 (2026-10-27, 8회차):**
  - 1회차에는 Aside가 빨랐다.
  - 회차마다 No.VI 엔진을 고쳤고, 6회차 링크드인에서는 No.VI가 34초 빠르고 비용도 조금 적었다.
  - X는 시간이 비슷하고, 비용은 Aside가 $0.05~0.10 적었다.
- 실제 게시·광고 집행·결제는 한 번도 하지 않았다.
