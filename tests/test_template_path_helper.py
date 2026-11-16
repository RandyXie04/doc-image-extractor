import pytest
from pathlib import Path
from unittest.mock import patch

from src.utils.path_helper import resolve_active_template_path, get_template_path


def test_resolve_active_template_path_default():
    resolved = resolve_active_template_path()
    assert resolved is not None
    assert resolved.exists()
    assert resolved.suffix.lower() == ".docx"


def test_resolve_active_template_path_preferred_override(tmp_path):
    custom_template = tmp_path / "custom.docx"
    custom_template.write_bytes(b"dummy docx")
    resolved = resolve_active_template_path(custom_template)
    assert resolved == custom_template.resolve()


def test_resolve_active_template_path_nonexistent_preferred():
    resolved = resolve_active_template_path("non_existent_file_xyz_123.docx")
    assert resolved is not None
    assert resolved.exists()
    assert resolved.suffix.lower() == ".docx"


def test_resolve_active_template_path_none_when_all_missing(tmp_path):
    non_existent = tmp_path / "none.docx"
    with patch("src.utils.path_helper.get_data_dir", return_value=tmp_path / "data"), \
         patch("src.utils.path_helper.get_template_path", return_value=tmp_path / "pkg.docx"), \
         patch("src.utils.path_helper.get_config_dir", return_value=tmp_path / "cfg"), \
         patch("src.utils.path_helper.get_project_dir", return_value=tmp_path / "prj"):
        resolved = resolve_active_template_path(non_existent)
        assert resolved is None
