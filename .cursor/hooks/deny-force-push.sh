#!/usr/bin/env bash
# Deny force-push (including --force-with-lease) to main or master.
set -euo pipefail

input=$(cat)

result=$(COMMAND_JSON="$input" python3 - <<'PY'
import json
import os
import re
import sys

raw = os.environ.get("COMMAND_JSON", "")
try:
    data = json.loads(raw) if raw else {}
    command = data.get("command") or ""
except Exception:
    print(json.dumps({
        "permission": "deny",
        "user_message": "Blocked: could not parse shell hook input (fail closed).",
        "agent_message": "deny-force-push.sh failed to parse stdin JSON. Treat as deny."
    }))
    sys.exit(0)

# Force indicators: --force, --force-with-lease, or -f as a discrete flag
force = bool(
    re.search(r"(^|\s)--force(-with-lease)?(\s|=|$)", command)
    or re.search(r"(^|\s)-f(\s|$)", command)
)

# Destination branch main/master: refs/heads/, origin/, or bare trailing arg
targets_protected = bool(
    re.search(r"(^|\s)(refs/heads/)?(main|master)(\s|$)", command)
    or re.search(r"(^|\s)origin/(main|master)(\s|$)", command)
    or re.search(r":(main|master)(\s|$)", command)
)

# Any shell line that looks like git push, including after ; && ||
is_git_push = bool(re.search(r"(^|[;&|]\s*)git(\s+-C\s+\S+)?\s+push\b", command))

if is_git_push and force and targets_protected:
    print(json.dumps({
        "permission": "deny",
        "user_message": "Blocked: force-push to main/master is not allowed.",
        "agent_message": "Hook denied force-push (--force / -f / --force-with-lease) targeting main or master. Push a feature branch or ask a human to update protected branches safely."
    }))
else:
    print(json.dumps({"permission": "allow"}))
PY
)

printf '%s\n' "$result"
exit 0
