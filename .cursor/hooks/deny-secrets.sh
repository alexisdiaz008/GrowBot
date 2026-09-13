#!/usr/bin/env bash
# Deny git add/commit of common secret paths (command-string heuristic only).
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
        "agent_message": "deny-secrets.sh failed to parse stdin JSON. Treat as deny."
    }))
    sys.exit(0)

is_git_stage = bool(
    re.search(r"(^|[;&|]\s*)git(\s+-C\s+\S+)?\s+add\b", command)
    or re.search(r"(^|[;&|]\s*)git(\s+-C\s+\S+)?\s+commit\b", command)
)

if not is_git_stage:
    print(json.dumps({"permission": "allow"}))
    sys.exit(0)

# Tokenize roughly; allow .env.example explicitly
# Patterns: .env, .env.*, *.pem, *.p12, id_rsa, credentials.json, *secret*, *service-account*.json
patterns = [
    r"(^|[\s=/])\.env(\.[A-Za-z0-9_.-]+)?(?=$|[\s;|&])",
    r"(^|[\s=/])[^\s]*\.pem(?=$|[\s;|&])",
    r"(^|[\s=/])[^\s]*\.p12(?=$|[\s;|&])",
    r"(^|[\s=/])id_rsa(?=$|[\s;|&])",
    r"(^|[\s=/])credentials\.json(?=$|[\s;|&])",
    r"(^|[\s=/])[^\s]*secret[^\s]*(?=$|[\s;|&])",
    r"(^|[\s=/])[^\s]*service-account[^\s]*\.json(?=$|[\s;|&])",
]

# Strip .env.example mentions so they do not trigger .env match alone:
# If the only .env-like path is .env.example, allow that part.
scrubbed = re.sub(r"(^|[\s=/])\.env\.example(?=$|[\s;|&])", r"\1", command)

hit = None
for pat in patterns:
    m = re.search(pat, scrubbed, re.IGNORECASE)
    if m:
        # Extra: .env.example already removed; remaining .env* is deny
        hit = m.group(0).strip()
        break

if hit:
    print(json.dumps({
        "permission": "deny",
        "user_message": f"Blocked: refusing to stage/commit suspected secret path ({hit.strip()}).",
        "agent_message": "Hook denied git add/commit involving a secret-like path (.env*, *.pem, *.p12, id_rsa, credentials.json, *secret*, *service-account*.json). Stage named non-secret paths only. .env.example is allowed."
    }))
else:
    print(json.dumps({"permission": "allow"}))
PY
)

printf '%s\n' "$result"
exit 0
