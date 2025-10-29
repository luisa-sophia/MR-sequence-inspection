"""
Platform-independent configuration module to set system paths.

This module initializes all necessary paths and settings in a platform-independent way. 
All paths are automatically converted to use the correct OS separator.
This script provides the functionality to import config variables specified in the cfgvars.py.

Variables:
    _REL_*          : relative paths stored in cfgvars.py; will be combined with the BASE_DATA_DIR
    Other constants : stored in cfgvars.py 

Usage:
    import config.core as cfg

    # Option 1: Manual initialisation
    cfg.initialise_config(base_data_dir="/mnt/data/")

    # Option 2: Auto detect (searches along path upward from this file)
    cfg.initialise_config(keyword="myproject1")

    # Then access paths:
    print(cfg.MYPATH)

Author: Luisa Seckinger
Date: 2025-10-29
"""

import os
import re
import warnings
import inspect
from typing import Dict
from . import cfgvars # contains all relative paths (_REL_*) and constants

# =============================================================================
# INTERNAL STATE
# =============================================================================

_vars: Dict[str, str] = {}   # stores all resolved paths and constants after initialization
_initialized = False         # tracks if configuration has been initialised

# =============================================================================
# UTILITIES
# =============================================================================

def combine_paths(*segments: str) -> str:
    """Join multiple path segments into a single path, converting any separators to OS-specific separator."""
    clean_segments = [seg.replace("/", os.sep).replace("\\", os.sep) for seg in segments]
    return os.path.join(*clean_segments)


def __import_vars_from_file() -> tuple[dict, dict]:
    """
    Extract relative paths (_REL_*) and other constants from cfgvars module.

    Returns:
        rel_paths (dict): relative paths with _REL_ prefix removed
        constants (dict): other public variables not starting with _
    """
    rel_paths = {}
    constants = {}
    
    for name, val in vars(cfgvars).items():
        if name.startswith("_REL_") and isinstance(val, str):
            rel_paths[name.replace("_REL_", "")] = val
        elif not name.startswith("_"):  # ignore private/internal vars
            constants[name] = val

    return rel_paths, constants

# =============================================================================
# INITIALISATION
# =============================================================================

def __set_base_data_dir(path: str):
    """Resolve the absolute path of the base directory (if exists)."""
    global _vars, _initialized

    base_data_dir = os.path.abspath(path)
    if not os.path.exists(base_data_dir):
        raise ValueError(f"Base data directory does not exist: '{base_data_dir}'")

    return base_data_dir


def __auto_set_base_data_dir(keyword: str):
    """
    Automatically detect BASE_DATA_DIR by scanning upward from the current working dir's location.
    The directory containing the given keyword is considered the root.
    """

    cwd = os.getcwd()

   # script_path = os.path.abspath(__file__)
    path_parts = cwd.split(os.sep)

    if keyword not in path_parts:
        raise ValueError(
            f"Could not auto-initialise data dir: keyword '{keyword}' not found in cwd '{cwd}'"
        )

    idx = path_parts.index(keyword)
    base_data_dir = os.sep.join(path_parts[:idx + 1])
    return __set_base_data_dir(base_data_dir)


def initialise_config(base_data_dir: str = None, keyword: str = None, force=False, verbose=True):
    """
    Initialise the configuration either manually (with base_data_dir) or automatically from cwd (with keyword).

    Args:
        base_data_dir (str): manually specified root path
        keyword (str): keyword to auto-detect the root folder scanning 
        force (bool): force reinitialisation even if already initialised
        verbose (bool): print info messages

    Sets global _vars dictionary containing resolved paths and constants.
    """
    global _vars, _initialized

    if _initialized and not force:
        if verbose:
            print(
                f"Configuration already initialised with BASE_DATA_DIR: "
                f"'{_vars.get('BASE_DATA_DIR', '<unknown>')}'. Use force=True to reinitialise."
            )
        return

    if base_data_dir:
        base_dir = __set_base_data_dir(base_data_dir)
    elif keyword:
        base_dir = __auto_set_base_data_dir(keyword)
    else:
        raise ValueError("Must provide either base_data_dir or keyword to initialise().")
    
    # Extract both relative paths and constants
    rel_paths, constants = __import_vars_from_file()

    resolved_paths = {
        name: combine_paths(base_dir, rel_path)
        for name, rel_path in rel_paths.items()
    }

    _vars = {"BASE_DATA_DIR": base_dir}
    _vars.update(resolved_paths)
    _vars.update(constants)  # add other constants in the cfgvars.py
    globals().update(_vars)
    _initialized = True

    if verbose:
        print(f"Configuration initialised with base directory: {base_dir}")

# =============================================================================
# INSPECTION & DEBUG UTILITIES
# =============================================================================

def get_config_vars() -> Dict[str, object]:
    """Return all public configuration variables (paths and constants)."""
    import sys, inspect
    current_module = sys.modules[__name__]
    allowed_types = (str, int, float, bool, dict, list, tuple)
    variables = {
        name: val
        for name, val in inspect.getmembers(current_module)
        if not name.startswith("_") and isinstance(val, allowed_types)
    }
    return variables


def __print_vars(variables: Dict[str, object], vars: list | None = None, origin_file = None, title: str = "CONFIG VARIABLES"):
    """
    Pretty-print configuration variables.
    
    Args:
        variables: dictionary of variables to print
        vars: optional list of variable names to filter output
        origin_file: optional filename to indicate source
        title: title for printing
    """
    print(f"\n=== {title} " + "=" * 60)
    if origin_file:
        print(f"=== from {origin_file}")
        print("=" * 81)

    if vars:
        for var in vars:
            val = variables.get(var, "<not found>")
            print(f"{var:25} = {val}")
    else:
        for k, v in variables.items():
            print(f"{k:25} = {v}")
    print("=" * 81)

def print_config_vars(vars=None):
    """Pretty-print configuration variables, optionally filtered by names."""
    _warnif_not_initialised()
    if isinstance(vars, str):
        vars = [vars]
    
    config_vars = get_config_vars()

    # Check if a config filename is stored as a variable in the cfgvars.py (case insensitive)
    config_filename = next((v for k, v in config_vars.items() if k.lower() == "config_filename"),None)

    __print_vars(get_config_vars(), vars, config_filename)


def verify_paths() -> Dict[str, bool]:
    """
    Check all variables that look like paths and report existence.

    Only considers strings containing '/' or '\\' and composed of letters, numbers, _, -, spaces, dots, or slashes.
    """
    _warnif_not_initialised()
    pths = dict()
    path_pattern = r'^[\w\s\-./\\]+$'

    for varname, varvalue in _vars.items():
        if isinstance(varvalue, str):
            # Only consider strings containing / or \ as potential paths
            if "/" in varvalue or "\\" in varvalue:
                # Ensure the string only contains valid path characters (e.g. ignore glob patterns)
                if re.match(path_pattern, varvalue):
                    pths[varname] = os.path.exists(varvalue)
    
    if len(pths) > 0:
        print()
        for pth, pthvalue in pths.items():
            flag = "exists" if pthvalue else "does not exist"
            print(f"{pth:40}: path {flag}.")
    else:
        print("No path-like variables found.")

def _warnif_not_initialised():
    """Warn the user if the config has not been initialised."""
    global _initialized
    if not _initialized:
        msg ="\nWARNING: Configuration not initialised.\nCall initialise_config(data_dir=...) or initialise_config(keyword=...) to set config.\n"
        warnings.warn(msg)
