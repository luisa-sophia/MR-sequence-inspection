from __future__ import annotations
from typing import Optional, Any
from heudiconv.utils import SeqInfo
import heudiconv.bids as _hb
import logging
import json
import os
import pandas as pd
import re

lgr = logging.getLogger("heudiconv")


# This script provides the heuristic to use heudiconv on the STAD dataset.
# More specifically, it defines which DICOM folders are converted to nifti, and how they are named. 
# Heudiconv will also put the files in a BIDS-conform folder structure (https://bids.neuroimaging.io/getting_started/folders_and_files/folders.html).
# Rules are adapted for the STAD dataset, where we e.g. know that each subject has only one of each structural scan, and potentially several fMRI scans with differing tasks.
# AUTHOR: Luisa Seckinger
# Last update: 20.11.26

# ------------------------------------------------------------
# Populate IntendedFor options (sbref image, important for fMRI prep)
# ------------------------------------------------------------
POPULATE_INTENDED_FOR_OPTS = {
    "matching_parameters": ["ImagingVolume", "Shims"],
    "criterion": "Closest",
}

#some mp2rage images did not have a shim field which made the pipeline crash
#this is a workaround to temporarily set the function that retrieves the metadata
#to a replacement that does not raise an error but accepts a missing Shim field
_orig_key_info = _hb.get_key_info_for_fmap_assignment
def _tolerant_key_info(json_file, matching_parameter):
    """Images without ShimSetting match no fieldmap instead of crashing."""
    if matching_parameter == "Shims":
        with open(json_file) as f:
            has_shims = "ShimSetting" in json.load(f)
        if not has_shims:
            _hb.lgr.warning(
                'Not an error: %s has no "ShimSetting", so no fieldmap will be '
                "assigned to it. Conversion continues.",
                json_file,
            )
            return [[float("nan")] * 8]  # NaN never matches anything
    return _orig_key_info(json_file, matching_parameter)

_hb.get_key_info_for_fmap_assignment = _tolerant_key_info
# ------------------------------------------------------------
# Load subject-specific fMRI task map from external file
# ------------------------------------------------------------
# was the subject scanned in the SOC or NSOC condition?
TASKMAP_PATH = os.environ.get("HEUDICONV_TASKMAP", "")

try:
    task_map_tsv = pd.read_csv(TASKMAP_PATH, sep = "\t", dtype = str)
    TASK_MAP = dict(zip(task_map_tsv["PatientID"], task_map_tsv["fMRI_Condition"]))
except Exception as e:
    lgr.warning(f"Could not load task map from path '%s' (must be a tab-separated file with 'Scan' and 'fMRI_Condition' columns, passed in via the HEUDICONV_TASKMAP environment variable"\
                "Error: %s", TASKMAP_PATH, e, exc_info=True)
    TASK_MAP = {}



def create_key(template, outtype=("nii.gz",), annotation_classes=None):
    if not template:
        raise ValueError("Template must be a valid format string")
    return (template, outtype, annotation_classes)

# ------------------------------------------------------------
# Main heuristic
# ------------------------------------------------------------
def infotodict(seqinfo: list[SeqInfo]):

    # NOTES
    # - The output Dataset is NOT YET BIDS conform. MP2RAGE needs to be denoised and UNI images moved to derivatives after
    # ------------------------------------------------------------
    # BIDS keys
    # ------------------------------------------------------------

    #=== IMAGE TYPES =====================================
    #MP2RAGE inv times
    #we know each subject has only one T1w set, thus no run idx (otherwise add run-{subindex:02d})
    mp2rage = create_key("sub-{subject}/{session}/anat/sub-{subject}_{session}_inv-{inv}_MP2RAGE") 

    #MP2RAGE UNI image (t1)
    #we know each subject has only one T1w set, thus no run idx (otherwise add run-{item:02d})
    unit1 = create_key("sub-{subject}/{session}/anat/sub-{subject}_{session}_UNIT1")
    #we'll later use the inv times to denoise UNIT1, the denoised image is later put in derivatives (call it desc-denoised_UNIT1.nii.gz or desc-denoised_T1w.nii.gz)


    #set up functional, we have also a direction (anterior posterior and vice versa)
    func = create_key("sub-{subject}/{session}/func/sub-{subject}_{session}_task-{task}_dir-{dir}_run-{item:02d}_bold")
    #field map, to be used for susceptibility distortion correction (no task label according to BIDS)
    fmap_func = create_key("sub-{subject}/{session}/fmap/sub-{subject}_{session}_dir-{dir}_run-{item:02d}_epi")


    info = {
        mp2rage: [], 
        unit1: [], 
        func: [], 
        fmap_func: [],
        }


    inv = 0

    patient_id = seqinfo[0].patient_id

    task_label = TASK_MAP.get(patient_id, "unknown")  # fallback if not in the map
    lgr.info(f"Determined fMRI Task via Scanner PatientID '{patient_id}': '{task_label}'")
    skipped = []

    for s in seqinfo:
            desc = s.series_description
            #we only care about primary images, i.e. nothing that is created after patient examination
            if 'PRIMARY' in s.image_type:
                #=== /ANAT =============================================================
                if("t1" in desc.lower()):
                    #if an image is a readout between the two inversion pulses (INV)
                    INV = re.search(r"INV(\d)", desc) 
                    if INV:
                        inv = INV.group(1)
                        info[mp2rage].append({"item": s.series_id, "inv" : inv})
    
                    #if an image is an UNI image which is derived from the two GRE INV images
                    # (note that we will have to denoise the background later, which is why we keep the INV images)
                    elif("UNI_Images" in s.series_description):
                        info[unit1].append({"item": s.series_id})
    
    
                #=== /FUNC ===================================================
                #bold
                elif("ep2d_bold" in s.series_description):
                    #direction comes after 1p25 in series_description
                    direction =  s.series_description.split("p3s2_")[1].split("_")[0].lower()
                    #main bold run
                    if(direction == 'ap'):
                        info[func].append({"item": s.series_id, "task": task_label, "dir" : direction})
                    #fmap reverse encoding direction
                    elif(direction == "pa"):
                        info[fmap_func].append({"item": s.series_id, "dir" : direction})

                #=== SKIP & ignore =====================================================
                else:
                    skipped.append(s.series_description)
            else:
                #secondary images
                skipped.append(s.series_description)
        

    if skipped:
        lgr.warning(
            "Excluded the following %d of %d sequences from conversion, based on specified heuristic:\n%s"
            % (len(skipped), len(seqinfo), "\n".join(skipped))
        )

    return info
