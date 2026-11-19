"""
Step 3 (optional): convert the dicoms to a BIDS conform nifti dataset with heudiconv + your heuristic.
For subjects WITHOUT session structure.

Paths, heuristic and container come from the config (bids_dir, bids_heuristic, container, container_tmp).

From the terminal:
    python -m seqinspect.convert configs/myproject.py --subjects sub-01 sub-02
    python -m seqinspect.convert configs/myproject.py --all
    python -m seqinspect.convert --help

From a notebook:
    convert(cfg, ["01", "02"])

Subject ids are given with or without 'sub-'. heudiconv gets the id without it, so if
the dicom folders are called sub-<id>, write 'sub-{subject}' in the dcm_pattern.

Author: Luisa Seckinger
"""
import argparse
import os
import sys

from .config import Config, load_config
from .dicominfo import (find_sessions, has_dicoms, heudiconv_binds, heudiconv_cmd, heuristic_path, print_versions,
                        session_pattern, stream)


def subject_ids(cfg: Config, subjects: list[str]) -> list[str]:
    """Strip a leading 'sub-' and check that the dcm_pattern finds dicoms for every subject."""
    ids = [s[4:] if s.startswith("sub-") else s for s in subjects]
    missing = [s for s in ids if not has_dicoms(cfg, s)]
    if missing:
        raise FileNotFoundError(
            f"No dicoms found for {missing}, e.g. with pattern '{session_pattern(cfg, missing[0])}'.\n"
            "If the folders are called sub-<id>, use 'sub-{subject}' in the dcm_pattern.")
    return ids


def convert(cfg: Config, subjects: list[str], outdir: str | None = None, heuristic: str | None = None) -> int:
    """Run heudiconv with the heuristic and dcm2niix for the given subjects (one heudiconv call). Returns the exit code."""
    outdir = os.path.abspath(cfg.path(outdir or cfg.bids_dir))
    heuristic = heuristic_path(heuristic or cfg.bids_heuristic)
    ids = subject_ids(cfg, subjects)
    os.makedirs(outdir, exist_ok=True)

    print_versions(cfg)
    prefix_cmd, env = heudiconv_cmd(cfg, heudiconv_binds(cfg, outdir, heuristic))
    cmd = prefix_cmd + [
        "--dicom_dir_template", os.path.abspath(cfg.path(cfg.dcm_pattern)),
        "--subjects", *ids,
        "-f", heuristic,
        "--minmeta",
        "--converter", "dcm2niix",
        "--outdir", outdir,
        "-b",
        "--overwrite",
    ]
    print(f"\n... starting heudiconv for subjects: {' '.join(ids)}")
    status = stream(cmd, env, cwd="/" if cfg.container else None)
    if status != 0:
        print(f"\nERROR: heudiconv failed (exit code {status}) - check output above.")
    else:
        print(f"\n... ok, conversion completed! Processed subjects: {' '.join(ids)}")
    return status


def _confirm(question: str) -> bool:
    return input(f"{question} [ENTER = yes, 1 = quit]: ").strip() != "1"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert dicoms to a BIDS dataset with heudiconv (no session structure).")
    parser.add_argument("config", help="config file, e.g. configs/myproject.py")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--subjects", nargs="+", help="subject ids, with or without 'sub-'")
    group.add_argument("--all", action="store_true", help="all sessions found below dicom_root")
    parser.add_argument("--root", help="overrides root from the config")
    parser.add_argument("--outdir", help="overrides bids_dir from the config")
    parser.add_argument("--heuristic", help="overrides bids_heuristic from the config")
    parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation (e.g. in batch jobs)")
    args = parser.parse_args(argv)

    print("\n" + "=" * 85)
    print("Conversion script to create a BIDS conform nifti dataset from DICOMS (via heudiconv).")
    print("=" * 85 + "\n")

    cfg = load_config(args.config, **({"root": args.root} if args.root else {}))
    subjects = find_sessions(cfg) if args.all else args.subjects
    outdir = os.path.abspath(cfg.path(args.outdir or cfg.bids_dir or ""))
    heuristic = args.heuristic or cfg.bids_heuristic
    if not (args.outdir or cfg.bids_dir) or not heuristic:
        parser.error("bids_dir and bids_heuristic must be set in the config (or via --outdir / --heuristic).")

    try:
        subject_ids(cfg, subjects)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"DICOM template: {cfg.path(cfg.dcm_pattern)}")
    print(f"Output dir:     {outdir}")
    print(f"Heuristic:      {heuristic}")
    print(f"Container:      {cfg.container or 'none (installed heudiconv)'}"
          + (f"  ({cfg.container_image})" if cfg.container and not cfg.container.endswith(".sif") else ""))
    print(f"Subjects:       {' '.join(subjects)}\n")

    if not args.yes:
        if not _confirm("Continue with these settings?"):
            sys.exit(1)
        if os.path.isdir(outdir) and os.listdir(outdir) and not _confirm("Output directory exists and is not empty. Continue?"):
            sys.exit(1)

    sys.exit(convert(cfg, subjects, outdir=outdir, heuristic=heuristic))


if __name__ == "__main__":
    main()
