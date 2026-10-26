"""
Config for sequence inspection.

A Config can be created in three ways:

    cfg = load_config("configs/myproject.py")                    # from a config file (.py or .yaml)
    cfg = load_config("configs/myproject.py", root="/some/root")  # config file + overrides
    cfg = Config(root="/some/root", dicom_root="...", ...)          # quick inline config

Relative paths (dicom_root, dcm_pattern, file_checks globs) are joined with `root`.
Absolute paths are used as they are, `root` can then be left empty.

Author: Luisa Seckinger
"""
import os
import runpy
import types
from dataclasses import dataclass, field, fields
from typing import Callable

import yaml


@dataclass
class Config:
    # prefix for all relative paths below (e.g. the lab drive mount point)
    root: str | None = None
    # used as prefix for output file names
    identifier: str = "PROJECT"

    # === DICOM input
    # folder that is searched for sessions
    dicom_root: str = ""
    # heudiconv dicom template, must contain the placeholder '{subject}'
    dcm_pattern: str = ""
    # a folder is a session if it contains this subfolder (None: every direct subfolder of dicom_root is a session)
    session_marker: str | None = "SCANS"
    # skip folders whose name contains one of these strings (case insensitive)
    ignore: list[str] = field(default_factory=lambda: ["pilot"])
    ignore_hidden: bool = True
    exclude_sessions: list[str] = field(default_factory=list)

    # === output (relative to the current working dir, NOT to root)
    output_dir: str = "output"
    # columns removed from the dicominfo.tsv files
    drop_columns: list[str] = field(default_factory=lambda: ["patient_age", "patient_sex"])

    # === classification
    # name -> rule. A rule is either {"include": [...], "exclude": [...]} (substrings of the
    # series_description) or a python callable str -> bool. First matching rule wins.
    modalities: dict = field(default_factory=dict)
    # optional, e.g. {"modality": "fMRI", "trs_per_block": 418, "threshold": 0.4}
    fmri_blocks: dict | None = None
    # optional checks for data heudiconv does not see, e.g. spectroscopy:
    # name -> {"glob": "...", "session_level": 2}  (session id = folder name N levels above the match)
    file_checks: dict = field(default_factory=dict)
    # optional python sort key for session ids (default: alphabetical)
    sort_key: Callable[[str], object] | None = None

    # ---------------------------------------------------------------------
    def path(self, p: str) -> str:
        """Resolve a path from the config: absolute paths stay, relative ones are joined with root."""
        p = os.path.expanduser(p)
        if os.path.isabs(p) or not self.root:
            return os.path.normpath(p)
        return os.path.normpath(os.path.join(os.path.expanduser(self.root), p))

    @property
    def out_dir(self) -> str:
        return os.path.abspath(os.path.join(self.output_dir, self.identifier))

    def show(self):
        print(f"=== Config '{self.identifier}' " + "=" * 50)
        for f in fields(self):
            print(f"{f.name:18} = {getattr(self, f.name)}")
        print(f"{'-> dicom_root':18} = {self.path(self.dicom_root)}  (exists: {os.path.isdir(self.path(self.dicom_root))})")
        print(f"{'-> out_dir':18} = {self.out_dir}")
        print("=" * 72)


def _read_py(path: str) -> dict:
    """Run a .py config and collect its public variables (helpers can be hidden with a leading '_')."""
    return {k: v for k, v in runpy.run_path(path).items()
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

    known = {f.name for f in fields(Config)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"Unknown config keys: {sorted(unknown)}. Allowed: {sorted(known)}")
    return Config(**values)


def matches(rule, series_description: str) -> bool:
    """Check a series description against one modality rule."""
    if callable(rule):
        return bool(rule(series_description))
    include = rule.get("include", [])
    exclude = rule.get("exclude", [])
    return all(s in series_description for s in include) and not any(s in series_description for s in exclude)
