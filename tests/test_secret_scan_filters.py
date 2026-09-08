"""End-to-end false-positive and leak-retention tests using synthetic values."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from detect_secrets.core.potential_secret import PotentialSecret
from detect_secrets.core.secrets_collection import SecretsCollection
from detect_secrets.settings import transient_settings

ROOT = Path(__file__).parent.parent
DIGEST = hashlib.sha256(b"synthetic metadata fixture").hexdigest()
OPAQUE = base64.b64encode(hashlib.sha256(b"synthetic credential fixture").digest()).decode()


@pytest.fixture(scope="module")
def scanner():
    sys.path.insert(0, str(ROOT / "hooks"))
    spec = importlib.util.spec_from_file_location(
        "secret_scan_filters_hook", ROOT / "hooks/scan-vault-secrets.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("filename", "text"),
    [
        ("note.md", 'api_key="your-api-key"'),  # pragma: allowlist secret
        (
            "note.md",
            'secret="generate-a-strong-secret-here"',  # pragma: allowlist secret
        ),
        (
            "note.md",
            'api_key="comfyui-xxxxxxxxxxxx"',  # pragma: allowlist secret
        ),
        ("note.md", 'api_key="sk-..."'),  # pragma: allowlist secret
        (
            "note.md",
            'AGENTMAIL_API_KEY: "am_your_key_here"',  # pragma: allowlist secret
        ),
        ("note.md", "https://<username>:<token>@github.com/<owner>/<repo>.git"),
        ("manifest.json", f'{{"source_skill_md_sha256": "{DIGEST}"}}'),
        ("export.json", f'{{"list_id": "{OPAQUE}"}}'),
        ("note.md", 'repo_id = "example-org/Synthetic-Model-482B-Quantized-GGUF"'),
        ("image.xmp", f'darktable:blendop_params="{OPAQUE}"'),
        ("image.xmp", f'darktable:blendop_params="{OPAQUE}"/>'),
        (
            "image.xmp",
            f'<x:xmpmeta xmlns:x="adobe:ns:meta/">\n<node\n darktable:blendop_params="{OPAQUE}"/>\n</x:xmpmeta>',
        ),
        (
            "config.py",
            'PASSWORD_OVERRIDE_ENV = "CALDAV_PASSWORD"',  # pragma: allowlist secret
        ),
        (
            "config.py",
            'ENV_API_KEY = "COMFY_CLOUD_API_KEY"',  # pragma: allowlist secret
        ),
        (
            "note.md",
            'The UI dump contained SystemUI/keyguard nodes with `password="false"`.',  # pragma: allowlist secret
        ),
        (
            "note.md",
            'SystemUI/keyguard nodes were present.\nThe UI dump had `password="false"`.',  # pragma: allowlist secret
        ),
    ],
)
def test_noncredentials_are_filtered(tmp_path, scanner, filename, text):
    path = tmp_path / filename
    path.write_text(text + "\n")
    with transient_settings(scanner.DETECT_SECRETS_CFG):
        collection = SecretsCollection()
        collection.scan_file(str(path))
    assert not collection.data


@pytest.mark.parametrize(
    ("filename", "text"),
    [
        ("note.md", f'token = "{OPAQUE}"'),
        ("note.md", f'password = "{OPAQUE}"'),
        (
            "config.py",
            'api_key = "ACTUAL_DEPLOYMENT_KEY"',  # pragma: allowlist secret
        ),
        ("note.md", 'password = "false"'),  # pragma: allowlist secret
        ("example.md", 'password = "mypassword"'),  # pragma: allowlist secret
        (
            "test_config.py",
            'password = "synthetic-weak-password"',  # pragma: allowlist secret
        ),
        ("export.json", f'{{"list_id": "{OPAQUE}", "password": "synthetic-weak-password"}}'),
        ("manifest.json", f'{{"sha256": "{DIGEST}", "token": "{OPAQUE}"}}'),
        (
            "note.md",
            f'api_key="your-api-key"; token="{OPAQUE}"',  # pragma: allowlist secret
        ),
        ("note.md", f'api_key="your-{OPAQUE}"'),  # pragma: allowlist secret
        (
            "image.xmp",
            f'darktable:blendop_params="{OPAQUE}" password="synthetic-weak-password"',  # pragma: allowlist secret
        ),
        ("export.json", '{"list_id": "' + "AKIA" + "Z" * 16 + '"}'),
        ("note.md", "-----BEGIN " + "RSA PRIVATE KEY-----"),
    ],
)
def test_credentials_still_alert(tmp_path, scanner, filename, text):
    path = tmp_path / filename
    path.write_text(text + "\n")
    with transient_settings(scanner.DETECT_SECRETS_CFG):
        collection = SecretsCollection()
        collection.scan_file(str(path))
    assert collection.data


def test_mime_only_filters_image_payload_and_invalidates_cache(tmp_path, scanner):
    path = tmp_path / "export.mht"
    # Synthetic regex match; never a real issued token.
    token = "AKC" + "Z" * 73
    body = (
        'MIME-Version: 1.0\nContent-Type: multipart/related; boundary="part"\n\n'
        "--part\nContent-Type: image/jpeg\nContent-Transfer-Encoding: base64\n\n" + token + "\n--part--\n"
    )
    path.write_text(body)
    with transient_settings(scanner.DETECT_SECRETS_CFG):
        collection = SecretsCollection()
        collection.scan_file(str(path))
        assert not collection.data
        path.write_text(body.replace("image/jpeg", "text/plain"))
        collection.scan_file(str(path))
        assert collection.data


def test_known_leaked_literal_overrides_placeholder_filter(tmp_path, scanner):
    (tmp_path / "example.md").write_text('api_key="your-api-key"\n')  # pragma: allowlist secret
    count, files, _ = scanner.scan_known_leaked(str(tmp_path), ["example.md"], ["your-api-key"])
    assert (count, files) == (1, 1)


@pytest.mark.parametrize("full", [False, True])
def test_policy_change_rescans_unchanged_files_and_preserves_audits(tmp_path, scanner, monkeypatch, full):
    note = tmp_path / "note.md"
    note.write_text(
        'password="synthetic-weak-password"\napi_key="your-api-key"\n'  # pragma: allowlist secret
    )
    baseline = tmp_path / ".secrets.baseline"
    scanner.run_scan(baseline, str(tmp_path), ["note.md"], ["note.md"])
    payload = json.loads(baseline.read_text())
    payload["results"]["note.md"][0]["is_secret"] = False
    payload["results"]["note.md"].append(
        PotentialSecret("Secret Keyword", "note.md", "your-api-key", line_number=2).json()
    )
    if not full:
        payload.pop("vault_scan_policy")
    baseline.write_text(json.dumps(payload))
    assert scanner.scan_policy_is_current(baseline) is full
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scanner, "is_in_vault", lambda _: True)
    monkeypatch.setattr(scanner, "load_vault_roots", lambda: [str(tmp_path)])
    monkeypatch.setattr(scanner, "find_containing_vault", lambda *_: str(tmp_path))
    with pytest.raises(SystemExit) as stopped:
        scanner.main(["--manual", "--full"] if full else ["--manual"])
    assert stopped.value.code == 0
    assert scanner.scan_policy_is_current(baseline)
    findings = json.loads(baseline.read_text())["results"]["note.md"]
    assert len(findings) == 1
    assert findings[0]["is_secret"] is False


@pytest.mark.parametrize("outside", ["", " ", "\n"])
def test_inline_image_does_not_hide_adjacent_credentials(tmp_path, scanner, outside):
    token = "AKIA" + "Z" * 16
    header = base64.b64encode(b"\x89PNG\r\n\x1a\n" + bytes(16)).decode()
    text = f"![](data:image/png;base64,{header}{token})"
    if outside:
        text += f"{outside}AWS_ACCESS_KEY_ID={token}"
    path = tmp_path / "image-note.md"
    path.write_text(text)
    with transient_settings(scanner.DETECT_SECRETS_CFG):
        collection = SecretsCollection()
        collection.scan_file(str(path))
    assert bool(collection.data) is bool(outside)


def test_fake_image_data_uri_still_alerts(tmp_path, scanner):
    token = "AKIA" + "Z" * 16
    path = tmp_path / "note.md"
    path.write_text(f"![](data:image/png;base64,{token})")
    with transient_settings(scanner.DETECT_SECRETS_CFG):
        collection = SecretsCollection()
        collection.scan_file(str(path))
    assert collection.data


def test_incremental_scan_retains_unscanned_audit_records(tmp_path, scanner):
    for name in ("first.md", "second.md"):
        (tmp_path / name).write_text('password="synthetic-weak-password"\n')  # pragma: allowlist secret
    baseline = tmp_path / ".secrets.baseline"
    scanner.run_scan(baseline, str(tmp_path), ["first.md", "second.md"], ["first.md", "second.md"])
    payload = json.loads(baseline.read_text())
    payload["results"]["second.md"][0]["is_secret"] = False
    baseline.write_text(json.dumps(payload))
    scanner.run_scan(baseline, str(tmp_path), ["first.md"], ["first.md", "second.md"])
    results = json.loads(baseline.read_text())["results"]
    assert set(results) == {"first.md", "second.md"}
    assert results["second.md"][0]["is_secret"] is False
