---
name: doc-code-coupling
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.(py|md|toml|yaml|yml)$
action: warn
---

When code and documentation share a concrete value, leave a comment at the code
site pointing to the document. This applies to environment variable allowlists,
blocked patterns, mount tables, configuration keys, and user-facing names.

```python
# NOTE: Update docs/architecture/security.md § Credential Handling if you change this list.
allowed_vars = ["PATH", "HOME", "USER"]
```

Add a `NOTE:` naming the document and section when introducing a documented
value. When changing a value that already has a `NOTE:`, read the referenced
document and update both in the same change. When editing docs, check whether
values repeated from code need a corresponding comment.

Apply this where code and prose describe the same thing and drift would mislead
readers. Small projects without published docs can skip it.
