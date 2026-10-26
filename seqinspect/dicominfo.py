"""
Step 1: find sessions, run heudiconv on them and clean the resulting dicominfo.tsv files.

Author: Luisa Seckinger
"""
import glob
import os
import subprocess
import sys

import pandas as pd

from .config import Config

DICOMINFO_NAME = "dicominfo_mod-{subject}.tsv"  # cleaned file, {subject} = session id
DICOMINFO_GLOB = DICOMINFO_NAME.replace("{subject}", "*")


def _is_ignored(cfg: Config, name: str) -> bool:
    if cfg.ignore_hidden and name.startswith("."):
        return True
    return any(s.lower() in name.lower() for s in cfg.ignore)


def find_sessions(cfg: Config) -> list[str]:
    """Return the session ids (folder names) found below dicom_root."""
    dicom_root = cfg.path(cfg.dicom_root)
    if not os.path.isdir(dicom_root):
        raise FileNotFoundError(f"dicom_root does not exist: '{dicom_root}'")

    sessions = []
    if cfg.session_marker is None:
        sessions = [d for d in os.listdir(dicom_root)
                    if os.path.isdir(os.path.join(dicom_root, d)) and not _is_ignored(cfg, d)]
    else:
        for root, dirs, _ in os.walk(dicom_root, topdown=True):
            dirs[:] = [d for d in dirs if not _is_ignored(cfg, d)]
            if cfg.session_marker in dirs:
                sessions.append(os.path.basename(root))
                dirs.remove(cfg.session_marker)  # don't walk into the scans

    sessions = [s for s in sessions if s not in cfg.exclude_sessions]
    return sorted(sessions, key=cfg.sort_key)


def find_dicominfo_files(cfg: Config, pattern: str = "dicominfo*.tsv") -> dict[str, str]:
    """Return {session_id: path} for all dicominfo files in out_dir (.heudiconv/<session>/info/...)."""
    paths = glob.glob(f"**/{pattern}", root_dir=cfg.out_dir, recursive=True, include_hidden=True)
    found = {}
    for p in paths:
        full = os.path.join(cfg.out_dir, p)
        found[os.path.basename(os.path.dirname(os.path.dirname(full)))] = full
    return found


def session_pattern(cfg: Config, session: str) -> str:
    """The dcm_pattern filled in for one session."""
    return cfg.path(cfg.dcm_pattern.replace("{subject}", session))


def has_dicoms(cfg: Config, session: str) -> bool:
    """True if the dcm_pattern matches at least one file for this session (stops at the first match)."""
    return next(glob.iglob(session_pattern(cfg, session)), None) is not None


def run_heudiconv(cfg: Config, sessions: list[str], force: bool = False) -> list[str]:
    """
    Run heudiconv (no conversion, only the info files) for every session that has no dicominfo yet.
    Sessions for which the dcm_pattern matches no files are skipped and returned.
    """
    if "{subject}" not in cfg.dcm_pattern:
        raise ValueError("dcm_pattern must contain the placeholder '{subject}'.")
    os.makedirs(cfg.out_dir, exist_ok=True)
    done = find_dicominfo_files(cfg)
    no_dicoms = []

    for i, session in enumerate(sessions):
        prefix = f"=== SESSION ({i+1}/{len(sessions)}): {session:>20s}"
        if session in done and not force:
            print(f"{prefix} --> dicominfo exists, skipping.")
            continue
        # e.g. a session found in a deeper subfolder doesn't fit the dcm_pattern
        if not has_dicoms(cfg, session):
            print(f"{prefix} --> NO DICOMS found with pattern '{session_pattern(cfg, session)}', skipping.")
            no_dicoms.append(session)
            continue
        cmd = ["heudiconv", "-d", cfg.path(cfg.dcm_pattern), "-s", session,
               "-o", cfg.out_dir, "-c", "none", "-f", "convertall"]
        print(f"{prefix} --> RUNNING HEUDICONV")
        # NO_ET: skip heudiconv's online version check (etelemetry), it only produces warnings
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   env={**os.environ, "NO_ET": "1"})
        for line in iter(process.stdout.readline, ""):
            print(line.rstrip())
            sys.stdout.flush()
        if process.wait() != 0:
            print(f"--- heudiconv FAILED for session {session} with exit code {process.returncode} ---")

    if no_dicoms:
        print(f"\nWARNING: {len(no_dicoms)} sessions skipped, no dicoms matched the dcm_pattern: {no_dicoms}")
    print("\n... all sessions processed.")
    return no_dicoms


def clean_dicominfo(cfg: Config):
    """Drop sensitive columns from the raw dicominfo.tsv files and save them as dicominfo_mod-<session>.tsv."""
    for session, path in find_dicominfo_files(cfg, "dicominfo.tsv").items():
        df = pd.read_csv(path, sep="\t", encoding="latin-1", on_bad_lines="skip")
        df = df.drop(columns=cfg.drop_columns, errors="ignore")
        df.to_csv(os.path.join(os.path.dirname(path), DICOMINFO_NAME.format(subject=session)), sep="\t", index=False)
        os.remove(path)
        print(f"cleaned {session}")


def check_consistency(cfg: Config, sessions: list[str]) -> bool:
    """Compare found sessions with existing dicominfo files."""
    infos = set(find_dicominfo_files(cfg, DICOMINFO_GLOB))
    no_info = sorted(set(sessions) - infos)
    no_data = sorted(infos - set(sessions))
    if no_info:
        print(f"Sessions without dicominfo: {no_info}")
    if no_data:
        print(f"dicominfo without session data: {no_data}")
    if not no_info and not no_data:
        print("All sessions have a dicominfo file and vice versa.")
    return not no_info and not no_data
