"""
Config for sequence inspection.

A Config can be created in three ways:

    cfg = load_config("configs/myproject.py")                    # from a config file (.py or .yaml)
    cfg = load_config("configs/myproject.py", root="/some/root")  # config file + overrides
    cfg = Config(root="/some/root", dicom_root="...", ...)          # quick inline config

Relative paths (dicom_root, dcm_pattern, file_checks globs, bids_dir) are joined with `root`.
Absolute paths are used as they are, `root` can then be left empty.
Instead of `root`, a `root_marker` file can be given: the root is then the first folder
(going upwards from the current dir) that contains this file, e.g. '.drive_root.txt' on the lab drive.

Author: Luisa Seckinger
"""
import os
import re
import runpy
import shutil
import sys
import types
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Callable

import yaml


@dataclass
class Config:
    # prefix for all relative paths below (e.g. the lab drive mount point)
    root: str | None = None
    # alternative to root: name of a marker file, root = first folder above the current dir containing it
    root_marker: str | None = None
    # used as prefix for output file names
    identifier: str = "PROJECT"

    # === DICOM input
    # folder that is searched for sessions
    dicom_root: str = ""
    # heudiconv dicom template, must contain the placeholder '{subject}'.
    # Sessions = the folders at the position of {subject} in which the pattern finds dicoms
    dcm_pattern: str = ""
    # skip folders whose name contains one of these strings (case insensitive)
    ignore: list[str] = field(default_factory=lambda: ["pilot"])
    ignore_hidden: bool = True
    exclude_sessions: list[str] = field(default_factory=list)

    # === output (relative to the current working dir, NOT to root, unless output_in_root=True)
    output_dir: str = "output"
    output_in_root: bool = False
    # columns removed from the dicominfo.tsv files
    drop_columns: list[str] = field(default_factory=lambda: ["patient_age", "patient_sex"])

    # === heudiconv
    # heuristic for the dicominfo step: "convertall" or a path to a .py file (relative to the notebook folder)
    info_heuristic: str = "convertall"
    # apptainer image (.sif file, or a folder with heudiconv*.sif in it, pulled if missing). None: installed heudiconv
    container: str | None = None
    # image that is pulled into the container folder. Pin a version (not 'latest') so results are reproducible
    container_image: str = "docker://nipy/heudiconv:1.5.1"
    # apptainer cache / work folder (only used with container)
    container_tmp: str | None = None

    # === BIDS conversion (optional, seqinspect.convert)
    bids_dir: str | None = None
    # heuristic .py for the conversion (relative to the notebook folder, or absolute)
    bids_heuristic: str | None = None
    # dicom template for the conversion (default: dcm_pattern). Can contain '{session}' besides '{subject}',
    # e.g. "sub-{subject}_ses-{session}/*/SCANS/*/DICOM/*.dcm" -> one heudiconv run per session (--ses)
    bids_dcm_pattern: str | None = None
    # additional input format for subject(+session) ids, with named groups, e.g. r"^(?P<subject>\d+)(?P<session>[A-Za-z])$"
    # for "01B". "sub-01" / "sub-01_ses-B" always work.
    short_id_regex: str | None = None
    # environment variables for heudiconv, e.g. {"HEUDICONV_TASKMAP": "/path/to/task_map.tsv"} (read by the heuristic).
    # With a container, the folders of existing file paths in here are mounted.
    bids_env: dict = field(default_factory=dict)

    # === classification
    # name -> rule. A rule is one of:
    #   {"include": [...], "exclude": [...]}  substrings of the series_description
    #   "regex" or ["regex", ...]             case insensitive, any of them anywhere in the series_description
    #   a python callable str -> bool
    modalities: dict = field(default_factory=dict)
    # True: first matching rule wins. False: a scan can count for several modalities
    exclusive_rules: bool = True
    # False: 1/0 per modality. True: number of matching scans
    count_scans: bool = False
    # optional, e.g. {"modality": "fMRI", "trs_per_block": 418, "threshold": 0.4}
    fmri_blocks: dict | None = None
    # optional checks for data heudiconv does not see, e.g. spectroscopy:
    # name -> {"glob": "...", "session_level": 2}  (session id = folder name N levels above the match)
    file_checks: dict = field(default_factory=dict)
    # optional python sort key for session ids (default: alphabetical)
    sort_key: Callable[[str], object] | None = None

    def __post_init__(self):
        if self.root is None and self.root_marker:
            self.root = str(find_root_with_marker(Path.cwd(), self.root_marker))

    # ---------------------------------------------------------------------
    def path(self, p: str) -> str:
        """Resolve a path from the config: absolute paths stay, relative ones are joined with root."""
        p = os.path.expanduser(p)
        if os.path.isabs(p) or not self.root:
            return os.path.normpath(p)
        return os.path.normpath(os.path.join(os.path.expanduser(self.root), p))

    @property
    def out_dir(self) -> str:
        output_dir = self.path(self.output_dir) if self.output_in_root else self.output_dir
        return os.path.abspath(os.path.join(output_dir, self.identifier))

    def show(self):
        print(f"=== Config '{self.identifier}' " + "=" * 50)
        for f in fields(self):
            print(f"{f.name:18} = {getattr(self, f.name)}")
        print(f"{'-> dicom_root':18} = {self.path(self.dicom_root)}  (exists: {os.path.isdir(self.path(self.dicom_root))})")
        print(f"{'-> out_dir':18} = {self.out_dir}")
        if self.container:
            print(f"{'-> apptainer':18} = {find_apptainer() or 'NOT FOUND'}")
        print("=" * 72)
        if self.container and not find_apptainer():
            print(f"WARNING: {APPTAINER_MISSING}")


APPTAINER_MISSING = (
    "'container' is set, but neither 'apptainer' nor 'singularity' is found in PATH, heudiconv can't run. "
    "Run it where apptainer is installed (not inside a container, e.g. a workbench), after 'module load apptainer' "
    "if needed. Or set container = None to use an installed heudiconv.")


def find_apptainer() -> str | None:
    """Path of the apptainer executable (or singularity, its older name), None if neither is in PATH."""
    return shutil.which("apptainer") or shutil.which("singularity")


def find_root_with_marker(start: Path, marker: str) -> Path:
    for p in [start] + list(start.parents):
        if (p / marker).exists():
            return p
    raise FileNotFoundError(f"Marker '{marker}' indicating root level of drive not found above '{start}'.")


def _read_py(path: str) -> dict:
    """
    Run a .py config and collect its public variables (helpers can be hidden with a leading '_').
    The config's folder is importable while it runs, so a config can import shared values from a file next to it.
    """
    config_dir = os.path.dirname(os.path.abspath(path))
    sys.path.insert(0, config_dir)
    try:
        values = runpy.run_path(path)
    finally:
        sys.path.remove(config_dir)
    return {k: v for k, v in values.items()
            if not k.startswith("_") and not isinstance(v, types.ModuleType)}


def load_config(path: str | None = None, **overrides) -> Config:
    """Load a config file (.py or .yaml, optional) and apply keyword overrides on top."""
    values = {}
    if path is not None:
        if path.endswith(".py"):
            values = _read_py(path)
        else:
            with open(path) as f:
                values = yaml.safe_load(f) or {}
    values.update(overrides)
    if "session_marker" in values:
        values.pop("session_marker")
        print(f"Note: 'session_marker' is no longer used (sessions are found with the dcm_pattern), "
              f"you can remove it from '{path}'.")

    known = {f.name for f in fields(Config)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"Unknown config keys: {sorted(unknown)}. Allowed: {sorted(known)}")
    return Config(**values)


def matches(rule, series_description: str) -> bool:
    """Check a series description against one modality rule."""
    if callable(rule):
        return bool(rule(series_description))
    if isinstance(rule, str):
        rule = [rule]
    if isinstance(rule, list):
        return any(re.search(p, series_description, re.IGNORECASE) for p in rule)
    include = rule.get("include", [])
    exclude = rule.get("exclude", [])
    return all(s in series_description for s in include) and not any(s in series_description for s in exclude)
