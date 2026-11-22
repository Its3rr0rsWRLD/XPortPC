"""Exercise offline pixel translation with independently assembled test programs.

The checks live in tests/pixel_aot_draws/, one module per draw family (docs/design/module-layout.md); this script runs
them: `controls`, `binary <llvm-mc> <llvm-objcopy> <libLLVM>`, `draw <dxc> <renderer> <adapter> [--family NAME]...`
and `--list-families`.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from pixel_aot import disassemble, native_program  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pixel_aot_draws import FAMILIES, MODULES  # noqa: E402
# Other checks import these from here: bc7_draw_check, cpu/native_frame_check, pso_readiness_check, form_coverage_check.
from pixel_aot_draws.common import (ACCEPTED, assembly, lower, must_reject, translate, with_constants,  # noqa: E402,F401
                                    write_record)
from pixel_aot_draws.container import check_container_selector, envelope  # noqa: E402
from pixel_aot_draws.dual import dual_program, translate_dual  # noqa: E402,F401

# Draw families, each a module of tests/pixel_aot_draws/ with draw(directory, compiler, renderer, backend). A family
# compiles what it needs and depends on nothing another family leaves behind, so a process can run any subset.
# `pixel_aot_check.py --list-families` prints these names; CMake makes one CTest test per name. A family
# returns a nonzero exit code (the renderer's 77 for "no adapter") or raises on failure.
DRAW_FAMILIES = {name: module.draw for name, module in FAMILIES.items()}


def check_controls(directory):
    """Every module's controls: translation checks that need neither DXC nor a GPU."""
    for module in MODULES:
        if hasattr(module, "controls"):
            module.controls(directory)
    check_adapter_skip(directory)


def check_adapter_skip(directory):
    """Without a hardware adapter the renderer exits 77, and every family must report that skip to CTest, not a
    failure (from R0Y00/Xbox2Windows#322 by Vonsek). The compiler is a stub that writes empty outputs."""
    compiler, renderer = "stub-dxc", "stub-offscreen"

    def run_without_adapter(args, *, check=False, **_):
        assert args[0] in (compiler, renderer), args
        if args[0] == compiler:
            for flag, text in (("-Fo", ""), ("-Fc", "fcmp uno \n")):
                if flag in args:
                    Path(args[args.index(flag) + 1]).write_text(text, encoding="ascii")
        result = subprocess.CompletedProcess(args, 77 if args[0] == renderer else 0, "", "")
        if check:
            result.check_returncode()
        return result

    for name in DRAW_FAMILIES:
        work = directory / f"no-adapter-{name}"
        work.mkdir()
        with patch.object(subprocess, "run", side_effect=run_without_adapter):
            code = check_render(work, compiler, renderer, "hardware", [name])
        assert code == 77, (name, code)


def check_binary(directory, assembler, objcopy, library):
    fixtures = [fixture for module in MODULES if hasattr(module, "binary_fixtures")
                for fixture in module.binary_fixtures()]
    selector = assembly(False)  # the program the container selection is checked with, once
    for entry in fixtures:
        instructions, lower_fixture = entry[:2]
        cpu = entry[2] if len(entry) > 2 else "gfx1013"  # a fixture may name another target (the dot products: gfx1030)
        source = directory / "fixture.s"
        obj = directory / "fixture.o"
        binary = directory / "fixture.bin"
        source.write_text("\n".join(instructions) + "\n", encoding="ascii")
        subprocess.run([assembler, "-triple=amdgcn--amdpal", f"-mcpu={cpu}",
                        "-filetype=obj", source, "-o", obj], check=True)
        subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
        archive = directory / "fixture.rpf"
        archive.write_bytes(envelope(binary.read_bytes()))
        _, native = native_program(archive, "fixture")
        assert native == binary.read_bytes()
        assert lower_fixture(disassemble(native, library, cpu=cpu.encode())) == lower_fixture(instructions)
        if instructions == selector:
            check_container_selector(directory, native, library)
            selector = None


def check_render(directory, compiler, renderer, backend, families=None):
    for name in families or DRAW_FAMILIES:
        try:
            code = DRAW_FAMILIES[name](directory, compiler, renderer, backend)
        except subprocess.CalledProcessError as error:
            if error.returncode != 77:  # the renderer found no adapter: skip, like the channel-order draw
                raise
            return 77
        if code:
            return code
    return 0


def main():
    mode, *args = sys.argv[1:]
    if mode == "--list-families":
        print("\n".join(DRAW_FAMILIES))
        return 0
    families = []
    while "--family" in args:  # draw mode: only these families (repeatable); none means all and the controls
        at = args.index("--family")
        families.append(args[at + 1])
        del args[at:at + 2]
    unknown = [name for name in families if name not in DRAW_FAMILIES]
    if unknown or (families and mode != "draw"):
        raise ValueError(f"Unknown or misplaced --family {unknown}; known families: {', '.join(DRAW_FAMILIES)}")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        if mode == "controls":
            check_controls(directory)
        elif mode == "binary":
            check_controls(directory)
            check_binary(directory, *args)
        elif mode == "draw":
            if not families:
                check_controls(directory)
            return check_render(directory, *args, families or None)
        else:
            raise ValueError("Expected binary, controls or draw mode")


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:  # also on skip or failure; tools/form_coverage.py reads the test's status from JUnit
        write_record(os.environ.get("FORM_COVERAGE_RECORD"))
