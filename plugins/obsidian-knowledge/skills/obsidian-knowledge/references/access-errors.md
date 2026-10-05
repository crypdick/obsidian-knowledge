# Access errors

Read this guide only when vault reads, writes, or search encounter permission
or connection failures.

- **Search:** Semantic ranking needs network access to Ollama, even on localhost.
  `EPERM` or `EACCES` indicates blocked access, not a stopped service. Check
  service health from a process with network access before restarting it.
- **Writes:** Papercut logging needs write access to the log directory and lock file.
- **macOS:** For `Operation not permitted` on note reads, grant the parent process
  Documents or Full Disk Access in **System Settings > Privacy & Security**,
  then restart it.

Use the host's approved permission mechanism when needed. If access remains
unavailable, report the limitation once and continue with available tools or
keyword ranking. Do not retry with unchanged permissions or log a papercut's
own failure.
