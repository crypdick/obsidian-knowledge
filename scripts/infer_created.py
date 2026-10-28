"""Build explicitly estimated creation-date evidence from a backfill preview.

Run with ``uv run python -m scripts.infer_created`` from the source checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from gardener.io import validate_relative
from scripts.backfill_created import CreationDate, Evidence, EvidenceFile, Note, Plan, Scope


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    observed: CreationDate
    source: str


class Observations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: tuple[Observation, ...] = ()


class InferenceOptions(BaseModel):
    dated_paths: tuple[Path, ...] = ()
    filename_dates: bool = False
    history: Path | None = None
    mtime: bool = False
    observations: Observations = Observations()


def valid_day(value: object) -> CreationDate | None:
    try:
        parsed = CreationDate.model_validate(value).root
        day = parsed.date() if isinstance(parsed, datetime) else parsed
        return CreationDate.model_validate(day)
    except ValueError:
        return None


def filename_record(relative: str) -> Evidence | None:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?!\d)", Path(relative).name)
    created = valid_day(match[1]) if match else None
    if created is None:
        return None
    return Evidence(path=relative, created=created, source=f"Accepted filename date: {relative}")


def modification_records(path: Path, relative: str, note: Note) -> tuple[Evidence, ...]:
    """Modification dates are upper-bound estimates, never verified creation."""
    values = note.metadata.model_extra or {}
    records = []
    mtime = path.stat().st_mtime
    candidates = (
        ("frontmatter updated", values.get("updated")),
        ("frontmatter modified", values.get("modified")),
        ("file mtime", datetime.fromtimestamp(mtime).astimezone() if mtime > 86400 else None),
    )
    for label, value in candidates:
        created = valid_day(value)
        if created is not None:
            records.append(
                Evidence(path=relative, created=created, source=f"{label}: {path}", estimated=True)
            )
    return tuple(records)


def history_records(vault: Path, wanted: frozenset[str], options: InferenceOptions) -> EvidenceFile:
    records = []
    if options.history is None:
        return EvidenceFile()
    if not options.history.is_dir():
        raise ValueError("history root is not a directory")
    scope = Scope.load()
    for path in sorted(options.history.rglob("*.md")):
        relative = path.relative_to(options.history).as_posix()
        original = re.sub(r"~\d{8}-\d{6}(?=\.md$)", "", relative)
        if path.is_symlink() or ".sync-conflict-" in relative or original not in wanted:
            continue
        if original != relative and relative in wanted:
            continue
        try:
            scope.target(vault, original)
            note = Note.read(path)
            created = valid_day((note.metadata.model_extra or {}).get("created"))
            if created is not None:
                records.append(
                    Evidence(
                        path=original,
                        created=created,
                        source=f"historical created estimate: {path}",
                        estimated=True,
                    )
                )
            if options.mtime:
                records.extend(modification_records(path, original, note))
        except (OSError, ValueError, yaml.YAMLError):
            continue
    return EvidenceFile(records=tuple(records))


def select_estimate(
    relative: str, note: Note, options: InferenceOptions, records: EvidenceFile
) -> Evidence | None:
    filename = filename_record(relative) if options.filename_dates else None
    if filename is not None:
        return filename
    choices = [item for item in records.records if item.path == relative]
    historical = [item for item in choices if item.source.startswith("historical created estimate:")]
    if historical:
        earliest = min(historical, key=lambda item: item.created.root.isoformat())
        dates = {item.created.root.isoformat() for item in historical}
        label = "historical frontmatter" if len(dates) == 1 else "earliest conflicting historical frontmatter"
        return earliest.model_copy(update={"source": f"Estimated from {label}; {earliest.source}"})
    # The caller explicitly identifies scopes whose dates describe note-writing,
    # rather than e.g. a scanned document's or a future event's date.
    if any(Path(relative).is_relative_to(folder) for folder in options.dated_paths):
        body = note.text[note.body_start :].lstrip("\r\n")
        for label, text in (("dated filename", Path(relative).name), ("opening date", body)):
            match = re.match(r"^[# \t]*(\d{4}-\d{2}-\d{2})(?!\d)", text)
            created = valid_day(match[1]) if match else None
            if created is not None and all(created.root <= item.created.root for item in choices):
                return Evidence(
                    path=relative,
                    created=created,
                    source=f"Estimated from {label}: {relative}",
                    estimated=True,
                )
    if not choices:
        return None
    earliest = min(choices, key=lambda item: item.created.root.isoformat())
    return earliest.model_copy(
        update={"source": f"Estimated from earliest available observation; {earliest.source}"}
    )


def infer_evidence(plan: Plan, options: InferenceOptions) -> EvidenceFile:
    scope = Scope.load()
    for folder in options.dated_paths:
        validate_relative(folder.as_posix())
    wanted = frozenset(item.path for item in plan.unresolved)
    records = list(history_records(plan.vault, wanted, options).records)
    for observation in options.observations.records:
        created = valid_day(observation.observed.root)
        if observation.path in wanted and created is not None:
            records.append(
                Evidence(
                    path=observation.path,
                    created=created,
                    source=f"recorded observation: {observation.source}",
                    estimated=True,
                )
            )
    result = []
    for item in plan.candidates:
        filename = filename_record(item.path) if options.filename_dates else None
        result.append(
            Evidence(
                path=item.path,
                created=filename.created if filename is not None else item.created,
                source=filename.source
                if filename is not None
                else (
                    f"Estimated from historical metadata; {item.source}"
                    if item.requires_review
                    else item.source
                ),
                note_sha256=item.sha256,
                estimated=False if filename is not None else item.estimated or item.requires_review,
            )
        )
    for relative in sorted(wanted):
        try:
            path = scope.target(plan.vault, relative)
            note = Note.read(path)
            if "created" in note.metadata.model_fields_set:
                continue
            choices = tuple(item for item in records if item.path == relative)
            if options.mtime:
                choices += modification_records(path, relative, note)
            found = select_estimate(relative, note, options, EvidenceFile(records=choices))
            if found is not None:
                result.append(
                    found.model_copy(update={"note_sha256": hashlib.sha256(note.content).hexdigest()})
                )
        except (OSError, ValueError, yaml.YAMLError):
            continue
    return EvidenceFile(records=tuple(result))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-plan", type=Path, required=True)
    parser.add_argument("--output-evidence", type=Path, required=True)
    parser.add_argument("--dated-path", type=Path, action="append", default=[])
    parser.add_argument(
        "--filename-dates", action="store_true", help="Explicitly accept leading YYYY-MM-DD filename dates"
    )
    parser.add_argument("--history", type=Path)
    parser.add_argument("--observations", type=Path)
    parser.add_argument(
        "--mtime", action="store_true", help="Allow oldest modification date as a fallback estimate"
    )
    args = parser.parse_args(argv)
    try:
        plan = Plan.model_validate_json(args.input_plan.read_text())
        if args.output_evidence.resolve().is_relative_to(plan.vault):
            raise ValueError("store evidence outside the vault")
        observations = (
            Observations.model_validate_json(args.observations.read_text())
            if args.observations
            else Observations()
        )
        evidence = infer_evidence(
            plan,
            InferenceOptions(
                dated_paths=args.dated_path,
                filename_dates=args.filename_dates,
                history=args.history,
                mtime=args.mtime,
                observations=observations,
            ),
        )
        descriptor = os.open(args.output_evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(evidence.model_dump_json(indent=2) + "\n")
        print(
            f"Saved {len(evidence.records)} records ({sum(item.estimated for item in evidence.records)} estimates); vault unchanged."
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
