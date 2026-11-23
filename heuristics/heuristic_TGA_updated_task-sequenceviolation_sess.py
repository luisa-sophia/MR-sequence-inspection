from __future__ import annotations
from typing import Optional, Any
from heudiconv.utils import SeqInfo
import logging
import json
import os
import pandas as pd
import re

lgr = logging.getLogger("heudiconv")


# This script provides the heuristic to use heudiconv on the TGA dataset.
# More specifically, it defines which DICOM folders are converted to nifti, and how they are named. 
# Heudiconv will also put the files in a BIDS-conform folder structure (https://bids.neuroimaging.io/getting_started/folders_and_files/folders.html).
# Rules are adapted for the TGA dataset, where we e.g. know that each subject has only one of each structural scan, and potentially several fMRI scans with differing tasks.
# Please use the respective bash script in this folder to execute, or pass the heuristic via a manual call of the heudiconv container.
# AUTHOR: Luisa Seckinger
# Last update: 14.08.26

# ------------------------------------------------------------
# Populate IntendedFor options (sbref image, important for fMRI prep)
# ------------------------------------------------------------
POPULATE_INTENDED_FOR_OPTS = {
    "matching_parameters": ["ImagingVolume", "Shims"],
    "criterion": "Closest",
}

# ------------------------------------------------------------
# Load subject-specific fMRI task map from external file
# ------------------------------------------------------------
# was the subject scanned at rest, or while doing the sequence task?
TASKMAP_PATH = os.environ.get("HEUDICONV_TASKMAP", "")

try:
    task_map_tsv = pd.read_csv(TASKMAP_PATH, sep = "\t")
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
    # - sbref image for reverse phase encoded BOLD image (used for distortion correction /fmap) is IGNORED!! (i.e. not converted)
    #   as it is difficult to bring together with BIDS structure and not used by fmriprep (I think, at least)
    # - The output Dataset is NOT YET BIDS conform. MP2RAGE needs to be denoised and UNI images moved to derivatives after
    # - dwi data is NOT properly handled (was not part of the project)
    # ------------------------------------------------------------
    # BIDS keys
    # ------------------------------------------------------------

    #=== IMAGE TYPES =====================================
    #MP2RAGE inv times
    #we know each subject has only one T1w set, thus no run idx (otherwise add run-{subindex:02d})
    mp2rage = create_key("sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-{acq}_inv-{inv}_MP2RAGE") 

    #MP2RAGE UNI image (t1)
    #we know each subject has only one T1w set, thus no run idx (otherwise add run-{item:02d})
    unit1 = create_key("sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-{acq}_UNIT1")

    #we'll later use the inv times to denoise UNIT1, the denoised image is later put in derivatives (call it desc-denoised_UNIT1.nii.gz or desc-denoised_T1w.nii.gz)

    t2w = create_key("sub-{subject}/{session}/anat/sub-{subject}_{session}_T2w")

    #set up functional, we have also a direction (anterior posterior and vice versa)
    func = create_key("sub-{subject}/{session}/func/sub-{subject}_{session}_task-{task}_dir-{dir}_run-{item:02d}_bold")
    #single band reference image
    fsbref = create_key("sub-{subject}/{session}/func/sub-{subject}_{session}_task-{task}_dir-{dir}_run-{subindex:02d}_sbref")
    #field map, to be used for susceptibility distortion correction
    fmap_func = create_key("sub-{subject}/{session}/fmap/sub-{subject}_{session}_dir-{dir}_run-{item:02d}_epi")

    # dwi = create_key("sub-{subject}/{session}/dwi/sub-{subject}_{session}_acq-{acq}_dwi")
    # dsbref = create_key("sub-{subject}/{session}/dwi/sub-{subject}_{session}_acq-{acq}_sbref")

    info = {
        mp2rage: [], 
        unit1: [], 
        t2w: [], 
        func: [], 
        fsbref: [], 
        fmap_func: [],
        # dwi: [], 
        # dsbref: [], 
        }

    patient_id = seqinfo[0].patient_id

    task_label = TASK_MAP.get(patient_id, "unknown")  # fallback if not in the map
    lgr.info(f"Determined fMRI Task via Scanner PatientID '{patient_id}': '{task_label}'")
    skipped = []

    for s in seqinfo:
            #we only care about primary images, i.e. nothing that is created after patient examination
            if 'PRIMARY' in s.image_type:
                #=== /ANAT =============================================================
                if "t1" in s.series_description.lower():
                    # resolution (in case we have two T1 images)
                    if "1mm" in s.series_description:
                        acq = "1mm"
                    elif "0.75" in s.series_description:
                        acq = "0p75mm"
                    else:
                        acq = None

                    #this was the original block but this is fragile as it depends on INV1 always being before INV2
                    #in this case it went ok because it always does (I checked), but this is not a reliable way
                    #as it would label INV1 and INV2 wrongly if the order was reversed, so we replace it by the block below
                    # #if an image is a readout between the two inversion pulses (INV)
                    # if("INV" in s.series_description):
                    #     inv = 0
                    #     if("1mm" in s.series_description):
                    #         inv1mm = inv1mm + 1
                    #         inv = inv1mm
                    #     elif("0.75" in s.series_description):
                    #         inv075mm = inv075mm + 1
                    #         inv = inv075mm
                    #     info[mp2rage].append({"item": s.series_id, "acq": acq, "inv" : inv})

                    # inversion number is read from the description,
                    # so it does not depend on series order
                    INV = re.search(r"INV(\d)", s.series_description)
                    if INV and acq:
                        info[mp2rage].append(
                            {"item": s.series_id, "inv": INV.group(1), "acq": acq}
                        )
    
                    #if an image is an UNI image which is derived from the two GRE INV images
                    # (note that we will have to denoise the background later, which is why we keep the INV images)
                    elif("UNI_Images" in s.series_description):
                        info[unit1].append({"item": s.series_id,"acq": acq})
    
                    acq = "none"
    
                elif("t2" in s.series_description):
                    info[t2w].append({"item": s.series_id})
    
                #=== /FUNC AND /FMAP ===================================================
                #bold
                elif("face" in s.series_description):
                    #direction comes after 1p25 in series_description
                    direction =  s.series_description.split("1p25_")[1].split("_")[0].lower()
                    #sbref images (ignore the one that is for the fmap, so only save the ones in ap direction)
                    if("SBRef" in s.series_description):
                        if direction == 'ap':
                            info[fsbref].append({"item": s.series_id, "task": task_label, "dir" : direction})
                    #main bold run
                    elif(direction == 'ap'):
                        info[func].append({"item": s.series_id, "task": task_label, "dir" : direction})
                    #fmap reverse encoding direction
                    elif(direction == "pa"):
                        info[fmap_func].append({"item": s.series_id, "dir" : direction})

                #skip DWI for now, not enough info to set up a proper heuristic (which files are important, etc.)
                #  #=== /DIFF =============================================================
                # #this is probably sloppy, as this heuristic was set up primarily for fMRI, but we'll give it a try
                # elif "DIFFUSION" in s.image_type:
                #     desc = s.series_description
                #     acq = acq = s.series_description.replace("_","")

                #     if "ORIGINAL" in s.image_type:
                #         # raw acquisitions: the main scan and its reverse-PE partner
                #         if desc.endswith("_PA"):
                #             direction = "pa"
                #             info[dsbref].append({"item": s.series_id, "acq": acq, "dir": direction})
                #         else:
                #             info[dwi].append({"item": s.series_id, "acq": acq})
                #     else:
                #         # scanner-computed maps: ADC, TRACEW, FA, ColFA, ...
                #         # commented out as they are derived, will only write out org
                #         skipped.append(s.series_description)
                #         #info[dwi].append({"item": s.series_id, "acq": acq}) #if you wanna write out
                #     acq = "none"

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
