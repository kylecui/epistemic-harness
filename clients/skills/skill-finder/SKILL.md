---
name: skill-finder
description: Fast local index of installed skills. List all or filter by keyword across user/project skill directories. Manually invoked via /skill:skill-finder [keyword].
disable-model-invocation: true
---

# skill-finder — Tier 0 reflexive lookup

This is a pure index lookup. Do NOT analyze, recommend, summarize, or add opinions.
Run EXACTLY ONE command and return its output verbatim in a code block. Done.

- User gave a keyword → put it in `KW="..."` (first line).
- No keyword → keep `KW=""` (lists everything, names only).

```bash
KW=""  # <-- replace with the user's keyword if provided
PY=$(command -v python3 || command -v python); "$PY" - "$KW" <<'PYEOF'
import re, sys
from pathlib import Path
kw = (sys.argv[1] if len(sys.argv) > 1 else "").casefold()
cwd = Path.cwd()
roots = [(Path.home()/'.agents'/'skills', 'user-shared'),
         (Path.home()/'.pi'/'agent'/'skills', 'pi-user'),
         (cwd/'.agents'/'skills', 'project'),
         (cwd/'.pi'/'skills', 'project')]
def desc_of(fm):
    lines = fm.splitlines()
    for i, l in enumerate(lines):
        if l.startswith('description:'):
            v = l.split(':', 1)[1].strip()
            if not v or set(v) <= set('>|-+'):
                buf = []
                for j in range(i+1, len(lines)):
                    if lines[j].startswith((' ', '\t')) and lines[j].strip():
                        buf.append(lines[j].strip())
                    else:
                        break
                return ' '.join(buf)[:200]
            return v.strip('"\'')[:200]
    return ''
seen, rows = {}, []
for root, tag in roots:
    if not root.is_dir():
        continue
    for md in sorted(root.glob('*/SKILL.md')):
        name = md.parent.name
        if name in seen:
            continue
        m = re.match(r'^---\n(.*?)\n---', md.read_text(encoding='utf-8', errors='ignore'), re.S)
        d = desc_of(m.group(1)) if m else ''
        seen[name] = (tag, d, name)
for tag, d, name in seen.values():
    if kw and kw not in name.casefold() and kw not in d.casefold():
        continue
    rows.append((name, tag, d))
if not kw:
    for name, tag, d in sorted(rows):
        print(f"{name:36s} [{tag}]")
    print(f"\n{len(rows)} skills. Re-run with a keyword to see descriptions.")
else:
    for name, tag, d in sorted(rows):
        print(f"{name} [{tag}]\n    {d}\n")
    print(f"{len(rows)} match(es) for '{kw}'.")
PYEOF
```

Rules (hard):
1. One command. No follow-up commands, no directory exploration.
2. Output verbatim — no commentary before or after beyond a single line stating the keyword.
3. If zero matches, say so in one line and stop. Do not suggest alternatives.
