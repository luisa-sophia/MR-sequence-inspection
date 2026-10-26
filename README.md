# MR sequence inspection

Overview of which MR sequences were run per scan session.

1. `heudiconv_wrapper.ipynb`: runs heudiconv (no conversion) to get a `dicominfo.tsv` per session and removes sensitive columns.
2. `sequence_readout.ipynb`: classifies the scans per session and writes the summary tables.

```
configs/template.py     # tracked dummy config, copy it to configs/<name>.py
seqinspect/             # the logic (config, heudiconv step, summary step)
hooks/pre-commit        # blocks commits that contain absolute paths
output/<identifier>/    # results (gitignored)
.deprecated/            # old version (config/cfgvars.py based)
```

## Setup

```bash
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
Modality rules are include/exclude lists or python functions. A `.yaml` config also works (without functions).

## Output

In `output/<identifier>/`:

- `.heudiconv/<session>/info/dicominfo_mod-<session>.tsv`: heudiconv info per session, sensitive columns removed
- `<identifier>_sequence_summary.tsv`: one row per session, one column per modality (1/0).
  Add notes in the `Comments` column, they are kept when the file is updated.
- `<identifier>_sequence_type_count.tsv`: how often each series description occurs across sessions
- `<identifier>_rules.txt`: the rules that were used, in readable form

Sessions whose folder doesn't match `dcm_pattern` are skipped by heudiconv with a warning.

## Keeping paths out of git

- Configs other than the template are gitignored, and so are the outputs.
- The pre-commit hook rejects staged lines containing `/mnt/`, `/media/`, `/home/`, `/Users/` or `C:\`.
  This also catches notebook outputs, so clear the outputs before committing if needed.
  To bypass it once: `git commit --no-verify`.
