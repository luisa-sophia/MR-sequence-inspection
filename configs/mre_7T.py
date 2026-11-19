"""
MRE project, 7T scanner. Shared config (tracked): only paths relative to the drive root.
The drive root is found automatically (folder containing '.drive_root.txt'), as the drive
might be mounted differently each time. Not on the drive: load_config(..., root="/your/root").
"""

identifier = "7T_Terra"
root_marker = ".drive_root.txt"

# === DICOM input (relative to the drive root)
dicom_root = "MR_Data/Raw/MRE/7T_Terra"
# all subjects of one scanner need the same folder hierarchy, otherwise heudiconv processes 0 files
dcm_pattern = f"{dicom_root}/{{subject}}/SCANS/*/DICOM/*.dcm"
ignore = ["__MACOSX"]    # temp folder from apple

# === output: <drive root>/Scan_Summaries/MRE/7T_Terra
output_dir = "Scan_Summaries/MRE"
output_in_root = True

# modified heuristic to extract TR and TE from enhanced DICOMs (new XB10 platform writes out
# enhanced format, which stores TR/TE in a different way)
info_heuristic = "heuristics/convertall_enhancedcm_mod.py"

# === modality rules: regex, case insensitive, matched anywhere in the series description.
# A modality matches if any of its patterns match; a scan can count for several modalities.
modalities = {
    "T1w":  [".*t1.*"],
    "T2w":  [".*t2.*"],
    "fMRI": [".*face.*", ".*cmrr.*"],
    "MRE":  ["^(?!.*fmre).*mre_"],
    "fMRE": [".*fmre_.*"],
}
exclusive_rules = False
count_scans = True
