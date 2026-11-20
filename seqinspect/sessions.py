"""
Finding the session folders with the dcm_pattern and checking them against the dicom headers.

Author: Luisa Seckinger
"""
import glob
import os

from .config import Config


def _is_ignored(cfg: Config, name: str) -> bool:
    if cfg.ignore_hidden and name.startswith("."):
        return True
    return any(s.lower() in name.lower() for s in cfg.ignore)


def find_sessions(cfg: Config) -> list[str]:
    """
    Return the session ids found with the dcm_pattern: the folders at the position of '{subject}'
    (e.g. dicom_root/<session>/SCANS/...) for which the pattern finds at least one dicom.
    """
    pattern = cfg.path(cfg.dcm_pattern)
    if "{subject}" not in pattern:
        raise ValueError("dcm_pattern must contain the placeholder '{subject}'.")
    # the folder level with {subject}, e.g. "sub-{subject}" -> prefix "sub-", suffix ""
    before, after = pattern.split("{subject}", 1)
    parent, prefix = os.path.split(before)
    suffix = after.split(os.sep, 1)[0]
    if not os.path.isdir(parent):
        raise FileNotFoundError(f"Folder with the sessions does not exist: '{parent}'")

    candidates = [d[len(prefix):len(d) - len(suffix)] for d in os.listdir(parent)
                  if d.startswith(prefix) and d.endswith(suffix) and len(d) > len(prefix) + len(suffix)
                  and os.path.isdir(os.path.join(parent, d)) and not _is_ignored(cfg, d)]
    candidates = [s for s in candidates if s not in cfg.exclude_sessions]

    sessions, no_dicoms = [], []
    for s in candidates:
        (sessions if has_dicoms(cfg, s) else no_dicoms).append(s)
    if no_dicoms:
        print(f"{len(no_dicoms)} folder(s) skipped, no dicoms matched the dcm_pattern: {sorted(no_dicoms)}")
    return sorted(sessions, key=cfg.sort_key)


def session_pattern(cfg: Config, session: str) -> str:
    """The dcm_pattern filled in for one session."""
    return cfg.path(cfg.dcm_pattern.replace("{subject}", session))


def has_dicoms(cfg: Config, session: str) -> bool:
    """True if the dcm_pattern matches at least one file for this session (stops at the first match)."""
    return next(glob.iglob(session_pattern(cfg, session)), None) is not None


def check_patient_names(cfg: Config, sessions: list[str]):
    """
    Compare folder names with the dicom patient_name (reads the first dicom per session).
    Apart from naming conflicts, folders should be renamed to match the patient_name.
    """
    import pandas as pd
    import pydicom

    rows = []
    for session in sessions:
        first = next(glob.iglob(session_pattern(cfg, session)), None)
        if first is None:
            print(f"Skipping folder '{session}': no match for '{session_pattern(cfg, session)}'.")
            continue
        patient_name = str(pydicom.dcmread(first, stop_before_pixels=True).PatientName).replace("^", "")
        rows.append({"foldername": session, "patient_name": patient_name, "is match?": session == patient_name})
    return pd.DataFrame(rows)
