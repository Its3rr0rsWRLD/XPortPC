"""Specialize a two-table, depth-only gfx1013 PS for an explicit Windows binding."""

import argparse
import re
from pathlib import Path

from pixel_aot import container_code, disassemble
from resource_inventory import parts


def lower(decoded, tables):
    if (
        len(tables) != 2
        or len({reg for reg, _ in tables}) != 2
        or any(
            not 0 <= reg <= 105 or offset < 0 or offset % 4 for reg, offset in tables
        )
    ):
        raise ValueError(
            "Expected two distinct table registers and aligned descriptor offsets"
        )
    scalar = {reg: ("table", n) for n, (reg, _) in enumerate(tables)}
    vector = {2: "pos.x", 3: "pos.y", 4: "pos.z"}
    pending = set()
    used = set()
    lines = [
        "cbuffer First : register(b0) { uint4 first[128]; };",
        "cbuffer Second : register(b1) { uint4 second[128]; };",
        "float main(float4 pos : SV_Position) : SV_Depth {",
    ]

    def word(token):
        if token.startswith("s"):
            n = int(token[1:])
            val = scalar.get(n)
            if n in pending or not isinstance(val, str):
                raise ValueError("Unresolved scalar word")
            return val
        return f"{int(token, 0) & 0xFFFFFFFF}u"

    def fp(token):
        if re.fullmatch(r"v\d+", token):
            return vector[int(token[1:])]
        if re.fullmatch(r"-?\d+\.\d+", token):
            return token + "f"
        return f"asfloat({word(token)})"

    def sgprs(start, stop):
        if start % 2 or stop > 105 or stop < start:
            raise ValueError("Invalid scalar register span")
        return list(range(start, stop + 1))

    index = 0
    for index, (_, line) in enumerate(decoded):
        if line.startswith("v_cmpx_"):
            break
        if re.fullmatch(r"s_(?:inst_prefetch|nop) (?:0x[0-9a-f]+|\d+)", line):
            continue
        if line == "s_waitcnt lgkmcnt(0)":
            pending.clear()
            continue
        if m := re.fullmatch(r"s_mov_b64 s\[(\d+):(\d+)\], exec", line):
            regs = sgprs(*map(int, m.groups()))
            if len(regs) != 2 or pending.intersection(regs):
                raise ValueError("Unverified EXEC save")
            for part, r in enumerate(regs):
                scalar[r] = ("entry", part)
        elif m := re.fullmatch(r"s_mov_b32 s(\d+), (0|s\d+)", line):
            dest, src = int(m[1]), m[2]
            if dest in pending or (src != "0" and int(src[1:]) in pending):
                raise ValueError("Scalar move before wait")
            scalar[dest] = 0 if src == "0" else scalar[int(src[1:])]
        elif m := re.fullmatch(
            r"s_load_dwordx4 s\[(\d+):(\d+)\], s\[(\d+):(\d+)\], (null|0x[0-9a-f]+)",
            line,
        ):
            dest = sgprs(int(m[1]), int(m[2]))
            base = sgprs(int(m[3]), int(m[4]))
            offset = 0 if m[5] == "null" else int(m[5], 0)
            if (
                len(dest) != 4
                or dest[0] % 4
                or len(base) != 2
                or pending.intersection(dest + base)
            ):
                raise ValueError("Unresolved descriptor load")
            ptr = scalar.get(base[0])
            if (
                not isinstance(ptr, tuple)
                or ptr[0] != "table"
                or scalar.get(base[1]) != 0
                or offset != tables[ptr[1]][1]
            ):
                raise ValueError("Unbound descriptor address")
            for part, reg in enumerate(dest):
                scalar[reg] = ("cb", ptr[1], part)
            pending.update(dest)
        elif m := re.fullmatch(
            r"s_buffer_load_dword s(\d+), s\[(\d+):(\d+)\], (null|0x[0-9a-f]+)", line
        ):
            dest, lo, hi = map(int, m.groups()[:3])
            source = sgprs(lo, hi)
            desc = scalar.get(lo)
            offset = 0 if m[4] == "null" else int(m[4], 0)
            if (
                not isinstance(desc, tuple)
                or desc[0] != "cb"
                or len(source) != 4
                or pending.intersection([dest, *source])
                or offset % 4
                or offset >= 2048
                or [scalar.get(r) for r in source]
                != [("cb", desc[1], j) for j in range(4)]
            ):
                raise ValueError("Unbound or pending constant read")
            used.add(desc[1])
            name = ("first", "second")[desc[1]]
            scalar[dest] = f"{name}[{offset // 16}].{'xyzw'[offset // 4 % 4]}"
            pending.add(dest)
        elif m := re.fullmatch(r"s_(add_i32|and_b32) s(\d+), (s\d+), (\d+)", line):
            if int(m[2]) in pending:
                raise ValueError("Pending scalar destination")
            op = "+" if m[1] == "add_i32" else "&"
            expr = f"({word(m[3])} {op} {word(m[4])})"
            scalar[int(m[2])] = expr
        else:
            op, _, arglist = line.partition(" ")
            args = arglist.split(", ")
            if not re.fullmatch(r"v\d+", args[0]):
                raise ValueError(f"Unsupported depth instruction: {op}")
            dest = int(args[0][1:])
            if op == "v_cvt_f32_ubyte0_e32" and len(args) == 2:
                expr = f"float({word(args[1])} & 255u)"
            elif op == "v_mul_legacy_f32_e32" and len(args) == 3:
                x, y = map(fp, args[1:])
                expr = f"(({x} == 0 || {y} == 0) ? 0.0f : {x} * {y})"
            elif op == "v_fmac_f32_e32" and len(args) == 3:
                expr = f"mad({fp(args[1])}, {fp(args[2])}, {vector[dest]})"
            elif op == "v_fract_f32_e32" and len(args) == 2:
                expr = f"min(frac({fp(args[1])}), asfloat(0x3f7fffffu))"
            else:
                raise ValueError(f"Unsupported depth instruction: {op}")
            vector[dest] = f"value{index}"
            lines.append(f"    precise float value{index} = {expr};")
    tail = decoded[index:]
    if len(tail) != 9 or used != {0, 1} or pending:
        raise ValueError("Expected two completed buffer reads and depth/discard exits")
    compare, invert, branch, restore, depth, end, empty, null, last = (
        s for _, s in tail
    )
    cmp = re.fullmatch(r"v_cmpx_lt_f32_e32 (s\d+), (v\d+)", compare)
    inv = re.fullmatch(r"s_andn2_b64 (s\[(\d+):(\d+)\]), \1, exec", invert)
    take = re.fullmatch(r"s_cbranch_scc0 (-?\d+)", branch)
    mask = re.fullmatch(r"s_and_b64 exec, (s\[(\d+):(\d+)\]), (s\[\d+:\d+\])", restore)
    exp = re.fullmatch(r"exp mrtz,? (v\d+), off, off, off done vm", depth)
    if not (
        cmp
        and inv
        and take
        and mask
        and exp
        and mask[4] == inv[1]
        and mask[1] != inv[1]
        and tail[2][0] + 4 + 4 * int(take[1]) == tail[6][0]
        and empty == f"s_mov_b64 exec, {inv[1]}"
        and end == last == "s_endpgm"
        and re.fullmatch(r"exp null,? off, off, off, off done vm", null)
    ):
        raise ValueError("Unverified lane mask or branch target")
    for first, final in ((inv[2], inv[3]), (mask[2], mask[3])):
        if [scalar.get(r) for r in sgprs(int(first), int(final))] != [
            ("entry", 0),
            ("entry", 1),
        ]:
            raise ValueError("Expected the original entry mask")
    lines += [
        f"    if ({fp(cmp[1])} < {fp(cmp[2])}) discard;",
        f"    return {fp(exp[1])};",
        "}",
    ]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("container", type=Path)
    p.add_argument("--llvm", required=True)
    p.add_argument(
        "--table",
        action="append",
        nargs=2,
        type=lambda t: int(t, 0),
        required=True,
        metavar=("ENTRY_SGPR", "BYTE_OFFSET"),
        help="b0 then b1",
    )
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if (
        a.output.suffix.lower() != ".hlsl"
        or a.output.resolve() == a.container.resolve()
    ):
        p.error("Choose an HLSL destination distinct from the input")
    code = container_code(
        parts(a.container.read_bytes())[b"DXIL"], stage=0, llvm=a.llvm
    )
    source = lower(disassemble(code, a.llvm, offsets=True), a.table)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(source, encoding="ascii")


if __name__ == "__main__":
    main()
