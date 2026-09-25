# -*- coding: utf-8 -*-
"""ASCII-named launcher for the weekly GitHub Trending crawler.

Windows cmd mangles Chinese filenames across code pages, so the .bat
calls this ASCII-named file instead, and this launcher locates the
real crawler (爬虫.py) by its content marker and executes it.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = "TRENDING_URL"
SELF = os.path.basename(__file__).lower()


def find_crawler():
    for name in sorted(os.listdir(HERE)):
        if not name.endswith(".py"):
            continue
        if name.lower() == SELF:
            continue
        path = os.path.join(HERE, name)
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                head = fh.read(8000)
        except OSError:
            continue
        if MARKER in head:
            return path
    return None


def main():
    target = find_crawler()
    if not target:
        print(f"[launcher] ERROR: crawler with marker '{MARKER}' not found in {HERE}")
        return 1
    print(f"[launcher] running crawler: {target}")
    sys.argv = [target]
    runpy.run_path(target, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
