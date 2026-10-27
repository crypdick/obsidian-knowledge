"""Plan and apply evidence-based created-date repairs without guessing timestamps."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator
from vault_preferences import load_preferences

from gardener.io import OrganizerPolicy, iter_paths, resolve_vault, validate_relative, visible_path, within
from lib.vault_index.note_creation import NoteCreationConfig, NoteFrontmatter, load_creation_config
from lib.vault_index.vault_files import write_vault_file


class CreationDate(RootModel[date | datetime]):
    """Accept explicit ISO dates only, not epoch coercions or future dates."""

    @field_validator("root", mode="before")
    @classmethod
    def explicit_date(cls, value: object) -> date | datetime:
        if isinstance(value, datetime | date):
            return value
        if not isinstance(value, str):
            raise ValueError("creation evidence must be an ISO date or datetime")
        return datetime.fromisoformat(value) if "T" in value or " " in value else date.fromisoformat(value)

    @model_validator(mode="after")
    def not_future(self) -> CreationDate:
        value = self.root
        local_now = datetime.now(UTC).astimezone()
        if isinstance(value, datetime):
            now = local_now if value.tzinfo is not None else local_now.replace(tzinfo=None)
            future = value > now
        else:
            future = value > local_now.date()
        if future:
            raise ValueError("creation evidence cannot be in the future")
        return self


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    created: CreationDate
    source: str = Field(min_length=1)

    @field_validator("source")
    @classmethod
    def identified_source(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identify the source of the creation date")
        return value


class EvidenceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: tuple[Evidence, ...] = ()


class Candidate(Evidence):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Unresolved(BaseModel):
    path: str
    reason: str


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    vault: Path
    candidates: tuple[Candidate, ...]
    unresolved: tuple[Unresolved, ...]
    existing: int
    excluded: int

    @model_validator(mode="after")
    def unique_candidates(self) -> Plan:
        if len({item.path for item in self.candidates}) != len(self.candidates):
            raise ValueError("plan contains duplicate candidate paths")
        return self


class AssistedZones(BaseModel):
    ai_assisted: tuple[str, ...] = ()

    @field_validator("ai_assisted")
    @classmethod
    def relative_zones(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            validate_relative(value)
        return values


class Scope(BaseModel):
    organizer: OrganizerPolicy
    assisted: AssistedZones
    creation: NoteCreationConfig

    @classmethod
    def load(cls) -> Scope:
        return cls(
            organizer=OrganizerPolicy.load(),
            assisted=AssistedZones.model_validate(load_preferences().root),
            creation=load_creation_config(),
        )

    def target(self, vault: Path, relative: str) -> Path:
        path = visible_path(vault, relative)
        policy = self.organizer
        if relative in policy.ai_readonly_root_files or any(
            within(relative, folder) for folder in policy.ai_readonly_folders
        ):
            raise ValueError(f"read-only path: {relative}")
        zones = (*policy.ai_managed, *self.assisted.ai_assisted)
        if not any(within(relative, zone) for zone in zones):
            raise ValueError(f"outside managed/assisted zones: {relative}")
        rel = Path(relative)
        if rel == self.creation.template or any(rel.is_relative_to(item) for item in self.creation.exclude):
            raise ValueError(f"excluded creation path: {relative}")
        if path.suffix.lower() != ".md":
            raise ValueError(f"not a Markdown note: {relative}")
        return path


class Note(BaseModel):
    content: bytes
    text: str
    bom: str
    header_end: int | None
    metadata: NoteFrontmatter

    @classmethod
    def read(cls, path: Path) -> Note:
        content = path.read_bytes()
        text = content.decode("utf-8-sig")
        match = re.match(
            r"\A(?P<opening>---[ \t]*\r?\n)(?P<yaml>.*?)(?P<closing>^(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z))",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if match:
            raw = yaml.safe_load(match["yaml"])
            metadata = NoteFrontmatter.model_validate({} if raw is None else raw)
        elif re.match(r"\A---[ \t]*(?:\r?\n|\Z)", text):
            raise ValueError("unclosed frontmatter")
        else:
            metadata = NoteFrontmatter()
        if (metadata.model_extra or {}).get("dg-publish") is True:
            raise ValueError("published note")
        return cls(
            content=content,
            text=text,
            bom="\ufeff" if content.startswith(b"\xef\xbb\xbf") else "",
            header_end=match.end("opening") if match else None,
            metadata=metadata,
        )

    def with_created(self, created: CreationDate) -> bytes:
        newline = "\r\n" if "\r\n" in self.text else "\n"
        header = f"created: {json.dumps(created.root.isoformat())}{newline}"
        if self.header_end is None:
            text = f"---{newline}{header}---{newline}{newline}{self.text}"
        else:
            text = self.text[: self.header_end] + header + self.text[self.header_end :]
        return (self.bom + text).encode("utf-8")


class ScanOptions(BaseModel):
    source_fields: tuple[str, ...] = ()
    paths: tuple[Path, ...] = ()
    evidence: EvidenceFile = Field(default_factory=EvidenceFile)


def choose_evidence(relative: str, note: Note, options: ScanOptions) -> Evidence | None:
    evidence = [record for record in options.evidence.records if record.path == relative]
    values = note.metadata.model_extra or {}
    for field in options.source_fields:
        if field in values:
            evidence.append(
                Evidence(
                    path=relative,
                    created=CreationDate.model_validate(values[field]),
                    source=f"frontmatter:{field}",
                )
            )
    if not evidence:
        return None
    if any(item.created.root != evidence[0].created.root for item in evidence[1:]):
        raise ValueError("conflicting creation evidence")
    return Evidence(
        path=relative,
        created=evidence[0].created,
        source="; ".join(sorted({item.source for item in evidence})),
    )


def make_plan(vault: Path, options: ScanOptions) -> Plan:
    scope = Scope.load()
    for selected in options.paths:
        if not visible_path(vault, selected.as_posix()).exists():
            raise ValueError(f"selected path does not exist: {selected}")
    candidates = []
    unresolved = []
    existing = excluded = 0
    for path in iter_paths(vault):
        if not path.is_file() or path.suffix.lower() != ".md":
            continue
        relative = path.relative_to(vault).as_posix()
        if options.paths and not any(Path(relative).is_relative_to(item) for item in options.paths):
            continue
        try:
            scope.target(vault, relative)
        except ValueError:
            excluded += 1
            continue
        try:
            note = Note.read(path)
            if "created" in note.metadata.model_fields_set:
                existing += 1
                continue
            found = choose_evidence(relative, note, options)
            if found is None:
                unresolved.append(Unresolved(path=relative, reason="no explicit creation-date evidence"))
                continue
            candidates.append(
                Candidate(**found.model_dump(), sha256=hashlib.sha256(note.content).hexdigest())
            )
        except (ValueError, OSError, yaml.YAMLError):
            unresolved.append(
                Unresolved(path=relative, reason="invalid, conflicting, published, or unreadable evidence")
            )
    return Plan(
        vault=vault,
        candidates=tuple(candidates),
        unresolved=tuple(unresolved),
        existing=existing,
        excluded=excluded,
    )


class PreparedEdit(BaseModel):
    path: str
    before: bytes
    after: bytes


class ApplyResult(BaseModel):
    applied: tuple[str, ...]
    already_present: tuple[str, ...]


def apply_plan(vault: Path, plan: Plan) -> ApplyResult:
    if plan.vault != vault:
        raise ValueError("plan belongs to a different vault; generate a plan for this vault")
    scope = Scope.load()
    edits = []
    existing = []
    # Preflight the whole reviewed set before changing any file.
    for item in plan.candidates:
        path = scope.target(vault, item.path)
        note = Note.read(path)
        if "created" in note.metadata.model_fields_set:
            existing.append(item.path)
            continue
        if hashlib.sha256(note.content).hexdigest() != item.sha256:
            raise ValueError(f"note changed since review: {item.path}")
        edits.append(PreparedEdit(path=item.path, before=note.content, after=note.with_created(item.created)))
    applied = []
    for edit in edits:
        scope.target(vault, edit.path)
        write_vault_file(vault, Path(edit.path), edit.after, replace=True, expected_content=edit.before)
        applied.append(edit.path)
    return ApplyResult(applied=tuple(applied), already_present=tuple(existing))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("plan", "apply"), default="plan")
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument(
        "--plan", type=Path, required=True, help="Write a new plan, or read a reviewed plan when applying"
    )
    parser.add_argument(
        "--source-field", action="append", default=[], help="Explicitly trusted creation-date property"
    )
    parser.add_argument(
        "--path", type=Path, action="append", default=[], help="Limit planning to a vault-relative path"
    )
    parser.add_argument(
        "--evidence", type=Path, help="JSON records with vetted path, created, and source values"
    )
    args = parser.parse_args(argv)
    try:
        vault = resolve_vault(args.vault)
        if args.plan.resolve().is_relative_to(vault):
            raise ValueError("store the review plan outside the vault")
        if args.action == "apply":
            if args.source_field or args.path or args.evidence:
                raise ValueError("apply uses the reviewed plan; selection/evidence flags belong to planning")
            result = apply_plan(vault, Plan.model_validate_json(args.plan.read_text()))
            print(result.model_dump_json(indent=2))
        else:
            evidence = (
                EvidenceFile.model_validate_json(args.evidence.read_text())
                if args.evidence
                else EvidenceFile()
            )
            plan = make_plan(
                vault, ScanOptions(source_fields=args.source_field, paths=args.path, evidence=evidence)
            )
            descriptor = os.open(args.plan, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(plan.model_dump_json(indent=2) + "\n")
            print(
                f"Planned {len(plan.candidates)} repairs; {len(plan.unresolved)} unresolved; "
                f"{plan.existing} existing dates preserved; {plan.excluded} paths excluded."
            )
            print(f"Review {args.plan}; the vault has not been changed.")
    except (ValueError, OSError, yaml.YAMLError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
