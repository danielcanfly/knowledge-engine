from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    source_path = Path(__file__).with_name("l3b_preservation_successor_builder.py")
    source = source_path.read_text()
    old = '    run(sys.executable, "-m", "pytest", "-q", *public_tests)\n'
    new = (
        '    for public_test in public_tests:\n'
        '        print(f"PUBLIC_REGRESSION_ISOLATED={public_test}", flush=True)\n'
        '        run(sys.executable, "-m", "pytest", "-q", public_test)\n'
        '    print(f"PUBLIC_REGRESSION_ISOLATED_COUNT={len(public_tests)}", flush=True)\n'
    )
    if source.count(old) != 1:
        raise SystemExit(f"expected exactly one public regression cohort anchor, got {source.count(old)}")
    patched = source.replace(old, new, 1)
    globals_dict = {
        "__name__": "__main__",
        "__file__": str(source_path),
        "__package__": None,
    }
    exec(compile(patched, str(source_path), "exec"), globals_dict)


if __name__ == "__main__":
    main()
