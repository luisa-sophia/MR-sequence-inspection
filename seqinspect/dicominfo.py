"""
Step 1: run heudiconv on the sessions (info files only, no conversion) and clean the resulting dicominfo.tsv files.

Author: Luisa Seckinger
"""
import ast
import glob
import os

from .config import Config
from .heudiconv import heudiconv_binds, heudiconv_cmd, heuristic_path, print_versions, stream
from .sessions import has_dicoms, session_pattern

DICOMINFO_NAME = "dicominfo_mod-{subject}.tsv"  # cleaned file, {subject} = session id


DICOMINFO_GLOB = DICOMINFO_NAME.replace("{subject}", "*")


def find_dicominfo_files(cfg: Config, pattern: str = "dicominfo*.tsv") -> dict[str, str]:
    """Return {session_id: path} for all dicominfo files in out_dir (.heudiconv/<session>/info/...)."""
    paths = glob.glob(f"**/{pattern}", root_dir=cfg.out_dir, recursive=True, include_hidden=True)
    found = {}
    for p in paths:
        full = os.path.join(cfg.out_dir, p)
        found[os.path.basename(os.path.dirname(os.path.dirname(full)))] = full
    return found


def run_heudiconv(cfg: Config, sessions: list[str], force: bool = False, dryrun: bool = False) -> list[str]:
    """
    Run heudiconv (no conversion, only the info files) for every session that has no dicominfo yet.
    Sessions for which the dcm_pattern matches no files are skipped and returned.
    """
    if "{subject}" not in cfg.dcm_pattern:
        raise ValueError("dcm_pattern must contain the placeholder '{subject}'.")
    os.makedirs(cfg.out_dir, exist_ok=True)
    heuristic = heuristic_path(cfg.info_heuristic)
    if not dryrun:
        print_versions(cfg)
        print()
    prefix_cmd, env = heudiconv_cmd(cfg, heudiconv_binds(cfg, cfg.out_dir, heuristic))
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
        cmd = prefix_cmd + ["-d", os.path.abspath(cfg.path(cfg.dcm_pattern)), "-s", session,
                            "-o", cfg.out_dir, "-c", "none", "-f", heuristic]
        if dryrun:
            print(f"{prefix} --> DRYRUN: {' '.join(cmd)}")
            continue
        print(f"{prefix} --> RUNNING HEUDICONV")
        # cwd "/": the current dir may not exist inside the container
        if stream(cmd, env, cwd="/" if cfg.container else None) != 0:
            print(f"--- heudiconv FAILED for session {session} ---")

    if no_dicoms:
        print(f"\nWARNING: {len(no_dicoms)} sessions skipped, no dicoms matched the dcm_pattern: {no_dicoms}")
    print("\n... all sessions processed.")
    return no_dicoms


def _from_custom(custom_val, key):
    """Read TR/TE from the 'custom' column written by heuristics/convertall_enhancedcm_mod.py."""
    try:
        return dict(ast.literal_eval(custom_val)).get(key)
    except Exception:
        return None


def clean_dicominfo(cfg: Config):
    """
    Drop sensitive columns from the raw dicominfo.tsv files and save them as dicominfo_mod-<session>.tsv.
    For enhanced dicoms (custom heuristic), TR/TE are copied from the 'custom' column where heudiconv wrote -1.
    """
    import pandas as pd

    for session, path in find_dicominfo_files(cfg, "dicominfo.tsv").items():
        df = pd.read_csv(path, sep="\t", encoding="latin-1", on_bad_lines="skip")
        msg = ""
        if "custom" in df.columns:
            n = {"TR": 0, "TE": 0}
            for idx, row in df.iterrows():
                for key in n:
                    value = _from_custom(row["custom"], key)
                    if value is not None and row[key] == -1:
                        df.at[idx, key] = value
                        n[key] += 1
            if any(n.values()):
                msg = f"  (enhanced DICOM: TR extracted {n['TR']}x, TE extracted {n['TE']}x)"
        df = df.drop(columns=cfg.drop_columns, errors="ignore")
        df.to_csv(os.path.join(os.path.dirname(path), DICOMINFO_NAME.format(subject=session)), sep="\t", index=False)
        os.remove(path)
        print(f"cleaned {session}{msg}")


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
