#!/bin/bash
# Run one benchmark round with a lean `claude -p` agent.
#
# usage: run.sh <code> novi|ego <novi-account> <novi-site>
#   <code>/task.md must hold the scenario (../../scenarios/*.md with {M}/{m} filled in).
#   CLAUDE_CODE_OAUTH_TOKEN must be set (both sides run on the same Claude account).
#   For the Ego side, EGO_BROWSER must point at ego-browser.exe.
set -u
M=$1; KIND=$2; P=$(cd "$(dirname "$0")" && pwd); cd "$P/$M"
# Make sure the child does not inherit a parent Claude Code session.
for v in CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_CHILD_SESSION CLAUDE_CODE_MESSAGING_SOCKET CLAUDE_CODE_MESSAGING_TOKEN CLAUDE_CODE_SESSION_ID; do unset $v; done
: "${CLAUDE_CODE_OAUTH_TOKEN:?set CLAUDE_CODE_OAUTH_TOKEN}"
export NOVI_CARD_ID=bench-$M
date +%s > start.txt
if [ "$KIND" = novi ]; then
  # No.VI side: the browser agent appends its own rules as the system prompt.
  timeout 3000 novi-browser agent "$3" --site "$4" --timeout 2900 "$(cat task.md)" > out.txt 2> err.txt
else
  # Ego side: same claude -p settings, Ego rules appended, Bash as the only tool.
  CWD=$(cygpath -w "$PWD" 2>/dev/null || pwd)
  RULES=$(sed -e "s#__CWD__#${CWD//\\/\\\\}#" -e "s#__EGO__#${EGO_BROWSER:?set EGO_BROWSER}#" "$P/ego_rules.md")
  timeout 3000 claude -p --output-format json --model claude-opus-5-5 --dangerously-skip-permissions \
    --tools Bash --strict-mcp-config --disable-slash-commands \
    --append-system-prompt "$RULES" "$(cat task.md)" > out.json 2> err.txt
fi
echo $? > exit.txt
date +%s > end.txt
