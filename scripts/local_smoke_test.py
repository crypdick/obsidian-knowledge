"""Local smoke test for the obsidian-knowledge Hermes provider.

Run from the repo root via:
  OBSIDIAN_VAULT_ROOT=/path/to/vault \
  MEMWEAVE_EMBEDDING_MODEL=ollama/nomic-embed-text \
  MEMWEAVE_EMBEDDING_API_BASE=http://localhost:11434 \
  uv run python scripts/local_smoke_test.py

Tests:
1. Plugin loads in Hermes venv (subprocess bridge)
2. is_available() returns True
3. initialize() works
4. system_prompt_block() returns primer text
5. prefetch() returns vault hits
6. handle_tool_call(vault_search) returns JSON
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Mock the Hermes agent module so we can test standalone
sys.modules["agent"] = MagicMock()
sys.modules["agent.memory_provider"] = MagicMock()
sys.modules["agent.memory_provider"].MemoryProvider = object

# Import the plugin from its installed location (repo root hermes_plugin/)
repo_root = Path(__file__).parents[1]
plugin_path = repo_root / "hermes_plugin" / "__init__.py"

import importlib.util  # noqa: E402  (must follow the agent-module mock above)
spec = importlib.util.spec_from_file_location("hermes_plugin", plugin_path)
mod = importlib.util.module_from_spec(spec)  # type: ignore
spec.loader.exec_module(mod)  # type: ignore

vault_root = os.environ.get("OBSIDIAN_VAULT_ROOT", "")
if not vault_root:
    print("ERROR: OBSIDIAN_VAULT_ROOT not set", file=sys.stderr)
    sys.exit(1)

os.environ["OBSIDIAN_VAULT_ROOT"] = vault_root

p = mod.ObsidianKnowledgeProvider()

print("=== Smoke Test: obsidian-knowledge Hermes provider ===\n")

# Test 1: name
assert p.name == "obsidian-knowledge", f"Bad name: {p.name}"
print("PASS  1. name == 'obsidian-knowledge'")

# Test 2: is_available
avail = p.is_available()
assert avail, "is_available() returned False — check OBSIDIAN_VAULT_ROOT and uv venv"
print("PASS  2. is_available() == True")

# Test 3: initialize
p.initialize(session_id="smoke-test")
print("PASS  3. initialize() completed")

# Test 4: system_prompt_block
block = p.system_prompt_block()
assert "obsidian-knowledge harness" in block, f"Primer missing: {block[:200]}"
assert "wiki" in block.lower(), "wiki not mentioned in primer"
assert "skill_view" in block, "skill_view directive missing"
print(f"PASS  4. system_prompt_block() ok ({len(block)} chars)")
print(f"      Preview: {block[:120]!r}")

# Test 5: prefetch
print("\n--- prefetch('hermes memory provider') ---")
pf = p.prefetch("hermes memory provider")
print(f"prefetch output ({len(pf)} chars):\n{pf[:500]}")
assert "long-term memory" in pf or "Top semantic vault hits" in pf, f"Unexpected: {pf}"
print("\nPASS  5. prefetch() returned valid output")

# Test 6: vault_search tool call
print("\n--- handle_tool_call vault_search ---")
result_json = p.handle_tool_call("vault_search", {"query": "hermes agent memory", "top_k": 3})
result = json.loads(result_json)
print(f"vault_search result: {json.dumps(result, indent=2)[:400]}")
assert isinstance(result, list), f"Expected list, got {type(result)}"
if result:
    assert "score" in result[0], "Missing score in hit"
    assert "path" in result[0], "Missing path in hit"
print(f"\nPASS  6. vault_search returned {len(result)} hits")

print("\n=== ALL TESTS PASSED ===")
