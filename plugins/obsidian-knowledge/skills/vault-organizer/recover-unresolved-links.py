#!/usr/bin/env python3
"""Classify and deterministically recover Obsidian unresolved wikilinks.

Usage:
  obsidian unresolved verbose format=json \
    | python3 recover-unresolved-links.py <vault_root> [--apply]

The script is intentionally conservative. It auto-fixes only unique exact
filename/alias/path recoveries. Ambiguous and fuzzy-looking items are reported
for human review instead of rewritten.
"""
from __future__ import annotations

import argparse
import json
import re
import signal
import sys
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Literal

try:
    import yaml as yaml_module
    HAS_YAML = True
except ImportError:  # pragma: no cover - exercised in packaged fallback contexts
    yaml_module = None
    HAS_YAML = False

signal.signal(signal.SIGPIPE, signal.SIG_DFL)

Classification = Literal[
    "exact filename recovery",
    "high-confidence moved/renamed file",
    "ambiguous candidate",
    "likely intentional concept stub",
    "missing-note/date/path reference",
]

DEFAULT_STUB_PATTERNS = [
    r"^\(PAPER\) ",
    r"^\(VIDEO\) ",
    r"^\(POST\) ",
    r"^\(PODCAST\) ",
    r"^\(RECIPE\) ",
    r"^\(BOOK\) ",
    r"^\(Vision\) ",
    r"^\(Pillar\) ",
    r"^@",
]
TEMPLATE_PLACEHOLDER = re.compile(r"\{\{|\<%")
DATEISH = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|\d{8}|\d{4}-\d{1,2}-\d{1,2})(?:\b|[-_ ])")
WIKILINK_CHARS = set("|#^")


@dataclass(frozen=True)
class Config:
    ai_managed: tuple[str, ...] = ("wiki",)
    stub_link_patterns: tuple[str, ...] = tuple(DEFAULT_STUB_PATTERNS)


@dataclass(frozen=True)
class UnresolvedItem:
    link: str
    count: str | int = 0
    sources: str = ""

    @classmethod
    def from_json(cls, value: object) -> "UnresolvedItem":
        if not isinstance(value, dict):
            raise ValueError(f"expected unresolved item object, got {type(value).__name__}")
        return cls(
            link=str(value.get("link", "")),
            count=value.get("count", 0),
            sources=str(value.get("sources", "")),
        )

    @property
    def source_paths(self) -> list[str]:
        return [source.strip() for source in self.sources.split(",") if source.strip()]


@dataclass(frozen=True)
class NoteCandidate:
    rel_path: str
    stem: str
    aliases: tuple[str, ...]

    @property
    def link_target(self) -> str:
        return self.rel_path[:-3] if self.rel_path.endswith(".md") else self.rel_path


@dataclass(frozen=True)
class RecoveryDecision:
    classification: Classification
    link: str
    sources: tuple[str, ...]
    candidates: tuple[NoteCandidate, ...] = ()
    score: float = 0.0
    rationale: str = ""

    @property
    def auto_fixable(self) -> bool:
        return self.classification in {
            "exact filename recovery",
            "high-confidence moved/renamed file",
        } and len(self.candidates) == 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault_root", type=Path)
    parser.add_argument("--apply", action="store_true", help="rewrite exact/high-confidence recoveries in source files")
    parser.add_argument("--include-stubs", action="store_true", help="show items matching configured stub patterns instead of dropping them")
    parser.add_argument("--format", choices=("tsv", "json"), default="tsv")
    return parser.parse_args()


def load_config(vault_root: Path) -> Config:
    config_path = vault_root / ".claude" / "obsidian-knowledge.yaml"
    if HAS_YAML and config_path.exists():
        with open(config_path, encoding="utf-8") as handle:
            assert yaml_module is not None
            raw = yaml_module.safe_load(handle) or {}
        return Config(
            ai_managed=tuple(str(zone) for zone in raw.get("ai_managed", ("wiki",))),
            stub_link_patterns=tuple(str(pattern) for pattern in raw.get("stub_link_patterns", DEFAULT_STUB_PATTERNS)),
        )
    return Config()


def normalize_name(value: str) -> str:
    name = value.strip().replace("_", "-")
    if name.endswith(".md"):
        name = name[:-3]
    if "/" in name:
        name = Path(name).name
    name = re.sub(r"\s+", " ", name.casefold())
    name = re.sub(r"[^\w\d]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def link_stem(link: str) -> str:
    link = link.split("#", 1)[0].split("^", 1)[0]
    if link.endswith(".md"):
        link = link[:-3]
    return Path(link).name if "/" in link else link


def looks_real_file_reference(link: str) -> bool:
    if any(char in link for char in ("/", ".")):
        return True
    if DATEISH.search(link):
        return True
    return False


def is_stub(link: str, patterns: Iterable[re.Pattern[str]]) -> bool:
    return bool(TEMPLATE_PLACEHOLDER.search(link) or any(pattern.search(link) for pattern in patterns))


def managed_sources(item: UnresolvedItem, config: Config) -> tuple[str, ...]:
    prefixes = tuple(f"{zone.rstrip('/')}/" for zone in config.ai_managed)
    return tuple(source for source in item.source_paths if source.startswith(prefixes))


def frontmatter_aliases(text: str) -> tuple[str, ...]:
    if not text.startswith("---\n"):
        return ()
    end = text.find("\n---", 4)
    if end == -1 or not HAS_YAML:
        return ()
    try:
        assert yaml_module is not None
        frontmatter = yaml_module.safe_load(text[4:end]) or {}
    except Exception:
        return ()
    aliases = frontmatter.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, list):
        return ()
    return tuple(str(alias) for alias in aliases if str(alias).strip())


def iter_notes(vault_root: Path) -> Iterable[NoteCandidate]:
    ignored_parts = {".obsidian", ".stversions", ".trash"}
    for path in vault_root.rglob("*.md"):
        rel_path = path.relative_to(vault_root).as_posix()
        if any(part in ignored_parts for part in path.relative_to(vault_root).parts):
            continue
        if ".sync-conflict-" in rel_path:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        yield NoteCandidate(rel_path=rel_path, stem=path.stem, aliases=frontmatter_aliases(text))


@dataclass(frozen=True)
class CandidateIndex:
    by_stem: dict[str, tuple[NoteCandidate, ...]]
    by_link_target: dict[str, NoteCandidate]
    by_norm: dict[str, tuple[NoteCandidate, ...]]
    by_alias_norm: dict[str, tuple[NoteCandidate, ...]]
    all_candidates: tuple[NoteCandidate, ...]


def build_index(vault_root: Path) -> CandidateIndex:
    stem_map: dict[str, list[NoteCandidate]] = defaultdict(list)
    norm_map: dict[str, list[NoteCandidate]] = defaultdict(list)
    alias_map: dict[str, list[NoteCandidate]] = defaultdict(list)
    candidates = tuple(iter_notes(vault_root))
    for candidate in candidates:
        stem_map[candidate.stem].append(candidate)
        norm_map[normalize_name(candidate.stem)].append(candidate)
        for alias in candidate.aliases:
            alias_map[normalize_name(alias)].append(candidate)
    return CandidateIndex(
        by_stem={key: tuple(value) for key, value in stem_map.items()},
        by_link_target={candidate.link_target: candidate for candidate in candidates},
        by_norm={key: tuple(value) for key, value in norm_map.items() if key},
        by_alias_norm={key: tuple(value) for key, value in alias_map.items() if key},
        all_candidates=candidates,
    )


def unique(candidates: Iterable[NoteCandidate]) -> tuple[NoteCandidate, ...]:
    seen: dict[str, NoteCandidate] = {}
    for candidate in candidates:
        seen[candidate.rel_path] = candidate
    return tuple(seen.values())


def best_fuzzy_candidates(name: str, all_candidates: tuple[NoteCandidate, ...]) -> tuple[float, tuple[NoteCandidate, ...]]:
    normalized = normalize_name(name)
    if not normalized:
        return 0.0, ()
    scored = []
    for candidate in all_candidates:
        score = SequenceMatcher(None, normalized, normalize_name(candidate.stem)).ratio()
        if score >= 0.82:
            scored.append((score, candidate))
    if not scored:
        return 0.0, ()
    scored.sort(key=lambda item: (-item[0], item[1].rel_path))
    top_score = scored[0][0]
    top = tuple(candidate for score, candidate in scored if score >= top_score - 0.02)[:5]
    return top_score, top


def classify(item: UnresolvedItem, sources: tuple[str, ...], index: CandidateIndex, patterns: tuple[re.Pattern[str], ...]) -> RecoveryDecision | None:
    link = item.link.strip()
    if not sources:
        return None
    if is_stub(link, patterns):
        return RecoveryDecision("likely intentional concept stub", link, sources, rationale="matches configured stub/template pattern")

    if "/" in link:
        path_key = link[:-3] if link.endswith(".md") else link
        path_candidate = index.by_link_target.get(path_key)
        if path_candidate is not None:
            return RecoveryDecision("exact filename recovery", link, sources, (path_candidate,), 1.0, "unique relative-path match")
        if looks_real_file_reference(link):
            return RecoveryDecision("missing-note/date/path reference", link, sources, score=0.0, rationale="path-shaped target with no exact relative-path match")

    stem = link_stem(link)
    exact_stem = unique(index.by_stem.get(stem, ()))
    if len(exact_stem) == 1:
        return RecoveryDecision("exact filename recovery", link, sources, exact_stem, 1.0, "unique basename match")
    if len(exact_stem) > 1:
        return RecoveryDecision("ambiguous candidate", link, sources, exact_stem, 1.0, "multiple basename matches")

    norm = normalize_name(stem)
    normalized_candidates = unique((*index.by_norm.get(norm, ()), *index.by_alias_norm.get(norm, ())))
    if len(normalized_candidates) == 1:
        return RecoveryDecision("high-confidence moved/renamed file", link, sources, normalized_candidates, 1.0, "unique normalized stem/alias match")
    if len(normalized_candidates) > 1:
        return RecoveryDecision("ambiguous candidate", link, sources, normalized_candidates, 1.0, "multiple normalized stem/alias matches")

    fuzzy_score, fuzzy_candidates = best_fuzzy_candidates(stem, index.all_candidates)
    if fuzzy_candidates:
        return RecoveryDecision("ambiguous candidate", link, sources, fuzzy_candidates, fuzzy_score, "near fuzzy filename match; manual review required")

    if looks_real_file_reference(link):
        return RecoveryDecision("missing-note/date/path reference", link, sources, score=0.0, rationale="date/path/extension-shaped target with no candidate")
    return RecoveryDecision("likely intentional concept stub", link, sources, score=0.0, rationale="plain concept-shaped target with no candidate")


def replacement_for(decision: RecoveryDecision) -> str:
    candidate = decision.candidates[0]
    # Prefer basename links when unique/high-confidence; fall back to relative path for path-shaped old links.
    if "/" in decision.link or candidate.stem != link_stem(decision.link):
        return candidate.link_target
    return candidate.stem


def rewrite_source(vault_root: Path, source: str, old_link: str, new_target: str) -> int:
    path = vault_root / source
    text = path.read_text(encoding="utf-8")
    escaped = re.escape(old_link)
    pattern = re.compile(r"\[\[(" + escaped + r")(?P<suffix>[#^|\]])")

    def repl(match: re.Match[str]) -> str:
        suffix = match.group("suffix")
        return "[[" + new_target + suffix

    new_text, count = pattern.subn(repl, text)
    if count:
        path.write_text(new_text, encoding="utf-8")
    return count


def emit(decisions: list[RecoveryDecision], output_format: str) -> None:
    if output_format == "json":
        payload = [
            {
                "classification": decision.classification,
                "link": decision.link,
                "sources": list(decision.sources),
                "candidates": [candidate.rel_path for candidate in decision.candidates],
                "score": round(decision.score, 3),
                "rationale": decision.rationale,
                "auto_fixable": decision.auto_fixable,
            }
            for decision in decisions
        ]
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    counts: dict[str, int] = defaultdict(int)
    for decision in decisions:
        counts[decision.classification] += 1
    print("# classification\tcount")
    for key in sorted(counts):
        print(f"# {key}\t{counts[key]}")
    print("classification\tlink\tsources\tcandidates\tscore\trationale")
    for decision in decisions:
        candidates = ", ".join(candidate.rel_path for candidate in decision.candidates)
        print(
            f"{decision.classification}\t{decision.link}\t{', '.join(decision.sources)}\t"
            f"{candidates}\t{decision.score:.3f}\t{decision.rationale}"
        )


def main() -> None:
    args = parse_args()
    vault_root = args.vault_root.resolve()
    config = load_config(vault_root)
    patterns = tuple(re.compile(pattern) for pattern in config.stub_link_patterns)
    raw_items = json.load(sys.stdin)
    items = [UnresolvedItem.from_json(raw_item) for raw_item in raw_items]
    index = build_index(vault_root)

    decisions = []
    for item in items:
        sources = managed_sources(item, config)
        decision = classify(item, sources, index, patterns)
        if decision is None:
            continue
        if decision.classification == "likely intentional concept stub" and not args.include_stubs:
            continue
        decisions.append(decision)

    if args.apply:
        rewrites = 0
        for decision in decisions:
            if not decision.auto_fixable:
                continue
            new_target = replacement_for(decision)
            for source in decision.sources:
                rewrites += rewrite_source(vault_root, source, decision.link, new_target)
        print(f"# applied_rewrites\t{rewrites}")

    emit(decisions, args.format)


if __name__ == "__main__":
    main()
