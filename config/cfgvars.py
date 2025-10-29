"""
Configuration Variables Module

Purpose:
    Define configuration variables such as data paths and constants.
    Paths can be specified relative to a dynamic root, which is set during
    initialization via `config.core.initialise_config()`.

    Any variable prefixed with `_REL_` is considered a relative path and will
    be automatically joined with the root directory passed during configuration.

Author: Luisa Seckinger
Date: 2025-10-29
"""
from typing import Callable, Dict
import os

IDENTIFIER="PROJECT1"

# === MR data details
# Root to dicoms, relative from lab drive
_REL_DICOM_ROOT_PATH = "this/is/a/path/to/root"
# Spectroscopy path template, relative to lab drive
_REL_SPECTRO_TEMPLATE = f"ishere/*/*/MRS-data"
#file pattern to dicoms, relative to lab drive. Mind that heudiconv requires the placeholder '{subject}' in the pattern. 
_REL_DCM_PATTERN=f"{_REL_DICOM_ROOT_PATH}/{{subject}}/SCANS/*/DICOM/*.dcm"

# Number of TRs that define one fMRI block
NUM_TRS_ONE_FMRI_BLOCK = 418
# At least 40% of one block needs to be present for the run to be considered
FMRI_BLOCK_THRESHOLD = 0.4

# ===== MODALITY SORTING RULES =====
# These rules are used to classify scans into modalities 
# this is done by checking the dicom seriesdescription for (non)matching strings
# Rules are MUTUALLY EXCLUSIVE!
MODALITY_CONDITIONS: Dict[str, Callable[[str], bool]] = {
    "T1w": lambda x: "t1" in x and "UNI" in x and "0.75" in x,
    "T2w": lambda x: "t2" in x,
    "fMRI": lambda x: "face" in x and "ap" in x and not "SBRef" in x,
    "DWI": lambda x: "resolve_COR" in x,
    "DTI": lambda x: "dti" in x
}

# Name of the dicominfo.tsv file after excluding sensitive columns (original name: dicominfo.tsv)
DICOMINFO_TSV_NAME = "dicominfo_mod.tsv"

# ===== EXCLUSIONS =====
#exclude scan ids from the sequence info overview sheet
EXCLUDE_SCAN_IDS = []

CONFIG_FILENAME = os.path.abspath(__file__)