"""Typed inputs, candidates and decisions for unresolved-link recovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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


@dataclass(frozen=True)
class UnresolvedItem:
    link: str
    count: str | int = 0
    sources: str = ""

    @classmethod
    def from_json(cls, value: object) -> UnresolvedItem:
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
        return (
            self.classification
            in {
                "exact filename recovery",
                "high-confidence moved/renamed file",
            }
            and len(self.candidates) == 1
            and not any(char in self.candidates[0].link_target for char in "[]|#^\n\r")
        )


@dataclass(frozen=True)
class CandidateIndex:
    by_stem: dict[str, tuple[NoteCandidate, ...]]
    by_link_target: dict[str, tuple[NoteCandidate, ...]]
    by_norm: dict[str, tuple[NoteCandidate, ...]]
    by_alias_norm: dict[str, tuple[NoteCandidate, ...]]
    all_candidates: tuple[NoteCandidate, ...]
    vault_root: Path
