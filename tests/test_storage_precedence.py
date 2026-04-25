import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_get_initial_data_dir_prefers_ui_override_file_over_env(monkeypatch, tmp_path):
    from backend.utils.storage import get_initial_data_dir

    override_file = tmp_path / ".override"
    ui_dir = tmp_path / "ui-data"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "env-data"))
    monkeypatch.setenv("APP_DATA_DIR_OVERRIDE_FILE", str(override_file))
    override_file.write_text(str(ui_dir), encoding="utf-8")

    assert get_initial_data_dir() == ui_dir
