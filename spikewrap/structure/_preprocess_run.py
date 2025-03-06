from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Literal

import yaml

if TYPE_CHECKING:
    from pathlib import Path

    import matplotlib


import numpy as np
import spikeinterface.full as si

from spikewrap.configs._backend import canon
from spikewrap.utils import _slurm, _utils
from spikewrap.visualise._visualise import visualise_run_preprocessed


class PreprocessedRun:
    """
    Holds the fully-preprocessed spikeinterface recordings. No further
    processing is done at this stage, this class manages the saving
    and visualisation of the preprocessed data.

    Parameters
    ----------
    raw_data_path
        Path to the raw-data session folder (e.g. ses-001 or ses-001/ephys)
        from which this data was preprocessed
    ses_name
        The session name for this run
    run_name
        Folder name of this run.
    file_format
        The file format (e.g. openephys, spikeglx) of the original data.
    session_output_path
        Path to the output (processed) parent session-level data.
    preprocessed_data
        The preprocessed data in a dictionary, which keys "grouped"
        or the shank_ids (e.g. "shank_0", ...) if split by shank.
    sync
        The recording containing the sync channel.

    TODO
    ----
    None of these attributes should be mutable. Make a frozen dataclass?
    """

    def __init__(
        self,
        raw_data_path: Path,
        ses_name: str,
        run_name: str,
        file_format: str,
        session_output_path: Path,
        preprocessed_data,
        sync,
        pp_steps,
        orig_run_names=None,
    ):
        self._raw_data_path = raw_data_path
        self._ses_name = ses_name

        self._run_name = run_name
        self._file_format = file_format
        self._session_output_path = session_output_path
        self._output_path = session_output_path / run_name
        self._pp_steps: dict = pp_steps
        self._orig_run_names = orig_run_names

        self._preprocessed = preprocessed_data
        self._sync = sync

    # ---------------------------------------------------------------------------
    # Public Functions
    # ---------------------------------------------------------------------------

    def save_preprocessed(
        self, overwrite: bool, chunk_duration_s: float, n_jobs: int, slurm: dict | bool
    ) -> None:
        """
        Save the fully preprocessed run to binary.

        see the public session.save_preprocessed() for arguments.
        """
        if slurm:
            self._save_preprocessed_slurm(overwrite, chunk_duration_s, n_jobs, slurm)
            return

        _utils.message_user(f"Saving data for: {self._run_name}...")

        if n_jobs != 1:
            si.set_global_job_kwargs(n_jobs=n_jobs)

        self._handle_overwrite_output(overwrite)

        self._save_sync_channel()

        # Save the recordings to disk, handling shank ids
        for shank_name, preprocessed_recording in self._preprocessed.items():

            preprocessed_path = self._output_path / canon.preprocessed_folder()

            if shank_name != canon.grouped_shankname():
                preprocessed_path = preprocessed_path / shank_name

            preprocessed_recording.save(
                folder=preprocessed_path,
                chunk_duration=f"{chunk_duration_s}s",
            )

        self.save_class_attributes_to_yaml(
            self._output_path / canon.preprocessed_folder()
        )

        if self._orig_run_names:
            with open(
                self._output_path / canon.preprocessed_folder() / "orig_run_names.txt",
                "w",
            ) as file:
                file.write("\n".join(self._orig_run_names))

    def save_class_attributes_to_yaml(self, path_to_save):
        """
        Dump the class attributes to file so the class
        can be loaded later.

        TODO
        ----
        Should use __to_dict? but want to be very
        selective about what is included.
        """
        to_dump = {
            "raw_data_path": self._raw_data_path.as_posix(),
            "ses_name": self._ses_name,
            "run_name": self._run_name,
            "file_format": self._file_format,
            "session_output_path": self._session_output_path.as_posix(),
            "pp_steps": self._pp_steps,
            "orig_run_names": self._orig_run_names,
            "shank_ids": list(self._preprocessed.keys()),
        }
        with open(path_to_save / canon.spikewrap_info_filename(), "w") as file:
            yaml.dump(to_dump, file)

    def _handle_overwrite_output(self, overwrite: bool) -> None:
        """
        If `overwrite`, delete the preprocessed and sync folders
        from the run output path. Raise if they exist
        and `overwrite` is False.
        """
        for folder in [canon.preprocessed_folder(), canon.sync_folder()]:
            out_folder = self._output_path / folder
            if out_folder.is_dir():
                if overwrite:
                    shutil.rmtree(out_folder)
                else:
                    raise RuntimeError(
                        f"`overwrite` is `False` but data already exists at the run path: {self._output_path}."
                    )

    def plot_preprocessed(
        self,
        mode: Literal["map", "line"],
        time_range: tuple[float, float],
        show_channel_ids: bool,
        show: bool,
        figsize: tuple[int, int],
    ) -> matplotlib.Figure:
        """
        Plot the fully preprocessed data for this run.

        Parameters
        ----------
        mode
            The type of plot to generate. ``"map"`` for a heatmap and ``"line"`` for a line plot.
        time_range
            The time range (start, end) to plot the data within, in seconds.
        show_channel_ids
            If True, the plot will display channel IDs.
        show
              If True, the plot will be displayed immediately (``plt.show()`` call).
        figsize
            The dimensions (width, height) of the figure in inches.
        """
        fig = visualise_run_preprocessed(
            self._run_name,
            show,
            self._preprocessed,
            ses_name=self._ses_name,
            mode=mode,
            time_range=time_range,
            show_channel_ids=show_channel_ids,
            figsize=figsize,
        )

        return fig

    # ---------------------------------------------------------------------------
    # Private Functions
    # ---------------------------------------------------------------------------

    def _save_preprocessed_slurm(
        self, overwrite: bool, chunk_duration_s: float, n_jobs: int, slurm: dict | bool
    ) -> None:
        """
        Use ``submitit`` to run the ``save_preprocessed``
        function for this run in a SLURM job.

        Parameters
        ----------
        see ``save_preprocessed``

        Notes
        -----
        This function is a little confusing because it is recursive. ``submitit``
        works by pickling the class / method to run, requesting a job and running
        the pickled method from within the SLURM job.

        Therefore, we need to tell ``submitit`` to run ``save_preprocessed`` with
        the passed kwargs from within the SLURM job, but we do not want to run it
        from within a SLURM job again because we will spawn infinite SLURM jobs!
        So when we run the function from within the SLURM job, we must set ``slurm=False``.
        """
        slurm_ops: dict | bool = slurm if isinstance(slurm, dict) else False

        # 1) find last slurm job ID from slurm_logs
        # 2) run command to check if it is currently running
        # 3) if it is currently running, or is (schedule to run) then raise an error
        # 4) do the same for preprocessing
        # 5) finish docs
        # 6) finish tests

        _slurm.run_in_slurm(
            slurm_ops,
            func_to_run=self.save_preprocessed,
            func_opts={
                "overwrite": overwrite,
                "chunk_duration_s": chunk_duration_s,
                "n_jobs": n_jobs,
                "slurm": False,
            },
            log_base_path=self._output_path,
        )

    def _save_sync_channel(self) -> None:
        """
        Save the sync channel as a ``.npy`` file.

        In SI, sorting cannot proceed if the sync channel is loaded to ensure
        it does not interfere with sorting. As such, a separate recording with the
        sync channel present is maintained and handled separately here.
        """
        if self._sync:
            _utils.message_user(f"Saving sync channel for: {self._run_name}...")

            # extract the sync channel from the recording object
            select_sync_recording = self._sync.select_channels(
                [self._sync.get_channel_ids()[-1]]
            )
            sync_data = select_sync_recording.get_traces()[:, 0]

            assert sync_data.size == select_sync_recording.get_num_samples()

            # Save the sync channel
            sync_output_filepath = (
                self._output_path / canon.sync_folder() / canon.saved_sync_filename()
            )
            sync_output_filepath.parent.mkdir(parents=True, exist_ok=True)
            np.save(sync_output_filepath, sync_data)
