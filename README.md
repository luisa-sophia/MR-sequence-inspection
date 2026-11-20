# MR sequence inspection

Overview of which MR sequences were run per scan session, optional MRE metadata, and BIDS conversion.
Merged from `MR-sequence-inspection` and `MRE-sequence-inspection` (both histories are kept).

1. `heudiconv_wrapper.ipynb`: runs heudiconv (no conversion) to get a `dicominfo.tsv` per session and removes sensitive columns.
2. `sequence_readout.ipynb`: classifies the scans per session and writes the summary tables.
3. `mre_metadata_crawler.ipynb` (MRE only): collects the metadata of all MRE phase scans per scanner.
4. `python -m seqinspect.convert` (optional): BIDS conversion with heudiconv + your heuristic.

```
configs/template.py     # tracked dummy config, copy it to configs/<name>.py
configs/mre_7T.py       # tracked MRE configs (only paths relative to the drive root)
configs/mre_3T.py
seqinspect/             # the logic
  config.py             #   Config, load_config
  sessions.py           #   finding the session folders, checking them against the dicom headers
  heudiconv.py          #   calling heudiconv (installed or in a container)
  container.py          #   apptainer/singularity, heudiconv .sif image
  dicominfo.py          #   step 1: dicominfo.tsv per session, cleaning
  summary.py            #   step 2: summary tables
  convert.py            #   step 3: BIDS conversion
seqinspect/mre/         # MRE metadata crawler (needs pydicom, nibabel)
  metadata.py           #   reading the MRE metadata from the dicom headers
  summary_tsv.py        #   the summary TSV: missing subjects, adding rows, backups
  crawler.py            #   ties both together per scanner config
heuristics/             # heudiconv heuristics, e.g. for enhanced dicoms (XB10)
hooks/pre-commit        # blocks commits that contain absolute paths
output/<identifier>/    # results (gitignored)
```

## Setup

```bash
pip install -r requirements.txt               # + heudiconv, or use a container (see below)
cp configs/template.py configs/myproject.py   # fill in, gitignored
git config core.hooksPath hooks               # once per clone
```

## Configuring

In the first cell of each notebook, choose one of:

```python
cfg = load_config("configs/myproject.py")                    # config file
cfg = load_config("configs/myproject.py", root="/path/to")   # config file + overrides
cfg = Config(dicom_root="/path/to/dicoms", dcm_pattern="...", modalities={...})  # quick inline
```

All options are documented in `configs/template.py`. Optional parts like `fmri_blocks` and
`file_checks` (e.g. spectroscopy) can be deleted, and their columns disappear from the summary.
A `.yaml` config also works (without functions).

- **Root:** relative paths are joined with `root`. Instead, `root_marker = ".drive_root.txt"` finds the
  root automatically (first folder above the notebook containing that file), so it works however the drive is mounted.
- **Modality rules:** include/exclude lists, regex strings (case insensitive) or python functions.
  `exclusive_rules=True`: first matching rule wins, `False`: a scan can count for several modalities.
  `count_scans=True` gives the number of matching scans instead of 1/0.
- **Several scanners:** one config per scanner (see `configs/mre_7T.py` and `configs/mre_3T.py`).
- **Enhanced dicoms (XB10):** heudiconv misses TR/TE. Set `info_heuristic = "heuristics/convertall_enhancedcm_mod.py"`,
  `clean_dicominfo` then fills them in from the `custom` column.
- **Container:** `container = "/path/to/apptainer"` runs heudiconv via apptainer, in the notebooks and for the conversion.
  If it is a folder, `heudiconv_<version>.sif` for the pinned `container_image` (default `nipy/heudiconv:1.5.1`) is used
  and pulled if missing. A `.sif` file is used as it is.
  The heudiconv and dcm2niix versions are printed at the start of every run, so they end up in the log.

## Output

In `out_dir` (`output/<identifier>/`, or `<root>/<output_dir>/<identifier>/` with `output_in_root=True`):

- `.heudiconv/<session>/info/dicominfo_mod-<session>.tsv`: heudiconv info per session, sensitive columns removed
- `<identifier>_sequence_summary.tsv`: one row per session, one column per modality.
  Add notes in the `Comments` column, they are kept when the file is updated.
- `<identifier>_sequence_type_count.tsv`: how often each series description occurs across sessions
- `<identifier>_rules.txt`: the rules that were used, in readable form
- `MRE_metadata_summary_<label>.tsv` (MRE crawler), previous versions in `backups/`

Sessions are the folders at the position of `{subject}` in `dcm_pattern` in which the pattern finds dicoms.
Other folders there are skipped with a note.

## BIDS conversion

For subjects without session structure. Set `bids_dir`, `bids_heuristic` (and optionally `container`,
`container_tmp`) in the config, then:

```bash
python -m seqinspect.convert configs/myproject.py --subjects sub-01 sub-02
python -m seqinspect.convert configs/myproject.py --all        # all sessions found below dicom_root
python -m seqinspect.convert configs/myproject.py --all --yes  # no questions, e.g. in a batch job
```

Subject ids can be given with or without `sub-`; heudiconv gets them without. If the dicom folders
are called `sub-<id>`, write `sub-{subject}` in the `dcm_pattern`.

**With sessions:** set a `bids_dcm_pattern` containing `{session}`, e.g.
`sub-{subject}_ses-{session}/*/SCANS/*/DICOM/*.dcm`. Ids are then given as `sub-01_ses-B`
(or in the format of `short_id_regex`, e.g. `01B`), and heudiconv runs once per session (`--ses`).
For the notebooks keep `dcm_pattern = f"{dicom_root}/{{subject}}/*/SCANS/..."`,
there a session is simply the whole folder name. Environment variables the heuristic reads
(e.g. `HEUDICONV_TASKMAP`) go in `bids_env`.
In a notebook: `from seqinspect.convert import convert; convert(cfg, ["01", "02"])`.

## Keeping paths out of git

- Configs other than the template and the MRE configs are gitignored, and so are the outputs.
- The pre-commit hook rejects staged lines containing `/mnt/`, `/media/`, `/home/`, `/Users/` or `C:\`.
  This also catches notebook outputs, so clear the outputs before committing if needed.
  To bypass it once: `git commit --no-verify`.
