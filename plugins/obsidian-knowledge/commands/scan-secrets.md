---
description: Scan the current vault for leaked secrets on demand. Pass `full` to rebuild the baseline from scratch.
---

# Scan Vault Secrets

Run the secrets scanner against the vault containing the current working directory. Bypasses the Stop-hook cooldown so it always executes.

The scanner is the same one wired up as a Stop hook (`hooks/scan-vault-secrets.py`); this command runs it in `--manual` mode so findings print to stdout instead of being injected as a Stop block.

## Steps

1. Run the scanner. If `$ARGUMENTS` contains the word `full`, append `--full` to delete the baseline first and force a full rescan; otherwise run an incremental scan.

   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/hooks/scan-vault-secrets.py" --manual
   ```

   With `full`:

   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/hooks/scan-vault-secrets.py" --manual --full
   ```

2. Surface the script's stdout verbatim to the user.

3. If findings appeared, briefly summarize what should happen next (audit, redact, or allowlist) using the inline guidance the script already prints. Do not start remediating files automatically — the user decides which findings are real.

User arguments: $ARGUMENTS
