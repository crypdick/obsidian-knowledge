"""Tests for path filtering and weighting."""
from lib.vault_index.config import DigestFilter, IndexFilter, VaultIndexConfig, WeightRule
from lib.vault_index.filters import apply_filters, path_passes, score_path
from lib.vault_index.indexer import Hit


# ---------------------------------------------------------------------------
# Task 4: score_path
# ---------------------------------------------------------------------------


def test_score_path_default_weight_when_no_match():
    cfg = VaultIndexConfig(default_weight=1.0)
    assert score_path("Inbox/foo.md", cfg) == 1.0


def test_score_path_uses_matching_weight():
    cfg = VaultIndexConfig(
        weights=[WeightRule(regex=r"^wiki/", multiplier=1.5)],
        default_weight=1.0,
    )
    assert score_path("wiki/foo.md", cfg) == 1.5


def test_score_path_longest_regex_wins():
    cfg = VaultIndexConfig(
        weights=[
            WeightRule(regex=r"^wiki/", multiplier=1.5),
            WeightRule(regex=r"^wiki/special/", multiplier=2.0),
        ],
        default_weight=1.0,
    )
    assert score_path("wiki/foo.md", cfg) == 1.5
    assert score_path("wiki/special/bar.md", cfg) == 2.0


# ---------------------------------------------------------------------------
# Task 5: path_passes
# ---------------------------------------------------------------------------


def test_path_passes_default_when_both_empty():
    f = IndexFilter()
    assert path_passes("Inbox/foo.md", f) is True


def test_path_passes_denies_matching():
    f = IndexFilter(deny_regex=[r"^Inbox/"])
    assert path_passes("Inbox/foo.md", f) is False
    assert path_passes("wiki/foo.md", f) is True


def test_path_passes_allow_overrides_default():
    f = IndexFilter(allow_regex=[r"^wiki/"])
    assert path_passes("wiki/foo.md", f) is True
    assert path_passes("Inbox/foo.md", f) is False  # not in allowlist


def test_path_passes_deny_beats_allow():
    f = IndexFilter(allow_regex=[r"^wiki/"], deny_regex=[r"^wiki/secret/"])
    assert path_passes("wiki/foo.md", f) is True
    assert path_passes("wiki/secret/bar.md", f) is False


# ---------------------------------------------------------------------------
# Task 6: apply_filters
# ---------------------------------------------------------------------------


def _h(path: str, score: float) -> Hit:
    return Hit(path=path, score=score, weight_applied=1.0)


def test_apply_filters_truncates_to_top_k():
    cfg = VaultIndexConfig(top_k=2)
    hits = [_h("wiki/a.md", 9.0), _h("wiki/b.md", 8.0), _h("wiki/c.md", 7.0)]
    out = apply_filters(hits, cfg)
    assert len(out) == 2
    assert out[0].path == "wiki/a.md"


def test_apply_filters_drops_denied_paths():
    cfg = VaultIndexConfig(
        digest=DigestFilter(deny_regex=[r"^Inbox/"]),
        top_k=10,
    )
    hits = [_h("wiki/a.md", 9.0), _h("Inbox/b.md", 8.0)]
    out = apply_filters(hits, cfg)
    paths = [h.path for h in out]
    assert "Inbox/b.md" not in paths


def test_apply_filters_applies_weight_and_resorts():
    cfg = VaultIndexConfig(
        weights=[WeightRule(regex=r"^wiki/", multiplier=2.0)],
        default_weight=1.0,
        top_k=10,
    )
    hits = [_h("Inbox/a.md", 9.0), _h("wiki/b.md", 5.0)]
    out = apply_filters(hits, cfg)
    # wiki/b: 5.0 * 2.0 = 10.0, beats Inbox/a: 9.0 * 1.0 = 9.0
    assert out[0].path == "wiki/b.md"
    assert out[0].weight_applied == 2.0


def test_apply_filters_override_digest_filter_bypasses_digest_rules():
    cfg = VaultIndexConfig(
        digest=DigestFilter(allow_regex=[r"^wiki/"]),
        top_k=10,
    )
    hits = [_h("wiki/a.md", 9.0), _h("Inbox/b.md", 8.0)]
    out = apply_filters(hits, cfg, override_digest_filter=True)
    assert len(out) == 2  # both kept
