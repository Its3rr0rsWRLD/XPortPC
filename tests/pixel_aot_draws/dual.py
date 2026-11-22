"""Draw family `dual`: pixel_aot_check.py draw --family dual."""
import subprocess

from .common import assembly, lower, must_reject

# "partial" reads texture A's red channel under vmcnt(1) while B is still outstanding (R0Y00/Xbox2Windows#176 by
# descent81): the samples return in order, so only the newest one is in flight.
DUAL_CASES = ("forward", "reverse", "reuse", "partial")


def dual_program(case="forward", *, swap_weights=False):
    program = assembly(False)
    first = next(i for i, line in enumerate(program) if line.startswith("image_sample"))
    sample_a = program[first]
    sample_b = sample_a.replace("v[12:15]", "v[20:23]").replace("s[28:35]", "s[56:63]")
    load_b = "s_load_dwordx8 s[56:63], s[20:21], 0x20"
    if case == "reuse":
        # Finish A before reloading the same descriptor registers for B.
        program[first:first+1] = [sample_a, "s_waitcnt vmcnt(0)",
                                  load_b.replace("56:63", "28:35"), "s_waitcnt lgkmcnt(0)",
                                  sample_b.replace("56:63", "28:35")]
    elif case in ("forward", "reverse", "partial"):
        program[first:first+1] = [sample_a, sample_b] if case != "reverse" else [sample_b, sample_a]
        program.insert(program.index("s_mov_b32 s40, 1"), load_b)
    else:
        raise ValueError(f"Unknown dual-texture case: {case}")
    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    a, b = ("0x3e800000", "0x3f400000") if swap_weights else ("0x3f400000", "0x3e800000")
    ops = []
    for i in range(4):
        ops.extend([f"v_mul_legacy_f32_e32 v{12+i}, {a}, v{12+i}",
                    f"v_fma_f32 v{12+i}, {b}, v{20+i}, v{12+i}"])
    if case == "partial":
        # Scale A's red channel while B is still outstanding.
        wait = program.index("s_waitcnt vmcnt(0)")
        first_mul = ops.pop(0).replace(", v12", ", v24")
        program[wait:wait] = ["s_waitcnt vmcnt(1)", "v_mov_b32_e32 v24, v12", first_mul]
        pos += 3
    program[pos:pos] = ops
    return program


def translate_dual(instructions):
    return lower(instructions, 20, 24, [1, 2, 3, 4], second_texture_offset=32)


def check_dual_draws(directory, compiler, renderer, backend):
    source = directory / "fixture.hlsl"
    shader = directory / "fixture.cso"
    capture = directory / "blend.rgba"
    draw = [renderer, backend, "--dual-pixel", shader, capture]
    for case in DUAL_CASES:
        source.write_text(translate_dual(dual_program(case)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        subprocess.run(draw, check=True)
    wrong = subprocess.run([renderer, backend, "--dual-pixel-swapped", shader, capture], capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Swapped texture bindings escaped detection")
    source.write_text(translate_dual(dual_program(swap_weights=True)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Swapped blend weights escaped detection")


def controls(directory):
    partial = dual_program("partial")
    wait = partial.index("s_waitcnt vmcnt(1)")
    translate_dual(partial)
    # Keep the early read of A but issue B first. Now A is still pending.
    reversed_samples = partial.copy()
    reversed_samples[wait - 2:wait] = reversed(reversed_samples[wait - 2:wait])
    must_reject(translate_dual, reversed_samples)
    # A wait that leaves both samples in flight, or no wait at all, settles nothing.
    for count in (2, 63):
        changed = partial.copy()
        changed[wait] = f"s_waitcnt vmcnt({count})"
        must_reject(translate_dual, changed)
    # B stays protected: no read of its registers, no write over them, and no pack of them.
    for early_use in ("v_mov_b32_e32 v24, v20", "v_mov_b32_e32 v20, v12",
                      "v_mul_legacy_f32_e32 v12, 1.0, v20",
                      "v_cvt_pkrtz_f16_f32_e32 v24, v12, v20"):
        changed = partial.copy()
        changed.insert(wait + 1, early_use)
        must_reject(translate_dual, changed)
    # Each of B's four destinations remains protected from a constant write.
    for reg in range(20, 24):
        changed = partial.copy()
        changed.insert(wait + 1, f"v_mov_b32_e32 v{reg}, 0")
        must_reject(translate_dual, changed)
    # Packing A is legal here even though B is outstanding.
    translate_dual(partial[:wait + 1] + ["v_cvt_pkrtz_f16_f32_e32 v24, v12, v13"] + partial[wait + 1:])
    # A larger legal wait after draining does not invalidate completed samples, and the six-bit field ends at 63.
    end_wait = partial.index("s_waitcnt vmcnt(0)")
    drained = partial[:end_wait + 1] + ["s_waitcnt vmcnt(63)"] + partial[end_wait + 1:]
    translate_dual(drained)
    must_reject(translate_dual, [op.replace("vmcnt(63)", "vmcnt(64)") for op in drained])
    # Samples and buffer loads are not known to return in order, so a partial wait over a mix settles neither, and
    # only vmcnt(0) does. Of two samples a partial wait settles the older one. (State-level: an assembled mixed program
    # would need a buffer descriptor setup that load.py already exercises.)
    from pixel_aot_ops.lowering import Lowering
    def state(*kinds):
        st = Lowering({}, {}, [], {}, [], None, {})
        for n, kind in enumerate(kinds):
            st.vm_issue([f"v{n}"], kind)
        return st
    mixed = state("sample", "mubuf")
    mixed.vm_wait(1)
    assert set(mixed.sample_dest) == {"v0", "v1"}, mixed.sample_dest
    mixed.vm_wait(0)
    assert not mixed.sample_dest
    same = state("sample", "sample")
    same.vm_wait(1)
    assert set(same.sample_dest) == {"v1"}, same.sample_dest
    same.vm_wait(2)
    assert set(same.sample_dest) == {"v1"}
    must_reject(same.vm_wait, 64)


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((dual_program(case), translate_dual) for case in DUAL_CASES),
        (dual_program(swap_weights=True), translate_dual),
    ]


draw = check_dual_draws
