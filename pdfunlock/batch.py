"""Known-password batch decryption, independent of the desktop interface."""

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Iterable, Iterator
import tempfile

import pikepdf

from pdfunlock.output import save_unencrypted


@dataclass(frozen=True)
class FileResult:
    source: Path
    status: str
    message: str
    output: Path | None = None


def parse_passwords(text: str) -> list[str]:
    """One candidate per line; preserve significant spaces and deduplicate."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return list(dict.fromkeys(line for line in lines if line != ""))


def prepare_output_directory(directory: str | Path) -> Path:
    path = Path(directory).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    # Detect an unwritable destination before starting the batch.
    with tempfile.TemporaryFile(dir=path):
        pass
    return path


def decrypt_file(source: str | Path, passwords: Iterable[str], output_dir: str | Path,
                 cancel: Event | None = None) -> FileResult:
    source = Path(source)
    cancelled = lambda: cancel is not None and cancel.is_set()
    try:
        # Empty password also handles plain PDFs and owner-only restrictions.
        for password in dict.fromkeys(["", *passwords]):
            if cancelled():
                return FileResult(source, "cancelled", "已取消，可重新开始")
            try:
                pdf = pikepdf.open(source, password=password)
            except pikepdf.PasswordError:
                continue
            with pdf:
                if cancelled():
                    return FileResult(source, "cancelled", "已取消，可重新开始")
                encrypted = pdf.is_encrypted
                output = Path(save_unencrypted(pdf, source, output_dir))
            return FileResult(source, "success", "已解密" if encrypted else "未加密，已导出副本", output)
        return FileResult(source, "failed", "密码不匹配，请检查已知密码")
    except FileNotFoundError:
        return FileResult(source, "failed", "文件或导出目录不存在")
    except PermissionError:
        return FileResult(source, "failed", "没有读写权限，或文件被占用")
    except pikepdf.PdfError:
        return FileResult(source, "failed", "PDF 损坏或使用了不支持的加密")
    except OSError:
        return FileResult(source, "failed", "读写失败，请检查路径与磁盘空间")
    except Exception:
        # Do not expose passwords or native-library diagnostics in the UI/logs.
        return FileResult(source, "failed", "处理失败，请检查文件后重试")


def decrypt_batch(sources: Iterable[str | Path], passwords: Iterable[str],
                  output_dir: str | Path, cancel: Event | None = None) -> Iterator[FileResult]:
    candidates = tuple(passwords)
    for source in sources:
        yield decrypt_file(source, candidates, output_dir, cancel)
