"""
Calling heudiconv: installed, or in a container (see container.py). Used by the dicominfo step and the BIDS conversion.

Author: Luisa Seckinger
"""
import os
import subprocess
import sys

from .config import Config
from .container import _apptainer, _find_sif


def heuristic_path(heuristic: str) -> str:
    """A heuristic .py file becomes an absolute path, a built-in heuristic name (e.g. 'convertall') stays."""
    if heuristic.endswith(".py"):
        if not os.path.isfile(heuristic):
            raise FileNotFoundError(f"The specified heuristic file does not exist: '{heuristic}'")
        return os.path.abspath(heuristic)
    return heuristic


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
        heudiconv = [_apptainer(), "exec", "--cleanenv", sif, "heudiconv"]
        dcm2niix = [_apptainer(), "exec", "--cleanenv", sif, "dcm2niix"]
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
    cmd = [_apptainer(), "run", "--cleanenv"]
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
