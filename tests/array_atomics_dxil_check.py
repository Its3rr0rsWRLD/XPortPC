"""Check that the built ProbeArrayAtomics keeps its atomic's resource index non-uniform (#369).

Usage: array_atomics_dxil_check.py DXC PROBE_CSO SOURCE_HLSL INCLUDE_DIR

1. Disassemble PROBE_CSO, the cs_6_0 shader that offscreen_check embeds for
   --gpu-alias-lookup-writes. Follow the atomic's handle operand back to the instruction that
   creates it, check that the handle selects the Aliases UAV range (u0, space1, 8 descriptors),
   that its index is computed from the dispatch thread ID and that nonUniformIndex is true.
2. Compile SOURCE_HLSL again as cs_6_0 with NonUniformResourceIndex removed and check that the
   same trace finds the same handle with nonUniformIndex false.

Operands are followed by value, so SSA renumbering or unrelated disassembly changes do not
affect the result. The compiler identification of each measured module is printed.

Manual diagnostics, not run by CTest: pass a cs_6_6 build of the probe, or a probe compiled with
another DXC, as PROBE_CSO. The cs_6_6 createHandleFromBinding and annotateHandle forms are traced
the same way.
"""

from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

ENTRY = "ProbeArrayAtomics"
INTRINSIC = "NonUniformResourceIndex("
UAV_CLASS = 1
ALIASES = {"space": 1, "lower": 0, "size": 8}
DEFINITION = re.compile(r"^\s*(%[\w.]+) = (.*)$")
DX_CALL = re.compile(r"@dx\.op\.([A-Za-z]+)(?:\.[\w]+)?\((.*)\)")
METADATA = re.compile(r"^(!\d+) = (?:distinct )?!\{(.*)\}\s*$")
VALUE = re.compile(r"%[\w.]+")


def split_operands(text):
    """Split a call's operand list at top-level commas."""
    operands, depth, start = [], 0, 0
    for i, char in enumerate(text):
        if char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
        elif char == "," and depth == 0:
            operands.append(text[start:i].strip())
            start = i + 1
    operands.append(text[start:].strip())
    return operands


def last_value(operand):
    return operand.split()[-1]


def integers(text):
    return [int(value) for value in re.findall(r"\bi\d+ (-?\d+)", text)]


def parse_module(text):
    """Return instruction definitions, numbered metadata nodes and named metadata roots."""
    definitions, metadata, named = {}, {}, {}
    for line in text.splitlines():
        if line.startswith("!"):
            match = METADATA.match(line.strip())
            if match:
                metadata[match[1]] = split_operands(match[2])
            elif " = !{" in line:
                name, nodes = line.split(" = ", 1)
                named[name.strip()] = re.findall(r"!\d+", nodes)
            continue
        match = DEFINITION.match(line.split(";", 1)[0])
        if match:
            call = DX_CALL.search(match[2])
            definitions[match[1]] = (call[1], split_operands(call[2])) if call else (None, match[2])
    return definitions, metadata, named


def compiler_ident(metadata, named):
    for node in named.get("!llvm.ident", []):
        match = re.search(r'!"([^"]*)"', ",".join(metadata.get(node, [])))
        if match:
            return match[1]
    return None


def uav_range(metadata, named, range_id):
    """Return space, lower bound and size of UAV range RANGE_ID from !dx.resources."""
    roots = named.get("!dx.resources", [])
    assert len(roots) == 1, "the module has no !dx.resources"
    uavs = metadata[roots[0]][1]
    for entry in [] if uavs == "null" else metadata[uavs]:
        fields = metadata[entry]
        if integers(fields[0])[0] == range_id:
            return {"space": integers(fields[3])[0], "lower": integers(fields[4])[0],
                    "size": integers(fields[5])[0]}
    raise AssertionError(f"UAV range {range_id} is not declared in !dx.resources")


def from_thread_id(definitions, value):
    """True when VALUE is computed, through any chain of instructions, from dx.op.threadId."""
    pending, seen = [value], set()
    while pending:
        name = pending.pop()
        if name in seen or name not in definitions:
            continue
        seen.add(name)
        op, operands = definitions[name]
        if op == "threadId":
            return True
        text = ", ".join(operands) if op else operands
        pending.extend(token for token in VALUE.findall(text) if token in definitions)
    return False


def trace_atomic(text):
    """Follow the only atomic's handle to its creation and return what that creation uses."""
    definitions, metadata, named = parse_module(text)
    atomics = [ops for op, ops in definitions.values() if op in ("atomicBinOp", "atomicCompareExchange")]
    assert len(atomics) == 1, f"expected one dx.op atomic, found {len(atomics)}"
    handle = last_value(atomics[0][1])
    while definitions.get(handle, (None,))[0] == "annotateHandle":
        handle = last_value(definitions[handle][1][1])
    op, operands = definitions.get(handle, (None, None))
    if op == "createHandle":
        resource_class = integers(operands[1])[0]
        binding = uav_range(metadata, named, integers(operands[2])[0]) if resource_class == UAV_CLASS else None
        index, flag = operands[3], operands[4]
    elif op == "createHandleFromBinding":
        lower, upper, space, resource_class = integers(operands[1])
        binding = {"space": space, "lower": lower, "size": upper - lower + 1}
        index, flag = operands[2], operands[3]
    else:
        raise AssertionError(f"atomic handle {handle} is not created by createHandle or createHandleFromBinding")
    index = last_value(index)
    return {
        "compiler": compiler_ident(metadata, named),
        "creation": op,
        "uav": resource_class == UAV_CLASS and binding == ALIASES,
        "dynamic_index": index in definitions and from_thread_id(definitions, index),
        "non_uniform": last_value(flag) == "true",
    }


def disassemble(dxc, args):
    return subprocess.run([str(dxc), *map(str, args)], check=True, capture_output=True, text=True).stdout


def report(name, trace):
    print(f"{name}: compiler={trace['compiler']} creation={trace['creation']} aliases_uav={trace['uav']} "
          f"dynamic_index={trace['dynamic_index']} nonUniformIndex={str(trace['non_uniform']).lower()}")


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    dxc, cso, source, include = map(Path, sys.argv[1:])
    print(subprocess.run([str(dxc), "--version"], capture_output=True, text=True).stdout.strip())

    probe = trace_atomic(disassemble(dxc, ["-dumpbin", cso]))
    report(cso.name, probe)
    assert probe["uav"] and probe["dynamic_index"], "the atomic does not use the probe's dynamic Aliases index"
    assert probe["non_uniform"], "the built probe lost nonUniformIndex on the atomic's handle"

    original = source.read_text(encoding="utf-8")
    assert original.count(INTRINSIC) >= 1, f"{source.name} no longer uses {INTRINSIC[:-1]}"
    with TemporaryDirectory() as tmp:
        copy = Path(tmp) / source.name
        copy.write_text(original.replace(INTRINSIC, "("), encoding="utf-8")
        control = trace_atomic(disassemble(dxc, ["-T", "cs_6_0", "-E", ENTRY, "-I", include, copy]))
    report(f"control without {INTRINSIC[:-1]}", control)
    assert control["uav"] and control["dynamic_index"], "the control does not trace to the dynamic Aliases index"
    assert not control["non_uniform"], "the check did not detect nonUniformIndex=false in the control"
    return 0


if __name__ == "__main__":
    sys.exit(main())
