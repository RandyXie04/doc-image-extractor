# -*- coding: utf-8 -*-
"""
Unit tests for unified flat models/ layout, model_manager download/fallback,
version.json SHA256 alignment, and Surya local checkpoint discovery.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config import PATHS, VERSION
from src.scripts import model_manager, process_ocr


class TestModelManagerAndVersionSync:
    """Verifies model_manager constants, SHA256 sync, and directory hygiene."""

    def test_default_model_and_surya_registry(self) -> None:
        assert model_manager.DEFAULT_MODEL_NAME == "pdf_extract_mfd.onnx"
        assert set(model_manager.SURYA_MODELS.keys()) == {
            "surya_det3",
            "surya_rec2",
            "surya_layout0",
        }
        assert "surya_order" not in model_manager.SURYA_MODELS
        assert "order" not in model_manager.SURYA_MODELS

    def test_version_json_hash_matches_local_pdf_extract_mfd_onnx(self) -> None:
        onnx_path = PATHS.models_dir / "pdf_extract_mfd.onnx"
        if not onnx_path.is_file():
            pytest.skip("models/pdf_extract_mfd.onnx not present on disk.")

        sha256 = hashlib.sha256()
        with open(onnx_path, "rb") as f:
            for chunk in iter(lambda: f.read(1048576), b""):
                sha256.update(chunk)

        version_data = json.loads((PATHS.root / "version.json").read_text(encoding="utf-8"))
        assert version_data["model_hash"] == sha256.hexdigest()
        assert VERSION.model_hash == sha256.hexdigest()

    def test_ensure_all_does_not_recreate_legacy_surya_pt_dir(self) -> None:
        assert PATHS.surya_pt_dir == PATHS.models_dir
        assert PATHS.get_model_path.__defaults__ == ("pdf_extract_mfd.onnx",)
        PATHS.ensure_all()
        assert not (PATHS.models_dir / "surya_pt").exists()

    def test_ensure_model_ready_falls_back_from_github_to_hf_export(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SKIP_MODEL_DOWNLOAD", raising=False)
        for name in model_manager.SURYA_MODELS:
            d = tmp_path / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.safetensors").write_bytes(b"stub")

        exported_file = tmp_path / "pdf_extract_mfd.onnx"

        def fake_export(**kwargs):
            out = Path(kwargs["output_path"])
            out.write_bytes(b"onnx-stub")
            return out

        mock_paths = MagicMock()
        mock_paths.models_dir = tmp_path

        with (
            patch.object(model_manager, "PATHS", mock_paths),
            patch.object(model_manager, "_get_exact_model_path", return_value=None),
            patch.object(model_manager, "try_download_model_from_github", return_value=None) as mock_gh,
            patch("src.scripts.export_mfd_onnx.export_mfd_to_onnx", side_effect=fake_export) as mock_export,
        ):
            res = model_manager.ensure_model_ready()

        assert res["status"] == "ready"
        assert res["engine"] == "onnx"
        assert res["path"] == exported_file
        mock_gh.assert_called_once_with(tmp_path)
        mock_export.assert_called_once()
        call_kwargs = mock_export.call_args.kwargs
        assert call_kwargs["imgsz"] == 1280
        assert call_kwargs["download_if_missing"] is True


class TestProcessOcrCheckpointDiscovery:
    """Verifies flat models/surya_* checkpoint resolution and legacy Segformer guard."""

    @pytest.fixture(autouse=True)
    def _clear_checkpoint_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in (
            "RECOGNITION_MODEL_CHECKPOINT",
            "DETECTOR_MODEL_CHECKPOINT",
            "LAYOUT_MODEL_CHECKPOINT",
            "ORDER_MODEL_CHECKPOINT",
            "SURYA_PT_PATH",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_maps_flat_surya_checkpoints_independently(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("surya_rec2", "surya_det3", "surya_layout0"):
            d = tmp_path / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.safetensors").write_bytes(b"weights")

        (tmp_path / "surya_layout0" / "config.json").write_text(
            json.dumps({"architectures": ["SuryaLayoutModel"]}), encoding="utf-8"
        )
        monkeypatch.setenv("SURYA_PT_PATH", str(tmp_path))

        import os

        process_ocr._configure_local_surya_checkpoints()

        assert os.environ["RECOGNITION_MODEL_CHECKPOINT"] == str(tmp_path / "surya_rec2")
        assert os.environ["DETECTOR_MODEL_CHECKPOINT"] == str(tmp_path / "surya_det3")
        assert os.environ["LAYOUT_MODEL_CHECKPOINT"] == str(tmp_path / "surya_layout0")
        assert "ORDER_MODEL_CHECKPOINT" not in os.environ

    def test_rejects_segformer_legacy_layout_while_preserving_rec_and_det(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("surya_rec2", "surya_det3", "surya_layout0"):
            d = tmp_path / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.safetensors").write_bytes(b"weights")

        (tmp_path / "surya_layout0" / "config.json").write_text(
            json.dumps({"architectures": ["SegformerForRegressionMask"]}), encoding="utf-8"
        )
        monkeypatch.setenv("SURYA_PT_PATH", str(tmp_path))

        import os

        process_ocr._configure_local_surya_checkpoints()

        assert os.environ["RECOGNITION_MODEL_CHECKPOINT"] == str(tmp_path / "surya_rec2")
        assert os.environ["DETECTOR_MODEL_CHECKPOINT"] == str(tmp_path / "surya_det3")
        assert "LAYOUT_MODEL_CHECKPOINT" not in os.environ
