"""Cross-lane reads (docs/design/compute-stage.md, C-7): v_readfirstlane_b32 of a wave-uniform value, compute stage only.

Semantics (AMD RDNA 2 ISA guide, VOP1): D (an SGPR) = S0 of the lowest-numbered lane whose EXEC bit is set, or of
lane 0 when EXEC is zero. The translation runs one HLSL thread per console lane and has no console wave, so it never
reads another thread; it lowers the instruction only where the lane read does not matter:

- A workgroup of one thread is one wave whose only lane is lane 0: the first active lane, and lane 0 when EXEC is
  zero, is this thread, so D = S0 of this thread, under any EXEC.
- Otherwise D is S0's value on the active lanes, which must be the same on every lane of the workgroup. That value is
  S0 with each masked write (lowering.masked_writes, `v = ex ? new : old`) whose lane bit the current bit implies
  replaced by its new word (an active lane took the new word), and the definitions between them and S0 emitted again
  from the replaced words (active_value), so that an inactive thread computes the same D. The result is assigned to `rfl<i>` and claimed uniform;
  tools/compute_aot.py checks the claim against the uniformity lattice (control_flow.uniform_names, with group_id a
  root) once the whole text is known, and refuses the program when it fails. The instruction must run where the wave
  provably has an active lane (control_flow's `live` bits: a lane bit implied active, or the region of an execz skip),
  since with EXEC zero the console reads lane 0's old value; an SGPR written inside a skipped region is poisoned after
  it as any other (control_flow.skip_region).

Inactive lanes therefore hold the same D as active ones, as on the console. v_readlane_b32, v_writelane_b32 and every
other cross-lane form stay refused.
"""
import re

from ..control_flow import alias, implies
from ..dispatch import form
from ..registers import sgpr_name, vector_u32


DECLARATION = re.compile(r"(\s*)((?:precise\s+)?(?:uint|int|float|bool)[234]?\s+)([A-Za-z_]\w*) = (.*);")
NAME = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(?!\w)")


def active_value(st, i, word):
    """The word as an active lane holds it, computable by every thread: each masked-write name whose lane bit the
    current EXEC bit implies is replaced by its new word, and each single-assignment name whose definition reaches
    such a name is defined again under the name `<name>_r<i>` from the replaced operands (an inactive thread's own
    copy would read its old words). Names assigned more than once (loop joins) are left as they are."""
    definitions, assigned = {}, {}
    for text in st.lines:
        if m := DECLARATION.fullmatch(text):
            definitions[m[3]] = m
        for m in re.finditer(r"(?<![\w.])([A-Za-z_]\w*)(?:\.\w+)?\s*=(?!=)", text):
            assigned[m[1]] = assigned.get(m[1], 0) + 1
    emitted, done = [], {}

    def rewrite(expression, depth):
        if depth > 256:
            raise ValueError("v_readfirstlane_b32: the value's definitions nest too deeply")
        return NAME.sub(lambda m: replace(m[1], depth), expression)

    def replace(name, depth):
        if name in done:
            return done[name]
        out = name
        bit, new = st.masked.get(name, (None, None))
        if bit is not None and implies(st.lines, st.ex, {bit}):
            out = f"({rewrite(new, depth + 1)})"
        elif name in definitions and assigned.get(name) == 1:
            m = definitions[name]
            body = rewrite(m[4], depth + 1)
            if body != m[4]:
                out = f"{name}_r{i}"
                emitted.append(f"    {m[2]}{out} = {body};")
        done[name] = out
        return out

    value = rewrite(word, 0)
    st.lines.extend(emitted)
    return value


def wave_live(st):
    """Whether the wave provably has an active lane here (control_flow.program's `live` bits)."""
    live = getattr(st, "live", ["true"])
    return st.ex == "true" or st.ex in live or alias(st.lines, st.ex) in {alias(st.lines, b) for b in live}


@form(r"v_readfirstlane_b32(?:_e32)? (s\d+), ([^,\s]+)")
def readfirstlane(st, i, m):
    dst, src = m.groups()
    if st.stage != "compute":
        raise ValueError("v_readfirstlane_b32 is lowered in the compute stage only (C-7)")
    sgpr_name(dst)
    if dst in st.pending:
        raise ValueError("Write overlaps an outstanding scalar load")
    word = vector_u32(src, st.scalar, st.vector, st.pending, st.sample_pending)
    if getattr(st, "workgroup_threads", None) != 1:
        if not wave_live(st):
            raise ValueError("v_readfirstlane_b32 while the wave may have no active lane (it reads lane 0)")
        word = active_value(st, i, word)
        st.uniform_claims.append(f"rfl{i}")
    st.lines.append(f"    uint rfl{i} = {word};")
    st.scalar[dst] = ("uint", f"rfl{i}")
