# Benchmarks

Head-to-head runs of the No.VI browser against other agent browsers on two real, logged-in tasks.
Every run stops right before the irreversible step: nothing was posted, no ad was launched and nothing was paid for.

| Date | Comparison | Report |
|---|---|---|
| 2026-10-28 | No.VI browser vs **Ego Lite** | [2026-10-28-novi-vs-ego-lite/report.md](2026-10-28-novi-vs-ego-lite/report.md) |
| 2026-10-27 | No.VI browser vs **Aside** (8 rounds, with the engine fixes made between them) | [2026-10-27-novi-vs-aside/report.md](2026-10-27-novi-vs-aside/report.md) |

The reports are written in Korean. The tables below summarize them.

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
  - It has one real profile, so accounts are not separated.
  - Each run puts a global "prefer Ego" skill link into every local agent's skill folder.

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

- **Ego Lite 비교 (2026-10-28):**
  - 정확도는 둘 다 만점이다(X 7/7, 링크드인 17/17).
  - 두 일을 합치면 No.VI는 7분 28초·$1.90, Ego Lite는 9분 05초·$2.28이 걸렸다. No.VI가 약 18% 빠르고 17% 쌌다.
  - Ego Lite는 화면에 창이 떠야 돌고, 계정별 프로필이 없다. 실행할 때마다 다른 AI 에이전트에 "Ego를 먼저 써라" 스킬을 깐다.
- **Aside 비교 (2026-10-27, 8회차):**
  - 1회차에는 Aside가 빨랐다.
  - 회차마다 No.VI 엔진을 고쳤고, 6회차 링크드인에서는 No.VI가 34초 빠르고 비용도 조금 적었다.
  - X는 시간이 비슷하고, 비용은 Aside가 $0.05~0.10 적었다.
- 실제 게시·광고 집행·결제는 한 번도 하지 않았다.
