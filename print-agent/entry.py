"""PyInstaller's entry point.

`print_agent/__main__.py` uses relative imports, which fail when PyInstaller runs a
file as a top-level script. This is the script; the package stays a package.
"""

from print_agent.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
