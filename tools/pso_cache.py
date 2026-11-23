"""The graphics shim's translation cache (docs/design/runtime.md, section 3): keys, the pipeline manifest, and the
translator that tools/pso_service.py and tools/precompile_cache.py share.

Layout of one title's cache directory (%LOCALAPPDATA%\\XPortPC\\cache\\<title>, or X2W_CACHE_DIR\\<title>):
    <key>.bind                its descriptor-table reads (pso_translate.bindings_text), stored before the DXIL
    <key>.dxil                the translated shader (raw DXIL container), as the shim reads it
    manifest.txt              one line "<input> <stage>" per console shader the shim has seen (hex SHA-256, vertex|pixel|compute)
    inputs\\<input>.code       the shader's raw gfx1013 code, as the container held it
    inputs\\<input>.roles.json the entry contract the shim derived from the container and the pipeline
    translator.json           the shim's translator configuration: tools, dxc, llvm, fingerprint (hex)
The manifest and inputs are local to the machine (they hold the title's shader code) and are never shared.

The key (src/d3d12_xs_pipeline.cpp, translated_shader) is SHA-256 over the converter's fingerprint (32 bytes), the
stage (u32), the roles text (u32 length, bytes), the code size (u32) and the code. The fingerprint is SHA-256 over
"x2w-pso-translate-2", the name, size and write time of every converter source (tools/*.py and two directory levels
below, sorted by name, __pycache__ skipped), of src/title_va_lookup.hlsli and of DXC, then the DXC and LLVM paths as
the shim was configured. An input id is the same hash without the fingerprint, with "x2w-pso-input-1" in front, so it
survives a converter change: tools/precompile_cache.py recomputes every key from the inputs with the current
fingerprint. All integers little-endian.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import pso_translate  # noqa: E402

STAGES = {"vertex": 0, "pixel": 1, "compute": 2}
FILETIME_EPOCH = 116444736000000000  # 1601-01-01 to 1970-01-01 in 100 ns units


def _text(sha, text):
    data = text.encode("ascii", "replace") if isinstance(text, str) else text
    sha.update(struct.pack("<I", len(data)))
    sha.update(data)


def _narrow(text):
    return "".join(c if ord(c) < 128 else "?" for c in text)


def _attributes(sha, path):
    info = os.stat(path)
    sha.update(struct.pack("<IQ", info.st_size & 0xffffffff, info.st_mtime_ns // 100 + FILETIME_EPOCH))


def _tree(sha, directory, depth):
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return
    for name in names:
        if name in (".", "..", "__pycache__"):
            continue
        path = os.path.join(directory, name)
        try:
            info = os.stat(path)
        except OSError:
            continue
        if os.path.isdir(path):
            if depth > 0:
                _tree(sha, path, depth - 1)
            continue
        if len(name) <= 3 or not name.endswith(".py"):
            continue
        _text(sha, _narrow(name))
        sha.update(struct.pack("<IQ", info.st_size & 0xffffffff, info.st_mtime_ns // 100 + FILETIME_EPOCH))


def windows_path(path):
    return str(path).replace("/", "\\")


def fingerprint(tools, dxc, llvm=""):
    """The shim's converter fingerprint (load_config in src/d3d12_xs_pipeline.cpp) for these configuration strings."""
    tools, dxc, llvm = windows_path(tools), windows_path(dxc), windows_path(llvm or "")
    sha = hashlib.sha256()
    _text(sha, "x2w-pso-translate-2")
    _tree(sha, tools, 2)
    for path in (os.path.join(tools, "..", "src", "title_va_lookup.hlsli"), dxc):
        try:
            _attributes(sha, path)
        except OSError:
            pass
    _text(sha, _narrow(dxc))
    _text(sha, _narrow(llvm))
    return sha.digest()


def shader_key(fingerprint_bytes, stage, roles, code):
    sha = hashlib.sha256(fingerprint_bytes)
    sha.update(struct.pack("<I", STAGES[stage]))
    _text(sha, roles.encode("utf-8"))
    sha.update(struct.pack("<I", len(code)))
    sha.update(code)
    return sha.hexdigest()


def input_id(stage, roles, code):
    sha = hashlib.sha256()
    _text(sha, "x2w-pso-input-1")
    sha.update(struct.pack("<I", STAGES[stage]))
    _text(sha, roles.encode("utf-8"))
    sha.update(struct.pack("<I", len(code)))
    sha.update(code)
    return sha.hexdigest()


def read_manifest(cache):
    """[(input id, stage)] in first-seen order, duplicates dropped."""
    path = Path(cache) / "manifest.txt"
    entries, seen = [], set()
    if not path.exists():
        return entries
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[1] not in STAGES or len(parts[0]) != 64 or parts[0] in seen:
            continue
        seen.add(parts[0])
        entries.append((parts[0], parts[1]))
    return entries


def read_input(cache, ident):
    inputs = Path(cache) / "inputs"
    return (inputs / f"{ident}.code").read_bytes(), (inputs / f"{ident}.roles.json").read_bytes().decode("utf-8")


def store(path, data):
    """Write `data` to `path` through a temporary file in the same directory, replacing atomically."""
    path = Path(path)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class Translator:
    """Translates one shader at a time with the converter modules imported once and DXC loaded in process
    (pso_translate.DxcLibrary), or dxc.exe per shader where the library cannot be loaded. translate() returns
    (status, message, dxil, hlsl, count, bindings): status 0 translated, 1 refused (message: the reason, as pso_translate.py
    prints it after "refused: "), 2 tool failure. `bindings` is the sidecar text pso_translate.py --bindings writes."""

    def __init__(self, dxc, llvm=None, compiler="library", scratch=None):
        self.dxc, self.llvm, self.scratch = dxc, llvm or None, scratch
        self.library, self.why_process = None, None
        if compiler == "library":
            try:
                self.library = pso_translate.DxcLibrary(dxc)
            except (OSError, AttributeError, pso_translate.ToolFailure) as error:
                self.why_process = str(error)
        else:
            self.why_process = "dxc.exe per shader requested"
        # The lowering modules are imported by the first translation; import them now so it is not slower.
        import pixel_aot  # noqa: F401
        import vertex_aot  # noqa: F401
        from pixel_aot_ops import lowering  # noqa: F401
        import gfx_text  # noqa: F401

    @property
    def compiler(self):
        return "library" if self.library else "process"

    def translate(self, stage, code, roles_text, instructions=None):
        try:
            roles = json.loads(roles_text)
            source, _, bindings, count = pso_translate.translate(stage, code, roles, self.llvm, instructions)
        except (ValueError, KeyError) as error:
            return 1, str(error), b"", "", 0, ""
        except OSError as error:
            return 2, str(error), b"", "", 0, ""
        try:
            if self.library:
                dxil = self.library.compile(stage, source)
            else:
                dxil = pso_translate.compile_with_process(self.dxc, stage, source, self.scratch or tempfile.gettempdir())
        except (pso_translate.ToolFailure, OSError) as error:
            return 2, str(error), b"", source, count, ""
        return 0, "", dxil, source, count, bindings
