"""Translate single-store gfx1013 compute programs under an explicit raw-UAV binding."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from pixel_aot import container_code, disassemble
from resource_inventory import parts


def group_width(psv):
    size = struct.unpack_from("<I", psv)[0] if len(psv) >= 4 else 0
    if not 48 <= size <= len(psv) - 4 or psv[28] != 5:
        raise ValueError("Expected compute PSV runtime info with thread dimensions")
    x, y, z = struct.unpack_from("<3I", psv, 40)
    if x not in (1, 32, 64) or (y, z) != (1, 1):
        raise ValueError("Unsupported thread group")
    return x


def lower(instructions, width, *, table_reg, descriptor_offset, group_reg=None, stride=None):
    """v0 is local X, group_reg is group X, and the selected descriptor names u0."""
    if (width not in (1, 32, 64) or not 0 <= table_reg <= 105
            or not 0 <= descriptor_offset < 1 << 20 or descriptor_offset % 4):
        raise ValueError("Invalid table or thread group binding")
    if group_reg is not None and (not 0 <= group_reg <= 105 or group_reg == table_reg):
        raise ValueError("Invalid group register")
    if stride is not None and (group_reg is None or not 4 <= stride <= 0x3fff or stride % 4):
        raise ValueError("Indexed stores require a group register and aligned stride")
    scalar = {table_reg: "table"}
    if group_reg is not None:
        scalar[group_reg] = "group"
    vector = {0: "local"}
    pending = set()
    store = None
    if not instructions or instructions[-1] != "s_endpgm":
        raise ValueError("Missing final program exit")

    for line in instructions[:-1]:
        if re.fullmatch(r"s_inst_prefetch (?:0x[0-9a-f]+|\d+)|s_nop \d+", line):
            continue
        if line == "s_waitcnt lgkmcnt(0)":
            pending.clear()
        elif m := re.fullmatch(r"s_mov_b32 s(\d+), (s\d+|0)", line):
            dst, src = int(m[1]), m[2]
            if dst in pending or dst > 105:
                raise ValueError("Invalid scalar destination or pending load")
            if src == "0":
                scalar[dst] = 0
            else:
                n = int(src[1:])
                if n in pending or n not in scalar:
                    raise ValueError("Unknown or pending scalar source")
                scalar[dst] = scalar[n]
        elif m := re.fullmatch(r"s_load_dwordx4 s\[(\d+):(\d+)\], s\[(\d+):(\d+)\], (null|0x[0-9a-f]+)", line):
            dest, last, base, high = map(int, m.groups()[:4])
            offset = 0 if m[5] == "null" else int(m[5], 16)
            regs = range(dest, last + 1)
            if (dest % 4 or last != dest + 3 or last > 105 or base % 2 or high != base + 1
                    or high > 105 or pending.intersection((*regs, base, high))
                    or (scalar.get(base), scalar.get(high)) != ("table", 0) or offset != descriptor_offset):
                raise ValueError("Unresolved UAV descriptor load")
            for component, reg in enumerate(regs):
                scalar[reg] = ("uav", component)
            pending.update(regs)
        elif m := re.fullmatch(r"v_mov_b32_e32 v(\d+), (-?\d+|0x[0-9a-f]+)", line):
            value = int(m[2], 0)
            if int(m[1]) > 255 or not -(1 << 31) <= value <= 0xffffffff:
                raise ValueError("Invalid literal move")
            vector[int(m[1])] = value & 0xffffffff
        elif m := re.fullmatch(r"v_lshl_add_u32 v(\d+), s(\d+), (\d+), v(\d+)", line):
            dst, group, shift, local = map(int, m.groups())
            if (dst > 255 or group in pending or scalar.get(group) != "group"
                    or shift != width.bit_length() - 1 or vector.get(local) != "local"):
                raise ValueError("Unverified dispatch index")
            vector[dst] = "index"
        elif m := re.fullmatch(r"buffer_store_dword(?:x([234]))? (v\d+|v\[\d+:\d+\]), (off|v\d+), "
                               r"s\[(\d+):(\d+)\], 0( idxen)?(?: offset:(\d+))?", line):
            count = int(m[1] or 1)
            first, *last = map(int, re.findall(r"\d+", m[2]))
            base, high = int(m[4]), int(m[5])
            offset = int(m[7] or 0)
            if (store or last != ([] if count == 1 else [first + count - 1])
                    or high != base + 3 or base % 4 or offset % 4 or offset > 4095
                    or pending.intersection(range(base, high + 1))
                    or any(scalar.get(base + i) != ("uav", i) for i in range(4))):
                raise ValueError("Unverified raw UAV store")
            address = f"{offset}u"
            if m[3] == "off" and not m[6] and width == 1 and stride is None:
                pass
            elif (stride is not None and m[6] and m[3] != "off"
                    and vector.get(int(m[3][1:])) == "index" and offset + 4 * count <= stride):
                address = f"tid.x * {stride}u + {offset}u"
            else:
                raise ValueError("Unsupported store address")
            values = [vector.get(reg) for reg in range(first, first + count)]
            if not all(isinstance(value, int) for value in values):
                raise ValueError("Store data is not a known word")
            words = ", ".join(f"0x{value:08x}u" for value in values)
            arg = words if count == 1 else f"uint{count}({words})"
            store = f"    outputData.Store{count if count > 1 else ''}({address}, {arg});"
        else:
            raise ValueError(f"Unsupported compute instruction: {line}")
    if store is None:
        raise ValueError("Expected one observable store")
    return (f"RWByteAddressBuffer outputData : register(u0);\n[numthreads({width},1,1)]\n"
            f"void main(uint3 tid : SV_DispatchThreadID) {{\n{store}\n}}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container", type=Path, help="Local extracted DXBC container")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--llvm", required=True)
    parser.add_argument("--table-reg", type=int, required=True)
    parser.add_argument("--descriptor-offset", type=lambda n: int(n, 0), required=True)
    parser.add_argument("--group-reg", type=int)
    parser.add_argument("--stride", type=int, help="Indexed raw UAV byte stride")
    args = parser.parse_args()
    if args.output.suffix.lower() != ".hlsl" or args.output.resolve() == args.container.resolve():
        parser.error("Choose an HLSL destination distinct from the input")
    blob = args.container.read_bytes()
    chunks = parts(blob)
    width = group_width(chunks.get(b"PSV0", b""))
    code = container_code(chunks.get(b"DXIL", b""), stage=5)
    source = lower(disassemble(code, args.llvm), width, table_reg=args.table_reg,
                   descriptor_offset=args.descriptor_offset, group_reg=args.group_reg, stride=args.stride)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source, encoding="ascii")
    print(json.dumps({"container_sha256": hashlib.sha256(blob).hexdigest(),
                      "native_sha256": hashlib.sha256(code).hexdigest(), "numthreads": [width, 1, 1]}))


if __name__ == "__main__":
    main()
