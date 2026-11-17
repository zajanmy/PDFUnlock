"""End-to-end checks for the known-password command-line interface."""

import pikepdf
import pytest

from pdfunlock.cli import main


@pytest.mark.parametrize("mode", ["Dictionary", "BruteForce", "Mask"])
def test_no_cracking_modes(user_pw_pdf, mode):
    with pytest.raises(SystemExit) as error:
        main(["-f", str(user_pw_pdf), "-m", mode])
    assert error.value.code == 2


@pytest.mark.parametrize("mode,fixture,password", [
    ("SinglePassword", "user_pw_pdf", "secret42"),
    ("RemoveRestrictions", "owner_pw_pdf", ""),
])
def test_export_can_be_opened_without_password(mode, fixture, password, request, tmp_path, capsys):
    source = request.getfixturevalue(fixture)
    original = source.read_bytes()
    destination = tmp_path / "exports"
    result = main(["-f", str(source), "-m", mode, "-p", password, "-o", str(destination)])
    assert result == 0
    exported = list(destination.glob("*.pdf"))
    assert len(exported) == 1
    with pikepdf.open(exported[0]) as document:
        assert not document.is_encrypted
    assert source.read_bytes() == original
    if password:
        assert password not in capsys.readouterr().out


def test_failed_password_reports_failure_without_export(user_pw_pdf, tmp_path, capsys):
    destination = tmp_path / "exports"
    assert main(["-f", str(user_pw_pdf), "-m", "SinglePassword", "-p", "wrong", "-o", str(destination)]) == 1
    assert not list(destination.glob("*.pdf"))
    assert "密码不匹配" in capsys.readouterr().out


def test_missing_input_returns_usage_error(tmp_path):
    assert main(["-f", str(tmp_path / "missing.pdf"), "-m", "SinglePassword"]) == 2
