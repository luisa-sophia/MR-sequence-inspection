"""
Step 3 (optional): convert the dicoms to a BIDS conform nifti dataset with heudiconv + your heuristic.

Paths, heuristic and container come from the config (bids_dir, bids_heuristic, bids_dcm_pattern,
bids_env, container, container_tmp).

From the terminal:
    python -m seqinspect.convert configs/myproject.py --subjects sub-01 sub-02
    python -m seqinspect.convert configs/myproject.py --subjects sub-01_ses-A sub-20_ses-B   # with sessions
    python -m seqinspect.convert configs/myproject.py --all
    python -m seqinspect.convert --help

From a notebook:
    convert(cfg, ["01", "02"])

Without sessions: ids are given with or without 'sub-'. heudiconv gets the id without it, so if
the dicom folders are called sub-<id>, write 'sub-{subject}' in the pattern.
With sessions ('{session}' in the pattern): ids are given as sub-<ID>_ses-<sess>, or in the format
of short_id_regex (e.g. 01B). heudiconv runs once per session, as it can only do one session at a time.

Author: Luisa Seckinger
"""
import argparse
import glob
import os
import re
import sys

from .config import APPTAINER_MISSING, Config, find_apptainer, load_config
from .heudiconv import heudiconv_binds, heudiconv_cmd, heuristic_path, print_versions, stream
from .sessions import find_sessions

BIDS_ID = r"^sub-(?P<subject>[^_]+)(_ses-(?P<session>[^_]+))?(_.*)?$" #allow also suffixes after ses but they wont be taken in 

def bids_pattern(cfg: Config) -> str:
    return os.path.abspath(cfg.path(cfg.bids_dcm_pattern or cfg.dcm_pattern))


def has_sessions(cfg: Config) -> bool:
    return "{session}" in bids_pattern(cfg)


def parse_id(cfg: Config, raw: str) -> tuple[str, str | None]:
    """'sub-01', 'sub-01_ses-B', '01' or the short_id_regex format -> (subject, session or None)."""
    with_session = has_sessions(cfg)
    for regex in [BIDS_ID, cfg.short_id_regex]:
        m = re.match(regex, raw) if regex else None
        if m and (m.groupdict().get("session") is not None) == with_session:
            return m["subject"], m.groupdict().get("session")
    if not with_session:
        return raw, None
    raise ValueError(f"Unsupported subject/session format '{raw}', must be sub-<ID>_ses-<sess>"
                     + (f" or match '{cfg.short_id_regex}'" if cfg.short_id_regex else "") + ".")


def _pattern_for(cfg: Config, subject: str, session: str | None) -> str:
    return bids_pattern(cfg).replace("{subject}", subject).replace("{session}", session or "")


def parse_ids(cfg: Config, subjects: list[str], skip_unknown: bool = False) -> dict[str | None, list[str]]:
    """
    Parse the ids and check that the pattern finds dicoms for each of them.
    Returns {session: [subjects]} ({None: [...]} without sessions).
    skip_unknown: ids in an unsupported format are skipped with a warning instead of raising (for --all).
    """
    groups, missing = {}, []
    for raw in subjects:
        try:
            subject, session = parse_id(cfg, raw)
        except ValueError as e:
            if not skip_unknown:
                raise
            print(f"WARNING: skipping folder '{raw}': {e}")
            continue
        if next(glob.iglob(_pattern_for(cfg, subject, session)), None) is None:
            missing.append(_pattern_for(cfg, subject, session))
        groups.setdefault(session, []).append(subject)
    if missing:
        raise FileNotFoundError(
            f"No dicoms found for {len(missing)} id(s), e.g. with pattern '{missing[0]}'.\n"
            "If the folders are called sub-<id>, use 'sub-{subject}' in the pattern.")
    return {ses: sorted(set(subs)) for ses, subs in sorted(groups.items(), key=lambda x: x[0] or "")}


def _env_binds(env: dict) -> list[str]:
    """Absolute file paths in bids_env (their folders are mounted). Warns if a file doesn't exist."""
    paths = []
    for key, value in env.items():
        if isinstance(value, str) and os.path.isabs(value):
            if os.path.exists(value):
                paths.append(value)
            else:
                print(f"WARNING: {key} '{value}' not found - the heuristic will fall back to its built-in default.")
    return paths


def convert(cfg: Config, subjects: list[str], outdir: str | None = None, heuristic: str | None = None,
            skip_unknown: bool = False, overwrite: bool = True) -> int:
    """
    Run heudiconv with the heuristic and dcm2niix for the given subjects
    (one heudiconv call, or one per session). Returns the exit code.

    Note that the overwrite flag is not behaving as you would expect. 
    Not passing it will cause heudiconv to fail on already processed subjects.
    """
    outdir = os.path.abspath(cfg.path(outdir or cfg.bids_dir))
    heuristic = heuristic_path(heuristic or cfg.bids_heuristic)
    groups = parse_ids(cfg, subjects, skip_unknown=skip_unknown)
    os.makedirs(outdir, exist_ok=True)

    print_versions(cfg)
    env_vars = {k: str(v) for k, v in cfg.bids_env.items()}
    binds = heudiconv_binds(cfg, outdir, heuristic, *_env_binds(env_vars), pattern=bids_pattern(cfg))
    prefix_cmd, env = heudiconv_cmd(cfg, binds, extra_env=env_vars)

    ok, failed = {}, {}
    for session, ids in groups.items():
        cmd = prefix_cmd + [
            "--dicom_dir_template", bids_pattern(cfg),
            "--subjects", *ids,
            *(["--ses", session] if session else []),
            "-f", heuristic,
            "--minmeta",
            "--converter", "dcm2niix",
            "--outdir", outdir,
            "-b",
            *(["--overwrite"] if overwrite else [])
        ]
        sess_string = f" for session {session}" if session else ""
        print(f"\n... starting heudiconv{sess_string}, subject(s): {' '.join(ids)}")
        status = stream(cmd, env, cwd="/" if cfg.container else None)
        if status == 0:
            ok[session] = ids
        else:
            print(f"\nERROR: heudiconv failed{sess_string}, subject(s): {' '.join(ids)} (exit code {status}) - continuing with the next session.")
            failed[session] = ids
            

    print("\n" + "=" * 85)
    if ok:
        print(f"Converted: {_mapping_text(ok)}")
    if failed:
        print(f"FAILED, heudiconv call did not finish for the following sessions: {_mapping_text(failed)}")
        print("Check the output above for the errors.")
    print("=" * 85)
    
    return 1 if failed else 0


# def _mapping_text(groups: dict) -> str:
#     if None in groups:
#         return " ".join(groups[None])
#     return "".join(f"\n  Session {ses}: {' '.join(subs)}" for ses, subs in groups.items())

def _mapping_text(groups: dict) -> str:
    if None in groups:
        return " ".join(groups[None])

    by_subject = {}
    for ses, subs in groups.items():
        for sub in subs:
            by_subject.setdefault(sub, []).append(ses)

    # group by whichever has fewer distinct values (tie: by subject)
    if len(by_subject) <= len(groups):
        outer, inner, mapping = "Subject", "Session", by_subject
    else:
        outer, inner, mapping = "Session", "Subject", groups

    return "".join(
        f"\n  {outer} {key}:" + "".join(f"\n    - {inner} {item}" for item in items)
        for key, items in mapping.items()
    )


def _confirm(question: str) -> bool:
    return input(f"{question} [ENTER = yes, 1 = quit]: ").strip() != "1"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert dicoms to a BIDS dataset with heudiconv.")
    parser.add_argument("config", help="config file, e.g. configs/myproject.py")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--subjects", nargs="+",
                       help="ids: sub-01 / 01, with sessions sub-01_ses-B (or the short_id_regex format)")
    group.add_argument("--all", action="store_true", help="all sessions found below dicom_root")
    parser.add_argument("--root", help="overrides root from the config")
    parser.add_argument("--outdir", help="overrides bids_dir from the config")
    parser.add_argument("--heuristic", help="overrides bids_heuristic from the config")
    parser.add_argument("--no-overwrite", action="store_true", help="don't pass --overwrite to heudiconv. It will fail on subjects that have already been processed.")
    parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation (e.g. in batch jobs)")
    args = parser.parse_args(argv)

    print("\n" + "=" * 85)
    print("Conversion script to create a BIDS conform nifti dataset from DICOMS (via heudiconv).")
    print("=" * 85 + "\n")

    cfg = load_config(args.config, **({"root": args.root} if args.root else {}))
    if cfg.container and not find_apptainer():
        print(f"ERROR: {APPTAINER_MISSING}")
        sys.exit(1)

    subjects = find_sessions(cfg) if args.all else args.subjects
    outdir = os.path.abspath(cfg.path(args.outdir or cfg.bids_dir or ""))
    heuristic = args.heuristic or cfg.bids_heuristic
    if not (args.outdir or cfg.bids_dir) or not heuristic:
        parser.error("bids_dir and bids_heuristic must be set in the config (or via --outdir / --heuristic).")

    try:
        groups = parse_ids(cfg, subjects, skip_unknown=args.all)
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"DICOM template: {bids_pattern(cfg)}")
    print(f"Output dir:     {outdir}")
    print(f"Heuristic:      {heuristic}")
    for key, value in cfg.bids_env.items():
        print(f"{key + ':':15} {value}")
    print(f"Container:      {cfg.container or 'none (installed heudiconv)'}"
          + (f"  ({cfg.container_image})" if cfg.container and not cfg.container.endswith(".sif") else ""))
    print(f"Subjects:       {_mapping_text(groups)}\n")

    overwrite = not args.no_overwrite

    if not args.yes:
        if not _confirm("Continue with these settings?"):
            sys.exit(1)
        if os.path.isdir(outdir) and os.listdir(outdir) and not _confirm(f"Output directory exists and is not empty. Overwrite {'enabled' if overwrite else 'disabled'}. Continue?"):
            sys.exit(1)

    # the parsed ids (unsupported folders from --all are already dropped)
    subjects = [f"sub-{sub}" + (f"_ses-{ses}" if ses else "") for ses, subs in groups.items() for sub in subs]
    sys.exit(convert(cfg, subjects, outdir=outdir, heuristic=heuristic, overwrite = overwrite))


if __name__ == "__main__":
    main()
