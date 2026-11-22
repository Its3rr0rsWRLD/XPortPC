"""Write a range manifest for cpu_switch_aot --bind-ranges from a linker map's source labels.

For each NAME, the function's start is the public symbol NAME and its end the public symbol
NAME_end, both read from the MSVC /MAP file of IMAGE. The manifest is bound to IMAGE by its SHA-256,
so it only applies to that exact build.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

SYMBOL = re.compile(r"^\s*[0-9a-fA-F]{4}:[0-9a-fA-F]{8}\s+(\S+)\s+([0-9a-fA-F]{16})\b")
BASE = re.compile(r"Preferred load address is ([0-9a-fA-F]{16})")


def map_symbols(text):
    base = BASE.search(text)
    if not base:
        raise ValueError("linker map without a preferred load address")
    base = int(base.group(1), 16)
    symbols = {}
    for line in text.splitlines():
        match = SYMBOL.match(line)
        if match:
            symbols.setdefault(match.group(1), int(match.group(2), 16) - base)
    return symbols


def manifest(image, map_file, names):
    symbols = map_symbols(Path(map_file).read_text(encoding="utf-8", errors="replace"))
    functions = []
    for name in names:
        if name not in symbols or f"{name}_end" not in symbols:
            raise ValueError(f"linker map has no {name} or {name}_end")
        functions.append({"name": name, "start": f"{symbols[name]:#x}", "end": f"{symbols[name + '_end']:#x}"})
    return {"image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(), "functions": functions}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path)
    parser.add_argument("map", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("names", nargs="+")
    args = parser.parse_args()
    try:
        args.output.write_text(json.dumps(manifest(args.image, args.map, args.names), indent=2) + "\n",
                               encoding="utf-8")
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")
