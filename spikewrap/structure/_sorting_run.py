from pathlib import Path

import spikeinterface
import spikeinterface.full as si
from spikeinterface.sorters import run_sorter
from spikeinterface.sorters.runsorter import SORTER_DOCKER_MAP

from spikewrap.processing._preprocessing_run import (
    ConcatPreprocessRun,
    SeparatePreprocessRun,
)
from spikewrap.utils import _managing_sorters, _slurm, _utils


class BaseSortingRun:
    """ """

    def __init__(
        self, run_name, session_output_path, output_path, preprocessed_recording
    ):
        self._run_name = run_name
        self._session_output_path = session_output_path
        self._output_path = output_path
        self._preprocessed_recording = preprocessed_recording

    def sort(
        self,
        sorting_configs: dict,
        run_sorter_method: str,
        per_shank: bool,
        overwrite: bool,
        slurm: bool | dict,
    ):
        """

        Parameters
        ----------

        """
        if slurm:
            self._sort_slurm(
                sorting_configs, run_sorter_method, per_shank, overwrite, slurm
            )
            return

        assert len(sorting_configs) == 1, "Only one sorter supported."
        ((sorter, sorter_kwargs),) = sorting_configs.items()

        run_docker, run_singularity = _managing_sorters._configure_run_sorter_method(
            run_sorter_method,
            sorter,
            self.get_singularity_image_path(sorter),  # TODO: maybe move that move
        )

        if per_shank:
            self.split_per_shank()

        self.handle_overwrite_output_path(overwrite)

        for rec_name, recording in self._preprocessed_recording.items():

            out_path = self._output_path
            if rec_name != "grouped":
                out_path = out_path / f"shank_{rec_name}"

            run_sorter(
                sorter_name=sorter,
                recording=recording,
                folder=out_path,
                verbose=True,
                docker_image=run_docker,
                singularity_image=run_singularity,
                remove_existing_folder=False,
                **sorter_kwargs,
            )

    def _sort_slurm(
        self,
        sorting_configs: dict,
        run_sorter_method: str | Path,
        per_shank: bool,
        overwrite: bool,
        slurm: bool | dict,
    ):
        """ """
        slurm_ops: dict | bool = slurm if isinstance(slurm, dict) else False

        _slurm.run_in_slurm(
            slurm_ops,
            func_to_run=self.sort,
            func_opts={
                "sorting_configs": sorting_configs,
                "run_sorter_method": run_sorter_method,
                "per_shank": per_shank,
                "overwrite": overwrite,
                "slurm": False,
            },
            log_base_path=self._output_path,
        )

    def handle_overwrite_output_path(self, overwrite):
        """ """
        if self._output_path.is_dir():
            if overwrite:
                _utils.message_user(
                    f"`overwrite=True`, so deleting all files and folders "
                    f"(except for slurm_logs) at the path:\n"
                    f"{self._output_path}"
                )
                _slurm._delete_folder_contents_except_slurm_logs(self._output_path)
            else:
                raise RuntimeError("need `overwrite`.")

    def split_per_shank(self):
        """ """
        if "grouped" not in self._preprocessed_recording:
            raise RuntimeError(
                "`per_shank=True` but the recording was already split per shank for preprocessing."
            )
        assert (
            len(self._preprocessed_recording) == 1
        ), "There should only be a single recording before splitting by shank."

        recording = self._preprocessed_recording["grouped"]

        if recording.get_property("group") is None:
            raise ValueError(
                f"Cannot split run {self._run_name} by shank as there is no 'group' property."
            )

        self._preprocessed_recording = recording.split_by("group")

    def get_singularity_image_path(
        self, sorter: str
    ) -> Path:  # TODO: maybe pass this from above.
        """ """
        spikeinterface_version = spikeinterface.__version__

        sorter_path = (
            self._session_output_path.parent.parent.parent  # TODO: hacky, this is the folder containing rawdata / derivatives
            / "sorter_images"
            / sorter
            / spikeinterface_version
            / SORTER_DOCKER_MAP[sorter]
        )

        if not sorter_path.is_file():
            _managing_sorters._download_sorter(sorter, sorter_path)

        return sorter_path


class SortingRun(BaseSortingRun):
    def __init__(
        self,
        pp_run: ConcatPreprocessRun | SeparatePreprocessRun,
        session_output_path: Path,
    ):
        """ """
        run_name = pp_run._run_name
        output_path = session_output_path / run_name / "sorting"

        preprocessed_recording = {
            key: _utils._get_dict_value_from_step_num(preprocessed_data._data, "last")[
                0
            ]
            for key, preprocessed_data in pp_run._preprocessed.items()
        }

        super().__init__(
            run_name, session_output_path, output_path, preprocessed_recording
        )


class ConcatSortingRun(BaseSortingRun):
    def __init__(
        self, pp_runs_list: list[SeparatePreprocessRun], session_output_path: Path
    ):
        """
        TODO

        """
        run_name = "concat_run"
        output_path = session_output_path / run_name / "sorting"

        shank_keys = list(pp_runs_list[0]._preprocessed.keys())

        preprocessed_recording: dict = {key: [] for key in shank_keys}

        # Create a dict (key is "grouped" or shank number) of lists where the
        # lists contain all recordings to concatenate for that shank
        for run in pp_runs_list:
            for key in shank_keys:

                assert key in run._preprocessed, (
                    "Somehow grouped and per-shank recordings are mixed. "
                    "This should not happen."
                )

                recording = _utils._get_dict_value_from_step_num(
                    run._preprocessed[key]._data, "last"
                )[0]

                preprocessed_recording[key].append(recording)

        # Concatenate the lists for each shank into a single recording
        for key in shank_keys:
            preprocessed_recording[key] = si.concatenate_recordings(
                preprocessed_recording[key]
            )

        super().__init__(
            run_name, session_output_path, output_path, preprocessed_recording
        )
        self._orig_run_names = [run._run_name for run in pp_runs_list]
