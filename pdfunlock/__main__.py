"""Launch the desktop interface with --gui, or the known-password CLI."""

import sys


def run():
    if sys.argv[1:] == ["--gui"]:
        from pdfunlock.gui import main
    else:
        from pdfunlock.cli import main
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
