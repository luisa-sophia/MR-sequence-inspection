"""
Platform-independent configuration module for DICOM processing.

This module initializes all necessary paths and settings in a platform-independent way.
All paths are automatically converted to use the correct OS separator.

THIS IS A TEMPLATE

"""

import os
from pathlib import Path
from typing import Callable, Dict


# ==================================================================================
# ==== SETTINGS
# ==================================================================================
#this keyword will help identifying the root drive the lab drive is mounted to
#must be present in the path to this script
__KEYDIR_TO_IDENTIFY_DRIVE= "Work"

IDENTIFIER="PROJECT1"

# === MR data details
# Root to dicoms, relative from lab drive
__REL_DICOM_ROOT_PATH = "this/is/a/path/to/root"
# Spectroscopy path template, relative to lab drive
__REL_SPECTRO_TEMPLATE = f"ishere/*/*/MRS-data"
#file pattern to dicoms, relative to lab drive. Mind that heudiconv requires the placeholder '{subject}' in the pattern. 
__REL_DCM_PATTERN=f"{__REL_DICOM_ROOT_PATH}/{{subject}}/SCANS/*/DICOM/*.dcm"

# Name of the dicominfo.tsv file after excluding sensitive columns (original name: dicominfo.tsv)
DICOMINFO_TSV_NAME = "dicominfo_mod.tsv"

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

# Number of TRs that define one fMRI block
NUM_TRS_ONE_FMRI_BLOCK = 418
# At least 40% of one block needs to be present for the run to be considered
FMRI_BLOCK_THRESHOLD = 0.4


# ===== EXCLUSIONS =====
#exclude scan ids from the sequence info overview sheet
EXCLUDE_SCAN_IDS = []


def combine_paths(*segments) -> str:
    """
    Join multiple path segments into a single path, converting any '/' or '\\' 
    in the segments to the OS-specific separator.

    Args:
        *segments: One or more strings representing parts of a path.

    Returns:
        str: The combined path using the correct OS separator.
    """
    clean_segments = []
    for seg in segments:
        # Replace both types of separators with os.sep
        seg_fixed = seg.replace("/", os.sep).replace("\\", os.sep)
        clean_segments.append(seg_fixed)
    return os.path.join(*clean_segments)

# ===== DYNAMIC PATH DETECTION =====

def initialize_paths():
    """
    Dynamically detect mounted drive and complete relative paths.
    
    Returns:
        dict: Dictionary containing all initialized paths.
    """
    try:
        script_path = os.path.abspath(__file__)
        
        if __KEYDIR_TO_IDENTIFY_DRIVE in script_path:
            drive = script_path.split(__KEYDIR_TO_IDENTIFY_DRIVE)[0]
        else:
            raise ValueError(f"Could not retrieve drive. \
            (Given keyword '{__KEYDIR_TO_IDENTIFY_DRIVE}' not in'{script_path}')")
        
        # Define relative paths and their corresponding variable names
        relative_paths = {
            "DICOM_ROOT_PATH": __REL_DICOM_ROOT_PATH,
            "SPECTRO_TEMPLATE": __REL_SPECTRO_TEMPLATE,
            "DCM_PATTERN": __REL_DCM_PATTERN,
        }
        
        # Combine drive with all relative paths
        paths = {name: combine_paths(drive, rel_path) 
                 for name, rel_path in relative_paths.items()}
        
        # Add drive itself
        paths["DRIVE"] = drive
        
        return paths
    
    except Exception as e:
        raise RuntimeError(f"Failed to initialize paths: {e}")

# Initialize paths when module is imported
_paths = initialize_paths()

# Automatically export all path variables to module namespace
globals().update(_paths)


def verify_paths() -> Dict[str, bool]:
    """
    Verify that critical paths exist.
    
    Returns:
        dict: Dictionary mapping path names to their existence status.
    """
    return {
        "dicom_root_exists": os.path.exists(DICOM_ROOT_PATH),
    }

def get_config_vars():
    """Get only actual config values (strings, numbers, dicts, lists)."""
    import sys, inspect
    
    current_module = sys.modules[__name__]
    allowed_types = (str, int, float, bool, dict, list, tuple)
    
    variables = {
        name: val for name, val in inspect.getmembers(current_module)
        if not name.startswith("_")
        and isinstance(val, allowed_types)
    }
    
    return variables

def print_config_vars(vars=None):
    """
    Print all public configuration variables in this module.
    """

    variables = get_config_vars()
    print("\n=== CONFIG VARIABLES " + "="*60)
    print(f"=== see {os.path.abspath(__file__)}")
    print("="*81)
    if vars:
        for var in vars:
            if var in variables.keys():
                k = var
                v = variables[k]
                print(f"{k:25} = {v}")
            else:
                raise KeyError(f"Variable with name '{var}' not  found config variables.")
    else:
        #print all
        for k, v in variables.items():
            print(f"{k:25} = {v}")
    print("="*81)


if __name__ == "__main__":
    # When run directly, print configuration summary
    print("\nPATH VERIFICATION:")
    verification = verify_paths()
    for path_name, exists in verification.items():
        status = "✓ EXISTS" if exists else "✗ NOT FOUND"
        print(f"  {path_name}: {status}")