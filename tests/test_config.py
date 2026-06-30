import os

from woodpecker_mcp.config import _load_dotenv


def test_load_dotenv_sets_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("WP_TEST_ABC", raising=False)
    monkeypatch.delenv("WP_TEST_QUOTED", raising=False)
    p = tmp_path / ".env"
    p.write_text('WP_TEST_ABC=hello\n# a comment\n\nWP_TEST_QUOTED="q v"\n')
    _load_dotenv(str(p))
    assert os.environ["WP_TEST_ABC"] == "hello"
    assert os.environ["WP_TEST_QUOTED"] == "q v"  # surrounding quotes stripped


def test_existing_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("WP_TEST_XYZ", "real")
    p = tmp_path / ".env"
    p.write_text("WP_TEST_XYZ=fromfile\n")
    _load_dotenv(str(p))
    assert os.environ["WP_TEST_XYZ"] == "real"  # setdefault: existing value wins


def test_missing_file_is_noop():
    _load_dotenv(str("/no/such/.env"))  # must not raise
