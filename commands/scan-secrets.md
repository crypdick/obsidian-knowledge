---
description: Scan the current vault for leaked secrets on demand. Pass `full` to rescan all eligible files while preserving audit decisions.
---

# Scan vault secrets

Scan the vault containing the working directory, bypassing the Stop-hook cooldown.

1. Run the scanner in manual mode:

   ```bash
   uv run "${CLAUDE_PLUGIN_ROOT}/hooks/scan-vault-secrets.py" --manual
   ```

   If `$ARGUMENTS` contains `full`, append `--full` to rescan all eligible files
   while preserving audit decisions.
2. Show stdout verbatim to the user.
3. If there are findings, summarize the next steps from the scanner's guidance.
   Do not remediate files automatically; the user decides which findings are real.

User arguments: `$ARGUMENTS`
