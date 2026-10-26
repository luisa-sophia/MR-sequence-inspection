"""
Template config. Copy it to e.g. configs/myproject.py and fill it in.
Everything in configs/ except this template is gitignored.

All public variables are read as config options (unknown names raise an error),
so prefix helper variables with '_'.
"""

identifier = "PROJECT1"

# Prefix for all relative paths below (e.g. where the lab drive is mounted).
# Can also be left as None here and passed in the notebook: load_config(..., root="...")
root = None

# === DICOM input (relative to root, or absolute)
dicom_root = "path/to/dicom/root"
# heudiconv template, must contain {subject}
dcm_pattern = f"{dicom_root}/{{subject}}/SCANS/*/DICOM/*.dcm"
# a folder is a session if it contains this subfolder (None: every subfolder of dicom_root)
session_marker = "SCANS"
ignore = ["pilot"]       # skip folders containing these strings (case insensitive)
exclude_sessions = []

# === output, relative to the notebook folder (gitignored)
output_dir = "output"
drop_columns = ["patient_age", "patient_sex"]

# === modality rules, checked against the dicom series_description
# include: all substrings must be present, exclude: none may be present.
# A rule can also be a function, e.g. lambda x: "t1" in x.lower()
# First matching rule wins. Remove/add entries as you like.
modalities = {
    "T1w":  {"include": ["t1", "UNI", "0.75"]},
    "T2w":  {"include": ["t2"]},
    "fMRI": {"include": ["face", "ap"], "exclude": ["SBRef"]},
    "DWI":  {"include": ["resolve_COR"]},
    "DTI":  {"include": ["dti"]},
    "MRE":  {"include": ["tomomre"]},
}

# optional: set to None if not needed
fmri_blocks = {
    "modality": "fMRI",
    "trs_per_block": 418,
    "threshold": 0.4,    # a run counts if it has at least 40% of a block
}

# optional: data that heudiconv doesn't see, found via glob (relative to root).
# session_level: the session id is the folder name N levels above the match.
# Set to {} if not needed.
file_checks = {
    "Spectro": {"glob": "path/to/spectro/*/*/MRS-data", "session_level": 2},
}

# optional: sort order of the sessions (default: alphabetical)
# sort_key = lambda session: session.split("7T")[-1]
