"""
The MRE metadata summary TSV: which subjects are done, adding new rows (manual columns are kept), backups.

Author: Luisa Seckinger
"""
from datetime import datetime
from pathlib import Path
import shutil

import pandas as pd

from .metadata import SUMMARY_SORT_COLUMNS, _list_subject_dirs, extract_MRE_seq_info, format_meg_vector

SUMMARY_KEY_COLUMNS = ["SubjectName", "PatientID", "Date", "SeriesNumberPhase"]


def load_existing_summary(tsv_path: str | Path) -> pd.DataFrame:
    """Load an existing metadata summary TSV if it exists."""
    tsv_path = Path(tsv_path)
    if not tsv_path.exists():
        return pd.DataFrame()
    return pd.read_csv(tsv_path, sep="\t")


def get_missing_subjects(tsv_path: str | Path, dicom_root: str | Path, ignore_hidden: bool = True) -> list[str]:
    """Return subject folders not yet present in the summary TSV."""
    existing_subjects = _list_subject_dirs(dicom_root, ignore_hidden=ignore_hidden)
    existing_summary = load_existing_summary(tsv_path)
    if existing_summary.empty:
        return existing_subjects
    processed_subjects = set(existing_summary["SubjectName"].astype(str))
    return sorted(set(existing_subjects) - processed_subjects)


def _row_keys(df: pd.DataFrame, key_cols: list[str]) -> pd.Series:
    """One string key per row, so keys match regardless of dtype (e.g. 13 vs '13')."""
    return df[key_cols].astype(str).agg("|".join, axis=1)


def append_summary_rows(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """Append new rows to an existing summary and de-duplicate by key columns.

    Re-scanned rows replace their old version. Columns that only exist in the existing
    summary (manual columns, e.g. 'Notes' or 'PrivateName') are carried over to the new rows.
    """
    if existing_df.empty:
        return new_df.copy()
    if new_df.empty:
        return existing_df.copy()

    key_cols = [col for col in SUMMARY_KEY_COLUMNS if col in existing_df.columns and col in new_df.columns]
    manual_cols = [col for col in existing_df.columns if col not in new_df.columns]
    if key_cols and manual_cols:
        manual_values = existing_df[manual_cols].set_index(_row_keys(existing_df, key_cols))
        manual_values = manual_values[~manual_values.index.duplicated(keep="last")]
        new_df = new_df.copy()
        new_df[manual_cols] = manual_values.reindex(_row_keys(new_df, key_cols)).to_numpy()

    combined = pd.concat([existing_df, new_df], ignore_index=True)
    dedupe_cols = [col for col in SUMMARY_KEY_COLUMNS if col in combined.columns]
    if dedupe_cols:
        combined = combined.drop_duplicates(subset=dedupe_cols, keep="last")
    sort_cols = [col for col in SUMMARY_SORT_COLUMNS if col in combined.columns]
    if sort_cols:
        combined = combined.sort_values(by=sort_cols).reset_index(drop=True)
    return combined


def backup_file(path: str | Path) -> Path:
    """Copy a file to 'backups/<name>_<date>_<time><ext>' next to it. Old backups are never deleted."""
    path = Path(path)
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / f"{path.stem}_{datetime.now():%Y-%m-%d_%H%M%S}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def list_available_subjects(dicom_root: str | Path, ignore_hidden: bool = True) -> list[str]:
    """Return all subject folders available under the given DICOM root."""
    return _list_subject_dirs(dicom_root, ignore_hidden=ignore_hidden)


def update_summary_tsv(
    folder_pattern_template: str,
    output_tsv_path: str | Path,
    subject_list: list[str] | None = None,
    ignore_hidden: bool = True,
    append_if_exists: bool = True,
    overwrite: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    force_all_subjects: bool = False,
):
    """Extract metadata and update the summary TSV.

    Parameters
    ----------
    subject_list:
        Explicit subjects to process. If `None`, the caller decides the scope.
    force_all_subjects:
        If `True`, ignore `subject_list` and re-scan all subjects found under the
        DICOM root encoded in `folder_pattern_template`.
    """
    requested_subjects = [] if force_all_subjects else subject_list

    summary_df, detailed_df = extract_MRE_seq_info(
        folder_pattern_template,
        subject_list=requested_subjects or [],
        ignore_hidden=ignore_hidden,
        verbose=verbose,
    )

    summary_to_write = summary_df.copy()
    if "megVector" in summary_to_write.columns:
        summary_to_write["megVector"] = summary_to_write["megVector"].apply(format_meg_vector)

    output_tsv_path = Path(output_tsv_path)
    if append_if_exists and output_tsv_path.exists() and not overwrite:
        existing_summary = load_existing_summary(output_tsv_path)
        summary_to_write = append_summary_rows(existing_summary, summary_to_write)

    if dry_run:
        print(f"Dry run activated. Would save to {output_tsv_path}")
    else:
        if output_tsv_path.exists():
            print(f"Backup of previous version: '{backup_file(output_tsv_path)}'")
        summary_to_write.to_csv(output_tsv_path, sep="\t", index=False)
        print(f"Wrote file to '{output_tsv_path}'")

    return summary_df, detailed_df, summary_to_write
