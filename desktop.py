"""Windowed entry point used by PyInstaller (CLI remains python -m pdfunlock)."""

import multiprocessing
import sys


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        try:
            from pdfunlock.self_test import main
        except Exception:
            # Report bundled dependency failures before the GUI can initialize.
            import json
            from pathlib import Path
            import traceback
            directory = Path(sys.argv[2]).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "self-test.json").write_text(json.dumps({
                "ok": False, "frozen": bool(getattr(sys, "frozen", False)),
                "error": traceback.format_exc(),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            sys.exit(1)
        sys.exit(main(sys.argv[2]))
    from pdfunlock.gui import main
    sys.exit(main())
