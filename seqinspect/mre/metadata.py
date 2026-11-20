from pathlib import Path
import glob
import os
from nibabel.nicom import csareader
import re

import numpy as np
import pandas as pd
import pydicom

SUMMARY_SORT_COLUMNS = ["Date", "PatientID", "SeriesNumberPhase"]
SUMMARY_OUTPUT_COLUMNS = [
    "SubjectName",
    "PatientID",
    "Date",
    "SeriesNumberPhase",
    "Resolution",
    "TR",
    "TE",
    "SeriesDescription",
    "SlicePlane",
    "PhaseEncodingDirection",
    "freqs_Hz",
    "timeStepIndices",
    "dirIndices",
    "megVector",
    "num_files",
]

# Tags needed to decide whether a sequence is MRE phase data (cheap partial read).
_MRE_CHECK_TAGS = ["SOPClassUID", "ImageType", "ImageComments", "PerFrameFunctionalGroupsSequence"]


def _is_enhanced_dicom(ds) -> bool:
    return ds.get("SOPClassUID") == "1.2.840.10008.5.1.4.1.1.4.1"


def format_meg_vector(vectors):
    """Format one or more motion-encoding vectors for TSV output."""
    if isinstance(vectors, str):
        return vectors
    if isinstance(vectors, tuple) and len(vectors) == 3:
        vectors = [vectors]
    return "[" + "; ".join("({:.3f}, {:.3f}, {:.3f})".format(*vec) for vec in vectors) + "]"


def _has_MRE_content(string: str) -> bool:
    """Return True if a string contains the MRE tag."""
    return isinstance(string, str) and "MRE:" in string

def _get_MRE_imagecomments(ds) -> str | None:
    """Return the MRE image comment of an (already read) DICOM dataset, or None.

    Enhanced DICOM: PerFrameFunctionalGroupsSequence[0].FrameContentSequence[0].FrameComments
    Classic DICOM:  ImageComments
    """
    if _is_enhanced_dicom(ds):
        image_comments = _dicom_get(ds, (0x5200, 0x9230), 0, (0x0020, 0x9111), 0, (0x0020, 0x9158), cast=str, default=None)
    else:
        image_comments = ds.get("ImageComments", None)
    return image_comments if _has_MRE_content(image_comments) else None


def _is_phase_data(ds) -> bool:
    """Return True if an (already read) DICOM dataset appears to be an MRE phase image."""
    try:
        image_type = ds.get("ImageType", None)
        if image_type and any(["phase" == e.lower() or "p" == e.lower() for e in list(image_type)]):
            return True
        return False
    except Exception:
        return False


def _dicom_get(ds, *tags, cast=float, default=-1):
    """Safely traverse nested DICOM tags, returning default if anything fails.
    
    Usage:
        _dicom_get(ds, (0x5200,0x9229), 0, (0x0018,0x9112), 0, (0x0018,0x0080))
        # integers are treated as sequence indices, tuples as tag addresses
    """
    try:
        val = ds
        for tag in tags:
            if isinstance(tag, int):
                val = val[tag]
            else:
                val = val[tag].value
        return cast(val) if cast else val
    except Exception:
        return default


def _get_iop_and_pe_dir(ds):
    """Get ImageOrientationPatient and InPlanePhaseEncodingDirection, handling enhanced DICOM."""
    if _is_enhanced_dicom(ds):
        iop = _dicom_get(ds, (0x5200,0x9230), 0, (0x0020,0x9116), 0, (0x0020,0x0037), cast=list, default=None)
        pe_dir = _dicom_get(ds, (0x5200,0x9229), 0, (0x0018,0x9125), 0, (0x0018,0x1312), cast=str, default=None)
    else:
        iop = list(ds.ImageOrientationPatient)
        pe_dir = str(ds.InPlanePhaseEncodingDirection)
    return iop, pe_dir


def _get_slice_plane(dcm):
    """Infer acquisition plane from the DICOM orientation vectors.
       This tells us the axis along which the brain was "sliced" during the scan.
       E.g. if the slice plane is axial, we have a bunch of coronal 2D images."""
    try:
        iop, _ = _get_iop_and_pe_dir(dcm)
        if iop is not None:
            image_ori_patient = np.array(iop, dtype=float)
            row = image_ori_patient[:3]
            col = image_ori_patient[3:]
            normal = np.cross(row, col)
            axis = np.argmax(np.abs(normal))
            return ["sagittal", "coronal", "axial"][axis]
    except Exception:
        return "N/A"


def _list_subject_dirs(dicom_root: str | Path, ignore_hidden: bool = True) -> list[str]:
    """List subject directories under a DICOM root."""
    entries = [entry.name for entry in Path(dicom_root).iterdir() if entry.is_dir()]
    if ignore_hidden:
        entries = [entry for entry in entries if not entry.startswith(".")]
    return sorted(entries)


def _split_folder_pattern_template(folder_pattern_template: str) -> tuple[str, str, str]:
    """Split a folder template into root, sequence glob, and file pattern."""
    if "{subject}" not in folder_pattern_template:
        raise ValueError("The given template does not contain the {subject} placeholder.")
    if "*." not in folder_pattern_template:
        raise ValueError("Template must include a file pattern like '*.dcm'.")

    dicom_root = folder_pattern_template.split("{subject}")[0]
    sequence_pattern_template, file_ext = folder_pattern_template.split("*.")
    file_pattern = f"*.{file_ext.strip()}"
    return dicom_root, sequence_pattern_template, file_pattern


def _extract_sequence_metadata(seq_dir: str, file_pattern: str, subject_name: str, ignore_hidden: bool, verbose: bool) -> list[dict]:
    """Extract metadata rows from a single sequence directory if it contains MRE phase data."""
    #handle paths that have special characters like [] or so
    if not glob.glob(seq_dir):
        seq_dir_safe = glob.escape(seq_dir)
        file_paths = glob.glob(os.path.join(seq_dir_safe, file_pattern), include_hidden=not ignore_hidden)
    else:
        file_paths = glob.glob(os.path.join(seq_dir, file_pattern), include_hidden=not ignore_hidden)

    if not file_paths:
        if verbose:
            print(f"[WARN], No files found: '{seq_dir}', subject '{subject_name}'.")
        return []

    try:
        first_ds = pydicom.dcmread(file_paths[0], stop_before_pixels=True, specific_tags=_MRE_CHECK_TAGS)
    except Exception as e:
        if verbose:
            print(f"[WARN], could not read '{file_paths[0]}': {e}")
        return []

    if not _get_MRE_imagecomments(first_ds):
        if verbose:
            print(f"[~],  no MRE comment found: '{seq_dir}'")
        return []

    if not _is_phase_data(first_ds):
        if verbose:
            print(f"[~],  MRE comment found, but is not phase: '{seq_dir}'")
        return []

    metadata_rows = []
    printed_note = False
    for file_path in file_paths:
        mre_info = try_extract_metadata_from_mre_dicom(file_path, custom_subject_name=subject_name)
        if mre_info is None:
            continue
        metadata_rows.append(mre_info)
        if verbose and not printed_note:
            print(f"[OK], MRE comment found & is phase data '{seq_dir}', processing files...")
            printed_note = True
    return metadata_rows


def extract_MRE_seq_info(folder_pattern_template, subject_list=None, ignore_hidden=True, verbose=True):
    """Scan subjects for MRE phase series and return summary and per-file metadata tables.

    Passing `subject_list=None` or `subject_list=[]` triggers a full crawl of all
    subjects under the DICOM root encoded in `folder_pattern_template`.
    """
    dicom_root, sequence_pattern_template, file_pattern = _split_folder_pattern_template(folder_pattern_template)

    sub_dirs = _list_subject_dirs(dicom_root, ignore_hidden=ignore_hidden) if not subject_list else sorted(subject_list)
    mre_info_list = []

    for si, sub_dir in enumerate(sub_dirs, start=1):
        if verbose:
            print(f"\nProcessing subject: {sub_dir} ({si}/{len(sub_dirs)})")
        sequence_glob = sequence_pattern_template.format(subject=sub_dir)
        sequence_dirs = glob.glob(sequence_glob, recursive=True, include_hidden=not ignore_hidden)

        if not sequence_dirs:
            if verbose:
                print(f"WARNING: No sequence directories found for subject '{sub_dir}' with pattern '{sequence_glob}'.")
            continue

        for seq_dir in sequence_dirs:
            mre_info_list.extend(
                _extract_sequence_metadata(
                    seq_dir=seq_dir,
                    file_pattern=file_pattern,
                    subject_name=sub_dir,
                    ignore_hidden=ignore_hidden,
                    verbose=verbose,
                )
            )

    df_full = pd.DataFrame()
    df_summary = pd.DataFrame()
    subs_with_mre = set()

    if mre_info_list:
        df_full = pd.DataFrame(mre_info_list).sort_values(by="SOPInstanceUID").reset_index(drop=True)
        df_summary = create_subject_MRE_overview_table(df_full)


        subs_with_mre = set(df_summary["SubjectName"].values)
        cols_to_keep = [col for col in SUMMARY_OUTPUT_COLUMNS if col in df_summary.columns]
        df_summary = df_summary[cols_to_keep]
        sort_cols = [col for col in SUMMARY_SORT_COLUMNS if col in df_summary.columns]
        if sort_cols:
            df_summary = df_summary.sort_values(by=sort_cols).reset_index(drop=True)

    non_mre_subs = set(sub_dirs) - subs_with_mre
    if non_mre_subs:
        print(
            "\n===============================================================================\n"
            "WARNING, Found no sequences with MRE ImageComment for the following subjects:\n",
            ",".join(sorted(non_mre_subs)),
            "\n===============================================================================\n",
        )

    return df_summary, df_full


def _get_phase_encoding_axis_and_direction(ds):
    """Get the phase encoding axis and direction for the dicom file.
     The Dicom tag "ImageOrientationPatient" and "InPlanePhaseEncodingDirection" reveal the axis, whereas the tag "PhaseEncodingDirectionPositive" in the CSA header 
     gives information about the direction (e.g. AP or PA).
     DICOM data is standardized to LPS+, with values increasing along the axis (i.e. values increase from R to L, A to P, and I to S)
    """
    #Image Orientation (Patient) specifies the direction cosines of the first row and the first column with respect to the patient. 
    try:
        iop, inplane_pe_dir = _get_iop_and_pe_dir(ds)
        if iop is None or inplane_pe_dir is None:
            return "N/A"
        row = np.array(iop[:3], dtype=float)
        col = np.array(iop[3:], dtype=float)

        if inplane_pe_dir == "ROW":
            phase = row
        elif inplane_pe_dir == "COL" or inplane_pe_dir == "COLUMN":
            phase = col
        else:
            return "N/A"

        axis = np.argmax(np.abs(phase))
        csa_header = csareader.get_csa_header(ds, csa_type='image')
        if csa_header:
            sign = csareader.get_scalar(csa_header, 'PhaseEncodingDirectionPositive') # where 1 positive direction, and 0 is reversed
        else:
            #for enhanced csareader doesnt work, found on this github that private DICOM tag (0021, 111C) is PhaseEncodingDirectionPositiveSiemens
            #https://github.com/orgs/open-dicom/discussions/12
            #by going frame by frame through groups, I found the nested path to the tag
            #same same 1 is positive, 0 is reversed 
            sign = _dicom_get(ds, (0x5200,0x9230), 0, (0x0021,0x11FE), 0, (0x0021,0x111C), cast=int, default=None)
        
        if sign is None:
            return "N/A"
        
        #dicom coordinate system is LPS so 
        directions = {0: ("R", "L"), 1: ("A", "P"), 2: ("I", "S")}
        encoding_direction = directions[axis] if sign > 0 else directions[axis][::-1]
        return "".join(encoding_direction)
    except Exception:
        import traceback
        traceback.print_exc()
        return "N/A"


def try_extract_metadata_from_mre_dicom(file_path, custom_subject_name=None):
    """Parse one DICOM file and return extracted MRE metadata, or `None` if it is not usable."""
    try:
        ds = pydicom.dcmread(file_path, stop_before_pixels=True)

        if not _get_MRE_imagecomments(ds):
            return None

        MRE_specific_data = parse_MRE_dcm_header(ds, convert_arrays_to_list=True)

        if _is_enhanced_dicom(ds):
            TR         = _dicom_get(ds, (0x5200,0x9229), 0, (0x0018,0x9112), 0, (0x0018,0x0080))
            TE         = _dicom_get(ds, (0x5200,0x9230), 0, (0x0018,0x9114), 0, (0x0018,0x9082))
            pxlspacing = _dicom_get(ds, (0x5200,0x9230), 0, (0x0028,0x9110), 0, (0x0028,0x0030), cast=lambda x: [float(v) for v in x], default=[-1,-1])
            z_spacing  = _dicom_get(ds, (0x5200,0x9230), 0, (0x0028,0x9110), 0, (0x0018,0x0088))
            date = ds.get("AcquisitionDateTime", None)
            date = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if date else None
        else:
            TR = ds.get("RepetitionTime", -1)
            TE = ds.get("EchoTime", -1)
            pxlspacing = ds.get("PixelSpacing", [-1, -1])
            z_spacing = ds.get("SpacingBetweenSlices", -1)
            date = ds.get("AcquisitionDate", None)
            date = f"{date[:4]}-{date[4:6]}-{date[-2:]}" if date else None

        zooms = tuple(round(x, 3) for x in [*pxlspacing, z_spacing])
        relative_filepath = os.path.splitdrive(file_path)[1]

        metadata = {
            "PatientID": str(ds.get("PatientName", "N/A")),
            "SubjectName": custom_subject_name if custom_subject_name else str(ds.get("PatientID", "N/A")),
            "SeriesNumberPhase": ds.get("SeriesNumber", "N/A"),
            "Path": relative_filepath,
            "SOPInstanceUID": ds.get("SOPInstanceUID", "N/A"),
            "Resolution": str(zooms),
            "TR": TR,
            "TE": TE,
            "SeriesDescription": ds.get("SeriesDescription"),
            #"InPlanePhaseEncodingDirection": ds.get("InPlanePhaseEncodingDirection", "N/A"),
            "ImageType": str(ds.get("ImageType", "N/A")),
            "Date": date,
            "SlicePlane": _get_slice_plane(ds),
            "PhaseEncodingDirection": _get_phase_encoding_axis_and_direction(ds)
        }
        metadata.update(MRE_specific_data)
        return metadata
    except Exception as e:
        import traceback
        print(f"Error processing {file_path}: {e}")
        traceback.print_exc()
        return None


def create_subject_MRE_overview_table(mre_info_df):
    """Collapse per-file metadata into one summary row per MRE phase series."""
    mre_info_df = mre_info_df.copy()
    #convert to hashable tuple
    for col in mre_info_df.columns:
        if col not in ["PatientID", "Date", "SeriesNumberPhase"]:
            mre_info_df[col] = mre_info_df[col].apply(
                lambda v: tuple(v) if isinstance(v, (list, np.ndarray)) else v
            )
    #group so that each row corresponds to one unique series, and aggregate the other columns into lists
    grouped = mre_info_df.groupby(["PatientID", "Date", "SeriesNumberPhase"], 
                                  as_index=False,
                                  dropna=False).agg(
                                      num_files=("SOPInstanceUID", "size"),
                                      **{col: (col, "unique") for col in mre_info_df.columns if col not in ["PatientID", "Date", "SeriesNumberPhase"]},
                                      ).reset_index(drop=True)
    grouped["freqs_Hz"] = grouped["freqs_Hz"].apply(lambda values: [round(float(freq), 2) for freq in values])
    return collapse_unique_columns(grouped)


def collapse_unique_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten list-like columns that only contain one unique value per row."""
    df = df.copy()
    for col in df.columns:
        if df[col].apply(lambda x: isinstance(x, (list, tuple, np.ndarray))).all():
            lengths = df[col].apply(len)
            if (lengths == 1).all():
                df[col] = df[col].apply(lambda x: x[0])
    return df


def parse_MRE_dcm_header(metadata_dict, convert_arrays_to_list=True, flatten_meg_vector=True):
    """Extract MRE-specific fields from the Siemens MRE image comment.

    Takes the whole DICOM dataset (not just the comment string), because the
    az/po branch also needs ImageOrientationPatient and SliceLocation.
    """
    extracted_info = {}

    tag = _get_MRE_imagecomments(metadata_dict)
    if tag is None:
        return extracted_info

    pattern = r'(\s|^|\])(fI|F )\[{0,1}(?P<freqIndices>\d+)\]{0,1}'
    ret = re.search(pattern, tag, flags=re.IGNORECASE)
    extracted_info['freqIndices'] = int(ret.group('freqIndices')) if ret else -1

    pattern = r'(\s|^|\])dI\[(?P<dirIndices>\d+)\]'
    ret = re.search(pattern, tag, flags=re.IGNORECASE)
    extracted_info['dirIndices'] = int(ret.group('dirIndices')) if ret else -1

    pattern = r'\({0,1}(?P<encDir>(slice|read|phase|readout))\){0,1}'
    ret = re.search(pattern, tag, flags=re.IGNORECASE)
    if ret:
        encDir = ret.group('encDir')
        if encDir != tag:
            megOpt = ['read', 'phase', 'slice']
            try:
                extracted_info['megIndices'] = next(i for i, opt in enumerate(megOpt) if opt.lower() == encDir.lower())
            except StopIteration:
                extracted_info['megIndices'] = -1
    else:
        extracted_info['megIndices'] = -1

    pattern = r'(\s|^|\])az\[(?P<azimuths>\d+)\]po\[(?P<polars>\d+)\]'
    ret = re.search(pattern, tag, flags=re.IGNORECASE)
    if ret:
        if not _is_enhanced_dicom(metadata_dict):
            extracted_info['SliceLocation'] = metadata_dict.get('SliceLocation', None)

        iop, _ = _get_iop_and_pe_dir(metadata_dict)
        iop = np.array(iop)
        extracted_info['ImageOrientationPatient'] = iop

        extracted_info['azimuth'] = float(ret.group('azimuths'))
        extracted_info['polar'] = float(ret.group('polars'))

        cubeOrientation = np.zeros((3, 3))

        cubeOrientation[:, 0] = iop[:3] / np.linalg.norm(iop[:3])
        cubeOrientation[:, 1] = iop[3:6] / np.linalg.norm(iop[3:6])
        cubeOrientation[:, 2] = np.cross(cubeOrientation[:, 0], cubeOrientation[:, 1])

        scannerSystemMatrix = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]])
        az = np.deg2rad(extracted_info['azimuth'])
        pol = np.deg2rad(extracted_info['polar'])
        dir_vec = np.zeros((3, 1))
        dir_vec[0, 0] = np.sin(pol) * np.cos(az)
        dir_vec[1, 0] = np.sin(pol) * np.sin(az)
        dir_vec[2, 0] = np.cos(pol)

        megVector = cubeOrientation.T @ scannerSystemMatrix @ dir_vec
        extracted_info['megVector'] = megVector
        resVector = np.eye(3) @ megVector
        absRes = np.abs(resVector)
        primary_idx = np.argmax(absRes)
        extracted_info['megIndices'] = primary_idx
        extracted_info['conjMeg'] = False
        if resVector[primary_idx] < 0:
            extracted_info['megVector'] = -extracted_info['megVector']
            extracted_info['conjMeg'] = True
        if flatten_meg_vector:
            extracted_info['megVector'] = extracted_info['megVector'].flatten().tolist()
        extracted_info['megIndices'] = int(extracted_info['megIndices'])
    else:
        extracted_info['conjMeg'] = False
        extracted_info['azimuth'] = None
        extracted_info['polar'] = None

    pattern = r'(\s|^|\])(tI|TS)(\[|\s)(?P<timeStepIndices>\d+)(\]|\s)'
    ret = re.search(pattern, tag, flags=re.IGNORECASE)
    extracted_info['timeStepIndices'] = int(ret.group('timeStepIndices')) if ret else -1

    pattern = r'(\s|^|\])(VP|VR)\[(?P<mechCycleTimes_us>\d+)\]'
    ret = re.search(pattern, tag, flags=re.IGNORECASE)
    if ret:
        extracted_info['mechCycleTimes_us'] = float(ret.group('mechCycleTimes_us'))
        extracted_info['freqs_Hz'] = 1e6 / extracted_info['mechCycleTimes_us']
    else:
        extracted_info['mechCycleTimes_us'] = 0
        extracted_info['freqs_Hz'] = 0

    if convert_arrays_to_list:
        for key, value in extracted_info.items():
            if isinstance(value, np.ndarray):
                extracted_info[key] = value.tolist()

    return extracted_info
