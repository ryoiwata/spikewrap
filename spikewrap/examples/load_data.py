from pathlib import Path

from spikewrap.pipeline.load_data import load_data

base_path = Path(
    # r"/ceph/neuroinformatics/neuroinformatics/scratch/jziminski/ephys/test_data/steve_multi_run/1119617/time-short-multises"
    r"X:\neuroinformatics\scratch\jziminski\ephys\test_data\steve_multi_run\1119617\time-short-multises"
)

sub_name = "sub-1119617"
sessions_and_runs = {
    "ses-001": [
        "run-001_1119617_LSE1_shank12_g0",
        "run-002_made_up_g0",
    ],
    "ses-002": [
        "run-001_1119617_pretest1_shank12_g0",
    ],
    "ses-003": [
        "run-002_1119617_pretest1_shank12_g0",
    ],
}

loaded_data = load_data(base_path, sub_name, sessions_and_runs, data_format="spikeglx")
