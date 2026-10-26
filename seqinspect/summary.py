"""
Step 2: build an overview which sequences were run per session.

Author: Luisa Seckinger
"""
import glob
import inspect
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, matches
from .dicominfo import DICOMINFO_GLOB, find_dicominfo_files


def _file_check_sessions(cfg: Config, check: dict) -> set[str]:
    """Session ids for which the glob of a file check matches."""
    level = check.get("session_level", 1)
    return {Path(p).parents[level - 1].name for p in glob.glob(cfg.path(check["glob"]))}


def _count_blocks(trs: list[int], trs_per_block: int, threshold: float) -> float:
    return float(sum(np.round(tr / trs_per_block, 1) for tr in trs if tr / trs_per_block >= threshold))


def build_summary(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
        summary: one row per session, one column per modality (1/0), plus optional fMRI block / file check columns
        counts:  how often each series_description occurs across all sessions
    """
    infos = {s: p for s, p in find_dicominfo_files(cfg, DICOMINFO_GLOB).items() if s not in cfg.exclude_sessions}
    print(f"{len(infos)} sessions with dicominfo in '{cfg.out_dir}'.")
    file_checks = {name: _file_check_sessions(cfg, check) for name, check in cfg.file_checks.items()}
    for name, found in file_checks.items():
        print(f"{len(found)} sessions with '{name}'.")

    fb = cfg.fmri_blocks
    rows, all_descriptions = [], []
    for session in sorted(infos, key=cfg.sort_key):
        df = pd.read_csv(infos[session], sep="\t", encoding="latin-1", on_bad_lines="skip")
        df = df[df["series_description"].notna()]
        all_descriptions.extend(df["series_description"])

        row = {"Session_ID": session, **{m: 0 for m in cfg.modalities}}
        block_trs = []
        for _, scan in df.iterrows():
            for modality, rule in cfg.modalities.items():
                if matches(rule, scan["series_description"]):
                    row[modality] = 1
                    if fb and modality == fb["modality"]:
                        block_trs.append(int(scan["dim4"]))
                    break  # rules are exclusive, first match wins

        if fb:
            row["fMRI_blocks"] = _count_blocks(block_trs, fb["trs_per_block"], fb["threshold"])
            row["fMRI_num_TRs"] = ", ".join(str(tr) for tr in block_trs)
        for name, found in file_checks.items():
            row[name] = int(session in found)
        rows.append(row)

    summary = pd.DataFrame(rows)
    counts = pd.Series(all_descriptions).value_counts().rename_axis("series_description").reset_index(name="count")
    return summary, counts


def _rule_as_text(rule) -> str:
    """One modality rule as readable text, e.g. "contains 'face', 'ap'; not 'SBRef'"."""
    if callable(rule):
        try:
            src = inspect.getsource(rule).strip()
        except (OSError, TypeError):
            return repr(rule)
        # a lambda inside the modalities dict comes with its whole line ("T1w": lambda x: ...,)
        return src[src.find("lambda"):].rstrip(",") if rule.__name__ == "<lambda>" else f"function {rule.__name__}()"
    parts = []
    if rule.get("include"):
        parts.append("contains " + ", ".join(f"'{s}'" for s in rule["include"]))
    if rule.get("exclude"):
        parts.append("not " + ", ".join(f"'{s}'" for s in rule["exclude"]))
    return "; ".join(parts)


def _rules_as_text(cfg: Config) -> str:
    lines = ["Rules used to classify scans, based on the dicom 'series_description'.",
             "Checked in this order, first matching rule wins.", ""]
    width = max((len(m) for m in cfg.modalities), default=0) + 1
    lines += [f"{name + ':':{width}} {_rule_as_text(rule)}" for name, rule in cfg.modalities.items()]

    fb = cfg.fmri_blocks
    if fb or cfg.file_checks:
        lines.append("")
    if fb:
        lines.append(f"fMRI blocks: {fb['trs_per_block']} TRs per block of '{fb['modality']}', "
                     f"a run counts if it has >= {fb['threshold']:.0%} of a block")
    for name, check in cfg.file_checks.items():
        lines.append(f"{name}: file check '{check['glob']}' "
                     f"(session = folder {check.get('session_level', 1)} level(s) above the match)")
    return "\n".join(lines) + "\n"


def write_outputs(cfg: Config, summary: pd.DataFrame, counts: pd.DataFrame):
    """Write summary (keeps manual 'Comments' from an existing file), counts and the rules used."""
    os.makedirs(cfg.out_dir, exist_ok=True)
    base = os.path.join(cfg.out_dir, cfg.identifier)

    summary_path = f"{base}_sequence_summary.tsv"
    summary = summary.copy()
    summary["Comments"] = ""
    if os.path.exists(summary_path):
        old = pd.read_csv(summary_path, sep="\t", dtype={"Session_ID": str}).fillna({"Comments": ""})
        comments = dict(zip(old["Session_ID"], old["Comments"]))
        summary["Comments"] = summary["Session_ID"].map(comments).fillna("")
    summary.to_csv(summary_path, sep="\t", index=False)

    counts.to_csv(f"{base}_sequence_type_count.tsv", sep="\t", index=False)
    with open(f"{base}_rules.txt", "w") as f:
        f.write(_rules_as_text(cfg))

    print(f"Written to '{cfg.out_dir}':\n- {os.path.basename(summary_path)}\n"
          f"- {cfg.identifier}_sequence_type_count.tsv\n- {cfg.identifier}_rules.txt")
