"""Extended unit tests for infrastructure modules."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── profiler ───────────────────────────────────────────────────────


class TestProfiler:
    def test_is_enabled_default(self) -> None:
        from echo_personal_tool.infrastructure.profiler import is_enabled

        # Default is disabled (ECHO_PROFILE not set)
        result = is_enabled()
        assert isinstance(result, bool)

    def test_profiled_decorator_disabled(self) -> None:
        from echo_personal_tool.infrastructure.profiler import profiled

        @profiled
        def my_func():
            return 42

        # When profiling is disabled, function should still work
        result = my_func()
        assert result == 42

    def test_profile_block_disabled(self) -> None:
        from echo_personal_tool.infrastructure.profiler import profile_block

        with profile_block("test"):
            x = 1 + 1
        assert x == 2

    def test_print_summary_disabled(self) -> None:
        from echo_personal_tool.infrastructure.profiler import print_summary

        # Should not crash when profiling is disabled
        print_summary()

    def test_profiled_with_exception(self) -> None:
        from echo_personal_tool.infrastructure.profiler import profiled

        @profiled
        def failing_func():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            failing_func()


# ── runtime_setup ──────────────────────────────────────────────────


class TestRuntimeSetup:
    def test_check_python_version(self) -> None:
        from echo_personal_tool.infrastructure.runtime_setup import check_python_version

        result = check_python_version()
        assert isinstance(result, bool)
        assert result is True  # Python 3.11 >= 3.10

    def test_setup_status(self) -> None:
        from echo_personal_tool.infrastructure.runtime_setup import SetupStatus, get_setup_status

        status = get_setup_status()
        assert isinstance(status, SetupStatus)
        assert isinstance(status.venv_exists, bool)
        assert isinstance(status.deps_installed, bool)
        assert isinstance(status.models_exist, bool)
        assert isinstance(status.python_ok, bool)

    def test_required_packages_list(self) -> None:
        from echo_personal_tool.infrastructure.runtime_setup import _REQUIRED_PACKAGES

        assert len(_REQUIRED_PACKAGES) > 0
        assert "PySide6" in _REQUIRED_PACKAGES
        assert "numpy" in _REQUIRED_PACKAGES

    def test_models_dir_constant(self) -> None:
        from echo_personal_tool.infrastructure.runtime_setup import _MODELS_DIR, _VENV_DIR

        assert _MODELS_DIR is not None
        assert _VENV_DIR is not None

    def test_report_callback(self) -> None:
        from echo_personal_tool.infrastructure.runtime_setup import _report

        callback = MagicMock()
        _report(callback, "test message", 50)
        callback.assert_called_once_with("test message", 50)

    def test_report_none_callback(self) -> None:
        from echo_personal_tool.infrastructure.runtime_setup import _report

        _report(None, "test", 50)  # should not crash

    def test_report_exception_swallowed(self) -> None:
        from echo_personal_tool.infrastructure.runtime_setup import _report

        callback = MagicMock(side_effect=RuntimeError("oops"))
        _report(callback, "test", 50)  # should not crash


# ── reference_model extended ───────────────────────────────────────


class TestReferenceModelExtended:
    def test_topic_model_from_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import TopicModel

        d = {"name": "Cardiac", "slug": "cardiac", "pathologies": []}
        topic = TopicModel.from_dict(d)
        assert topic.name == "Cardiac"
        assert topic.slug == "cardiac"

    def test_topic_model_to_dict(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import TopicModel

        topic = TopicModel(name="Test", slug="test", pathologies=[])
        d = topic.to_dict()
        assert d["name"] == "Test"
        assert d["slug"] == "test"

    def test_reference_model_from_dict_deep(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import ReferenceModel

        d = {
            "topics": [
                {
                    "name": "T",
                    "slug": "t",
                    "pathologies": [
                        {
                            "name": "P",
                            "slug": "p",
                            "parameters": [
                                {"id": "p1", "name": "P1", "unit": "mm"}
                            ],
                        }
                    ],
                }
            ]
        }
        model = ReferenceModel.from_dict(d)
        assert len(model.topics) == 1
        assert model.topics[0].pathologies[0].parameters[0].id == "p1"

    def test_parameter_model_with_norms(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            NormRangeModel,
            ParameterModel,
        )

        param = ParameterModel(
            id="LVIDd",
            name="LVIDd",
            unit="mm",
            norm_male=NormRangeModel(low=35.0, high=57.0),
            norm_female=NormRangeModel(low=32.0, high=52.0),
            pathology_desc="Dilated in DCM",
            source="ASE Guidelines",
        )
        d = param.to_dict()
        assert d["norm_male"]["low"] == 35.0
        assert d["norm_female"]["high"] == 52.0
        assert d["source"] == "ASE Guidelines"

    def test_pathology_model_with_gradations(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            GradationModel,
            ParameterModel,
            PathologyModel,
        )

        grad = GradationModel(
            name="Mild",
            parameters=[ParameterModel(id="p1", name="P1")],
        )
        patho = PathologyModel(
            name="HCM",
            gradations=[grad],
        )
        d = patho.to_dict()
        assert len(d["gradations"]) == 1
        assert d["gradations"][0]["name"] == "Mild"

    def test_pathology_model_all_parameters(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            GradationModel,
            ParameterModel,
            PathologyModel,
        )

        param1 = ParameterModel(id="p1", name="P1")
        param2 = ParameterModel(id="p2", name="P2")
        grad = GradationModel(name="Mild", parameters=[param2])
        patho = PathologyModel(
            name="HCM",
            parameters=[param1],
            gradations=[grad],
        )
        all_params = patho.all_parameters()
        # When has_gradations is True, only gradation parameters are returned
        assert len(all_params) == 1
        assert all_params[0].id == "p2"

    def test_pathology_model_all_parameters_flat(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            ParameterModel,
            PathologyModel,
        )

        param1 = ParameterModel(id="p1", name="P1")
        param2 = ParameterModel(id="p2", name="P2")
        patho = PathologyModel(
            name="HCM",
            parameters=[param1, param2],
        )
        all_params = patho.all_parameters()
        assert len(all_params) == 2

    def test_pathology_model_has_gradations(self) -> None:
        from echo_personal_tool.constructor.models.reference_model import (
            GradationModel,
            PathologyModel,
        )

        patho_with = PathologyModel(gradations=[GradationModel(name="Mild")])
        patho_without = PathologyModel()
        assert patho_with.has_gradations is True
        assert patho_without.has_gradations is False