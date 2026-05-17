---
name: obsidian-knowledge
description: Read, search, and create notes in the Obsidian vault/wiki memory store.
---

# Obsidian Vault / Wiki Memory

## Telegram Topic Behavior

When this skill is auto-loaded in the `obsidian` Telegram topic, treat that topic as the place for using the `obsidian-knowledge` skill. Read this `SKILL.md` and use it as the operating guide for the session.

If Ricardo refers to prior vault context that is not present in the current Telegram thread, search the vault first instead of guessing. Use `obsidian-knowledge search "<query>"` for semantic lookup, then read the relevant notes before answering or editing.


**Primary memory store:** `/Users/ricardo/Documents/obsidian/wiki/`

Use the Obsidian wiki as the durable memory/source-of-truth for non-trivial context, project knowledge, and conversation outcomes. Use `obsidian-knowledge search "<query>"` to find relevant notes.

**Location:** Set via `OBSIDIAN_VAULT_PATH` environment variable (e.g. in `~/.hermes/.env`).

If unset, defaults to `~/Documents/Obsidian Vault`.

Note: Vault paths may contain spaces - always quote them.

## Pitfall: macOS TCC silently returns zero results

On macOS, `~/Documents` is TCC-protected. If the calling process (Terminal, the Hermes agent's parent python, etc.) hasn't been granted Documents/Full Disk Access, `find` and `grep -r` return **0 results with no error** — they look like a clean miss. Permissions can also be transient (e.g. just-granted, or revoked by a recent OS update).

**Always sanity-check the vault is actually readable before trusting a "no hits" result.** If a search returns nothing for a term the user insists is there, do not give up — verify access first:

```bash
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"
# Probe: can we even list the vault root?
ls "$VAULT" 2>&1 | head -3
# If you see "Operation not permitted", it's TCC, not a missing note.
# Also confirm the search is finding *any* markdown:
find "$VAULT" -name "*.md" -type f | wc -l   # should be > 0
```

If TCC is blocking access, grant the running binary (Terminal, iTerm, or the parent python — check with `ps -o comm= -p $PPID`) Full Disk Access in System Settings → Privacy & Security, then retry. A simple retry sometimes works on its own — TCC permission state can be transient.

## Read a note

```bash
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"
cat "$VAULT/Note Name.md"
```

## List notes

```bash
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"

# All notes
find "$VAULT" -name "*.md" -type f

# In a specific folder
ls "$VAULT/Subfolder/"
```

## Search

```bash
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"

# By filename
find "$VAULT" -name "*.md" -iname "*keyword*"

# By content
grep -rli "keyword" "$VAULT" --include="*.md"
```

## Create a note

```bash
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"
cat > "$VAULT/New Note.md" << 'ENDNOTE'
# Title

Content here.
ENDNOTE
```

## Append to a note

```bash
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"
echo "
New content here." >> "$VAULT/Existing Note.md"
```

## Wikilinks

Obsidian links notes with `[[Note Name]]` syntax. When creating notes, use these to link related content.

## Pitfall: empty search results on macOS = check TCC permissions first

If `find`/`grep` against the vault returns 0 results for a term the user insists is there, **do not conclude "not found" yet**. On macOS, the parent shell may lack Full Disk Access / Documents folder permission under TCC, and `find` silently returns nothing instead of erroring loudly.

Diagnostic:

```bash
ls "$OBSIDIAN_VAULT_PATH/" 2>&1 | head -3
# "Operation not permitted" → TCC is blocking the shell's parent process
# (Terminal.app, Hermes python, etc.) from reading ~/Documents
```

Notes:
- Permission can appear granted in System Settings but still be cached as denied for an already-running process. A simple retry of the same `ls`/`find` often works moments later, or after the parent process restarts.
- The actual binary needing the grant is the parent in the process tree (e.g. `/Users/<user>/.hermes/hermes-agent/venv/bin/python` for Hermes, not `bash`). Check with: `ps -o pid,ppid,comm -p $$` and walk up to PID 1.
- If `ls` works but a recursive `find`/`grep` returns nothing for a known-present term, **retry once** before giving up — TCC state can flip mid-session.
- Vault paths often contain spaces and lowercase variants (`~/Documents/obsidian` vs `~/Documents/Obsidian Vault`); always honor `$OBSIDIAN_VAULT_PATH` from `~/.hermes/.env`.
