"""Publish complete unencrypted copies without overwriting existing files."""

import os
from pathlib import Path
import tempfile


def save_unencrypted(pdf, source, output_dir):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".pdfunlock-", suffix=".tmp", delete=False) as stream:
            staged = Path(stream.name)
            pdf.save(stream, encryption=False)
        stem = Path(source).stem
        number = 0
        while True:
            suffix = f"_{number}" if number else ""
            destination = directory / f"{stem}_已解密{suffix}.pdf"
            try:
                if os.name == "nt":
                    # Windows rename never replaces a destination that exists.
                    os.rename(staged, destination)
                    staged = None
                else:
                    # Same-filesystem hard link publishes without replacement.
                    os.link(staged, destination)
                return destination
            except FileExistsError:
                number += 1
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
