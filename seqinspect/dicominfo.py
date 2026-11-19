"""
Step 1: find sessions, run heudiconv on them and clean the resulting dicominfo.tsv files.

Author: Luisa Seckinger
"""
import ast
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


def check_patient_names(cfg: Config, sessions: list[str]):
    """
    Compare folder names with the dicom patient_name (reads the first dicom per session).
    Apart from naming conflicts, folders should be renamed to match the patient_name.
    """
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


# --- running heudiconv (installed or in an apptainer container) --------------

def heuristic_path(heuristic: str) -> str:
    """A heuristic .py file becomes an absolute path, a built-in heuristic name (e.g. 'convertall') stays."""
    if heuristic.endswith(".py"):
        if not os.path.isfile(heuristic):
            raise FileNotFoundError(f"The specified heuristic file does not exist: '{heuristic}'")
        return os.path.abspath(heuristic)
    return heuristic


def _find_sif(cfg: Config) -> str:
    """
    The container image file. cfg.container is a .sif file (used as it is), or a folder:
    then heudiconv_<version>.sif for the version in cfg.container_image (pulled if missing).
    """
    container = cfg.path(cfg.container)
    if container.endswith(".sif"):
        sif = container
    else:
        version = cfg.container_image.rsplit(":", 1)[-1] if ":" in cfg.container_image.split("/")[-1] else "latest"
        sif = os.path.join(container, f"heudiconv_{version}.sif")
    if not os.path.isfile(sif):
        print(f"No heudiconv .sif file found - pulling {cfg.container_image} ...")
        subprocess.run(["apptainer", "pull", sif, cfg.container_image], check=True)
        print(f"Pulled image to: {sif}")
    return sif


def _version_line(cmd: list[str]) -> str:
    """First output line of a version command (or why it failed)."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"unknown ({e})"
    lines = [l.strip() for l in (out.stdout + out.stderr).splitlines() if l.strip()]
    return next((l for l in lines if "version" in l.lower()), lines[0] if lines else "unknown")


def print_versions(cfg: Config):
    """Print the heudiconv and dcm2niix versions that will be used (installed or in the container)."""
    if cfg.container:
        sif = _find_sif(cfg)
        print(f"Container:      {sif}")
        heudiconv = ["apptainer", "exec", "--cleanenv", sif, "heudiconv"]
        dcm2niix = ["apptainer", "exec", "--cleanenv", sif, "dcm2niix"]
    else:
        print("Container:      none (installed heudiconv)")
        heudiconv, dcm2niix = ["heudiconv"], ["dcm2niix"]
    print(f"heudiconv:      {_version_line(heudiconv + ['--version'])}")
    print(f"dcm2niix:       {_version_line(dcm2niix + ['--version'])}")


def heudiconv_cmd(cfg: Config, bind: list[str], extra_env: dict | None = None) -> tuple[list[str], dict]:
    """
    Command prefix + environment for heudiconv. With a container, the folders in `bind` are mounted
    and `extra_env` is passed into the container. All paths passed to heudiconv must then be absolute.
    """
    # NO_ET: skip heudiconv's online version check (etelemetry), it only produces warnings
    extra_env = {"NO_ET": "1", **(extra_env or {})}
    env = {**os.environ, **extra_env}
    if not cfg.container:
        return ["heudiconv"], env

    sif = _find_sif(cfg)
    cmd = ["apptainer", "run", "--cleanenv"]
    for key, value in {"PYTHONDONTWRITEBYTECODE": "1", **extra_env}.items():
        cmd += ["--env", f"{key}={value}"]
    if cfg.container_tmp:
        tmp = os.path.abspath(cfg.path(cfg.container_tmp))
        work = os.path.join(tmp, "work")
        os.makedirs(os.path.join(tmp, "tmp"), exist_ok=True)
        os.makedirs(work, exist_ok=True)
        env.update(APPTAINER_TMPDIR=os.path.join(tmp, "tmp"), APPTAINER_CACHEDIR=tmp)
        cmd += ["-H", work]
        bind = bind + [tmp]
    cmd += ["--bind", ",".join(f"{p}:{p}" for p in dict.fromkeys(bind)), sif]
    return cmd, env


def heudiconv_binds(cfg: Config, *paths: str, pattern: str | None = None) -> list[str]:
    """Folders to mount in the container: the fixed part of the dicom pattern, plus the given files/folders."""
    pattern = cfg.path(pattern or cfg.dcm_pattern)
    dicom_base = os.path.dirname(pattern.split("{")[0])
    binds = [os.path.abspath(dicom_base)]
    for p in paths:
        if p and os.path.isabs(p):
            binds.append(p if os.path.isdir(p) else os.path.dirname(p))
    return binds


def stream(cmd: list[str], env: dict, cwd: str | None = None) -> int:
    """Run a command and print its output live. Returns the exit code."""
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, cwd=cwd)
    for line in iter(process.stdout.readline, ""):
        print(line.rstrip())
        sys.stdout.flush()
    return process.wait()


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
