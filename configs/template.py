"""
Template config. Copy it to e.g. configs/myproject.py and fill it in.
Everything in configs/ except this template and the shared MRE configs is gitignored.

All public variables are read as config options (unknown names raise an error),
so prefix helper variables with '_'.
"""
from container_config import container as _container, container_tmp as _container_tmp, container_image as _container_image
identifier = "PROJECT1"

# Prefix for all relative paths below (e.g. where the lab drive is mounted).
# Can also be left as None here and passed in the notebook: load_config(..., root="...")
root = None
# Or: find the root automatically, it is the first folder above the notebook folder containing this file
# root_marker = ".drive_root.txt"

# === DICOM input (relative to root, or absolute)
dicom_root = "path/to/dicom/root"
# heudiconv template, must contain {subject}.
# Sessions = the folders at the position of {subject} in which the pattern finds dicoms
dcm_pattern = f"{dicom_root}/{{subject}}/SCANS/*/DICOM/*.dcm"
ignore = ["pilot", "__MACOSX"]  # skip folders containing these strings (case insensitive)
exclude_sessions = []

# === output, relative to the notebook folder (gitignored)
output_dir = "output"
# output_in_root = True   # output_dir is relative to root instead (e.g. a summary folder on the drive)
drop_columns = ["patient_age", "patient_sex"]

# === heudiconv
# heuristic for the dicominfo step. For enhanced dicoms (XB10 platform) use the modified one,
# it extracts TR/TE which heudiconv misses for this format:
# info_heuristic = "heuristics/convertall_enhancedcm_mod.py"
info_heuristic = "convertall"
# run heudiconv in apptainer instead of the installed one: .sif file or folder with heudiconv*.sif (pulled if missing)
container = None
container_tmp = None     # apptainer cache / work folder
# image pulled into the container folder as heudiconv_<version>.sif. Keep a fixed version (not 'latest'),
# a newer heudiconv / dcm2niix can give slightly different BIDS output
container_image = "docker://nipy/heudiconv:1.5.1"

# === BIDS conversion (optional): python -m seqinspect.convert configs/myproject.py --all
bids_dir = None          # e.g. "path/to/BIDS" (relative to root, or absolute)
bids_heuristic = None    # e.g. "heuristics/heuristic_myproject.py"
# dicom template for the conversion (default: dcm_pattern). With '{session}', heudiconv runs once per session:
# bids_dcm_pattern = f"{dicom_root}/sub-{{subject}}_ses-{{session}}/*/SCANS/*/DICOM/*.dcm"
# extra input format besides sub-01_ses-B, e.g. "01B":
# short_id_regex = r"^(?P<subject>\d+)(?P<session>[A-Za-z])$"
# environment variables for the heuristic (folders of file paths are mounted in the container):
# bids_env = {"HEUDICONV_TASKMAP": "path/to/task_map.tsv"}

# === modality rules, checked against the dicom series_description
# include: all substrings must be present, exclude: none may be present.
# A rule can also be a regex string / list of regex strings (case insensitive, any of them),
# e.g. "^(?!.*fmre).*mre_", or a function, e.g. lambda x: "t1" in x.lower()
modalities = {
    "T1w":  {"include": ["t1", "UNI", "0.75"]},
    "T2w":  {"include": ["t2"]},
    "fMRI": {"include": ["face", "ap"], "exclude": ["SBRef"]},
    "DWI":  {"include": ["resolve_COR"]},
    "DTI":  {"include": ["dti"]},
    "MRE":  {"include": ["tomomre"]},
}
exclusive_rules = True   # True: first matching rule wins. False: a scan can count for several modalities
count_scans = False      # False: 1/0 per modality. True: number of matching scans

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
