from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pikepdf
import pytest

from pdfunlock.batch import decrypt_batch, decrypt_file, parse_passwords
from pdfunlock import output


def test_mixed_batch_continues_after_failure(user_pw_pdf, owner_pw_pdf, plain_pdf, tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a PDF")
    sources = [user_pw_pdf, broken, owner_pw_pdf, plain_pdf]
    originals = [p.read_bytes() for p in sources]
    results = list(decrypt_batch(sources, ["wrong", "secret42"], tmp_path / "exports"))
    assert [r.status for r in results] == ["success", "failed", "success", "success"]
    for result in results:
        if result.output:
            assert result.output.parent == tmp_path / "exports"
            with pikepdf.open(result.output) as pdf:
                assert not pdf.is_encrypted
                assert len(pdf.pages) == 1
    assert [p.read_bytes() for p in sources] == originals


def test_wrong_password_does_not_create_output(user_pw_pdf, tmp_path):
    dest = tmp_path / "exports"
    result = decrypt_file(user_pw_pdf, ["bad"], dest)
    assert result.status == "failed"
    assert result.output is None
    assert not dest.exists()


def test_cancel_does_not_write_remaining_files(user_pw_pdf, plain_pdf, tmp_path):
    cancel = Event()
    iterator = decrypt_batch([plain_pdf, user_pw_pdf], ["secret42"], tmp_path / "out", cancel)
    assert next(iterator).status == "success"
    cancel.set()
    assert next(iterator).status == "cancelled"
    assert len(list((tmp_path / "out").iterdir())) == 1


def test_cancellation_between_passwords(monkeypatch, user_pw_pdf, tmp_path):
    cancel = Event()
    original = pikepdf.open
    calls = []

    def open_and_cancel(*args, **kwargs):
        calls.append(kwargs.get("password"))
        cancel.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(pikepdf, "open", open_and_cancel)
    result = decrypt_file(user_pw_pdf, ["wrong", "secret42"], tmp_path, cancel)
    assert result.status == "cancelled"
    assert calls == [""]


def test_same_names_and_existing_output_are_preserved(plain_pdf, tmp_path):
    dest = tmp_path / "导出 目录"
    dest.mkdir()
    existing = dest / "plain_已解密.pdf"
    existing.write_bytes(b"keep me")
    other = tmp_path / "other" / plain_pdf.name
    other.parent.mkdir()
    other.write_bytes(plain_pdf.read_bytes())
    results = list(decrypt_batch([plain_pdf, other], [], dest))
    assert [r.output.name for r in results] == ["plain_已解密_1.pdf", "plain_已解密_2.pdf"]
    assert existing.read_bytes() == b"keep me"


def test_concurrent_exports_never_overwrite(plain_pdf, tmp_path):
    dest = tmp_path / "out"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: decrypt_file(plain_pdf, [], dest), range(8)))
    assert all(r.status == "success" for r in results)
    assert len({r.output for r in results}) == 8
    assert len(list(dest.iterdir())) == 8


def test_save_failure_cleans_partial_files(monkeypatch, plain_pdf, tmp_path):
    dest = tmp_path / "out"

    def fail_replace(*_):
        raise OSError("disk full")

    monkeypatch.setattr(output.os, "rename" if output.os.name == "nt" else "link", fail_replace)
    assert decrypt_file(plain_pdf, [], dest).status == "failed"
    assert list(dest.iterdir()) == []


def test_missing_source_is_reported(tmp_path):
    assert decrypt_file(tmp_path / "absent.pdf", [], tmp_path).status == "failed"


def test_unwritable_destination_is_reported(plain_pdf, tmp_path):
    dest = tmp_path / "not-a-directory"
    dest.write_text("existing file")
    assert decrypt_file(plain_pdf, [], dest).status == "failed"
    assert dest.read_text() == "existing file"


def test_password_spaces_are_significant(tmp_path):
    source = tmp_path / "中文 密码.pdf"
    with pikepdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(source, encryption=pikepdf.Encryption(user=" 密码 ", owner="owner"))
    assert parse_passwords("wrong\n 密码 \n\n 密码 ") == ["wrong", " 密码 "]
    result = decrypt_file(source, parse_passwords("密码\n 密码 "), tmp_path / "out")
    assert result.status == "success"


def test_windows_password_line_endings():
    assert parse_passwords("first\r\n second \r\n\r\nfirst") == ["first", " second "]


@pytest.mark.parametrize("revision", [2, 3, 4, 6])
def test_standard_encryption_revisions(tmp_path, revision):
    source = tmp_path / "protected.pdf"
    with pikepdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(source, encryption=pikepdf.Encryption(
            user="known", owner="owner", R=revision, aes=revision >= 4, metadata=revision >= 4))
    result = decrypt_file(source, ["known"], tmp_path / "out")
    assert result.status == "success"
    with pikepdf.open(result.output) as pdf:
        assert not pdf.is_encrypted


def test_empty_password_copies_plain_pdf(plain_pdf, tmp_path):
    result = decrypt_file(plain_pdf, [], tmp_path / "out")
    assert result.message == "未加密，已导出副本"


def test_known_owner_password_can_unlock_user_protection(tmp_path):
    source = tmp_path / "owner.pdf"
    with pikepdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(source, encryption=pikepdf.Encryption(user="user", owner="owner"))
    assert decrypt_file(source, ["owner"], tmp_path / "out").status == "success"
