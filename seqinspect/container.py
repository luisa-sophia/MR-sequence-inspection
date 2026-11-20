"""
Running heudiconv in an apptainer (singularity) container: finding apptainer and the heudiconv image.

Author: Luisa Seckinger
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # only for type hints, config.py imports from this module
    from .config import Config


APPTAINER_MISSING = (
    "'container' is set, but neither 'apptainer' nor 'singularity' is found in PATH, heudiconv can't run. "
    "Run it where apptainer is installed (not inside a container, e.g. a workbench), after 'module load apptainer' "
    "if needed. Or set container = None to use an installed heudiconv.")


def find_apptainer() -> str | None:
    """Path of the apptainer executable (or singularity, its older name), None if neither is in PATH."""
    return shutil.which("apptainer") or shutil.which("singularity")


def _apptainer() -> str:
    """The apptainer executable (or singularity, its older name)."""
    path = find_apptainer()
    if not path:
        raise FileNotFoundError(APPTAINER_MISSING)
    return path


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
        subprocess.run([_apptainer(), "pull", sif, cfg.container_image], check=True)
        print(f"Pulled image to: {sif}")
    return sif
