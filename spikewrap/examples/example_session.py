import spikewrap as sw

if __name__ == "__main__":

    # Make up a probe for this recording
    session = sw.Session(
        subject_path=sw.get_example_data_path("spikeglx") / "rawdata" / "sub-001",
        session_name="ses-001",
        file_format="spikeglx",
    )

    session.preprocess(
        configs="neuropixels+kilosort2_5",
        per_shank=False,
        concat_runs=False,
    )

    #    session.plot_preprocessed(
    #        run_idx="all", mode="map", show_channel_ids=False, show=True, figsize=(12, 8)
    #    )

    session.save_preprocessed(
        overwrite=True, n_jobs=1, slurm=False, chunk_duration_s=0.1
    )

    # 1) figure out what will happen for all per_shank, concat_run combinations
    # 2) figure out slurm
    # 3) figure out overwrite
    # 4) figure out run_method

    # TODO: properly test runs and stuff

    session.sort(
        configs="neuropixels+mountainsort5",
        run_names="all",  # TODO: test, not even sure whether to include...
        run_sorter_method="local",  # "local", "singularity", "docker" or path to MATLAB install (check for mex files!)
        per_shank=True,
        concat_runs=True,
        overwrite=True,
        slurm=False,
    )

    """
2)    configs="neuropixels+mountainsort5",
1)    runs="all",
7)    run_sorter_method="local",  # "local", "singularity", "docker" or path to MATLAB install (check for mex files!)
3)    per_shank=False,
4)    concat_runs=False,
5)    overwrite=True,
6)    slurm=False,
8)  handle existing preprocessing, loading into preprocessing etc.
    """
