"""Integration tests for recall-init SessionStart hook."""
import json
import os
import subprocess
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parent.parent
HOOK = PLUGIN_ROOT / "hooks" / "recall-init.py"


def run_hook(stdin_payload: dict, env_overrides: dict | None = None) -> tuple[int, dict]:
    """Run the hook subprocess; return (exit_code, parsed_stdout_json)."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        env=env,
    )
    try:
        out = json.loads(result.stdout) if result.stdout else {}
    except json.JSONDecodeError:
        out = {"_raw_stdout": result.stdout}
    return result.returncode, out


class TestRecallInit:
    def test_emits_primer_when_vault_configured(self, tmp_vault, tmp_path):
        """Vault configured; hook injects systemMessage with primer."""
        config_dir = tmp_path / "obsidian-knowledge"
        config_dir.mkdir()
        (config_dir / "vaults.yaml").write_text(f"vaults:\n  - {tmp_vault}\n")

        env = {
            "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG": str(config_dir / "vaults.yaml"),
        }
        code, out = run_hook({"session_id": "abc"}, env)

        assert code == 0
        assert "systemMessage" in out
        assert "harness" in out["systemMessage"].lower()
        assert "/improve-harness" in out["systemMessage"]

    def test_no_output_when_no_vault_config(self, tmp_path):
        """No vaults.yaml; hook emits nothing."""
        env = {
            "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG": str(tmp_path / "nonexistent.yaml"),
        }
        code, out = run_hook({"session_id": "abc"}, env)

        assert code == 0
        assert out == {}

    def test_errors_on_multi_vault_config(self, tmp_path):
        """vaults.yaml lists 2+ vaults; hook errors with clear message."""
        config_dir = tmp_path / "obsidian-knowledge"
        config_dir.mkdir()
        (config_dir / "vaults.yaml").write_text(
            f"vaults:\n  - {tmp_path}/vault1\n  - {tmp_path}/vault2\n"
        )
        env = {
            "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG": str(config_dir / "vaults.yaml"),
        }
        code, out = run_hook({"session_id": "abc"}, env)
        assert code == 0  # non-blocking warning, not hard error
        assert "multi-vault" in out.get("systemMessage", "").lower() or \
               "not supported" in out.get("systemMessage", "").lower()
