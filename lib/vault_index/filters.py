"""Path-based filtering and weighting."""

from __future__ import annotations

import re

from lib.vault_index.config import DigestFilter, IndexFilter, VaultIndexConfig
from lib.vault_index.models import Hit


def score_path(path: str, config: VaultIndexConfig) -> float:
    """Return the weight multiplier for `path` per config weights.

    Longest regex match wins. Ties broken by first-listed rule.
    Falls back to `default_weight` if no rule matches.
    """
    best_match_len = -1
    best_multiplier = config.default_weight
    for rule in config.weights:
        m = re.search(rule.regex, path)
        if m is None:
            continue
        match_len = m.end() - m.start()
        if match_len > best_match_len:
            best_match_len = match_len
            best_multiplier = rule.multiplier
    return best_multiplier


def path_passes(path: str, filt: IndexFilter | DigestFilter) -> bool:
    """Return True if `path` passes the allow/deny filter rules.

    Logic:
      - If `deny_regex` matches, fail.
      - Else if `allow_regex` is non-empty, require a match.
      - Else pass.
    """
    for pattern in filt.deny_regex:
        if re.search(pattern, path):
            return False
    if filt.allow_regex:
        return any(re.search(p, path) for p in filt.allow_regex)
    return True


def apply_filters(
    hits: list[Hit],
    config: VaultIndexConfig,
    *,
    override_digest_filter: bool = False,
) -> list[Hit]:
    """Apply digest filters + path weights to a list of hits.

    Pipeline:
      1. (Unless overridden) drop hits failing the digest allow/deny.
      2. Multiply each hit's score by its path weight.
      3. Re-sort descending by weighted score.
      4. Truncate to `config.top_k`.
      5. (If `min_score` set) drop weighted scores below threshold.
    """
    if not override_digest_filter:
        hits = [h for h in hits if path_passes(h.path, config.digest)]

    weighted: list[Hit] = []
    for h in hits:
        w = score_path(h.path, config)
        weighted.append(
            Hit(
                path=h.path,
                score=h.score * w,
                weight_applied=w,
            )
        )

    # Dedup by path — keep highest-scoring chunk per path so a note with
    # multiple matching paragraphs doesn't crowd out other results.
    best: dict[str, Hit] = {}
    for h in weighted:
        if h.path not in best or best[h.path].score < h.score:
            best[h.path] = h
    weighted = list(best.values())

    weighted.sort(key=lambda h: h.score, reverse=True)

    if config.min_score is not None:
        weighted = [h for h in weighted if h.score >= config.min_score]

    return weighted[: config.top_k]
