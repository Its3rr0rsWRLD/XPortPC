"""Control flow (docs/design/control-flow.md, CF-1): basic blocks, structured if / if-else / loop matching, join
variables, and the walk that yields instructions to lower() in program order while emitting the structure."""
import re


# Control flow (docs/design/control-flow.md, CF-1): uniform branches only. A program is split into basic blocks, the
# blocks are matched to if, if-else and single-back-edge loops, and every register a region changes becomes a join
# variable. These helpers are pure functions of state snapshots; lower() owns the state.
LABEL = r"[A-Za-z_.$][\w.$]*"


def word_expr(value):
    """A register value as an unsigned expression, or None when it is provenance (a descriptor word, an
    interpolation value or a lane mask) and not 32 bits of data."""
    if isinstance(value, int):
        return f"{value}u"
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
        return value[1]
    if isinstance(value, str) and value.startswith(("alu", "sample")):
        return f"asuint({value})"
    return None


def is_condition(value):
    return isinstance(value, tuple) and len(value) == 4 and value[0] == "condition"


# CF-2c (docs/design/control-flow.md, CF-2 section 4): the value of a scalar register (SGPR, VCC, M0, a lane mask)
# that a skipped region left different from its entry. The wave may have skipped the region while this lane ran it
# (inactive), so the register holds what another lane decided; reading it is refused (lowering.lower checks the
# operands of every instruction against it).
POISON = ("poison",)
POISON_MESSAGE = "Scalar value depends on another lane (written in a skipped region)"
# A scalar register that the paths of a uniform branch leave holding different kinds of value (a lane mask on one,
# data or a descriptor word on another): it cannot be joined, so it is unreadable after the join (CF-2c; before, the
# join itself was refused, which still happens for a VGPR).
JOIN_POISON = ("poison", "join")
JOIN_POISON_MESSAGE = "Descriptor state differs at a join (the register is read after it)"
# The all-lanes-dead block ACO branches to when no lane is left (CF-2 section 4): such a branch is not taken.
NULL_BLOCK = ["exp null off, off, off, off done vm", "s_endpgm"]


def poisoned_operands(scalar, line):
    """The scalar registers an instruction names that hold POISON."""
    if POISON not in scalar.values() and JOIN_POISON not in scalar.values():
        return []
    names = set(re.findall(r"(?<![\w\[:])s\d+\b", line))
    names.update(name for name, pattern in (("vcc", r"\bvcc"), ("m0", r"\bm0\b")) if re.search(pattern, line))
    for first, last in re.findall(r"s\[(\d+):(\d+)\]", line):
        names.update(f"s{n}" for n in range(int(first), int(last) + 1))
    return sorted(name for name in names if scalar.get(name) in (POISON, JOIN_POISON))


def conjuncts(expression):
    """The operands of the top-level && of a bool expression (the expression itself when it has none)."""
    e = expression.strip()
    while e.startswith("(") and e.endswith(")"):
        depth = 0
        for n, ch in enumerate(e):
            depth += {"(": 1, ")": -1}.get(ch, 0)
            if depth == 0 and n < len(e) - 1:
                break
        else:
            e = e[1:-1].strip()
            continue
        break
    parts, depth, start, n = [], 0, 0, 0
    while n < len(e):
        depth += {"(": 1, ")": -1}.get(e[n], 0)
        if depth == 0 and e.startswith("&&", n):
            parts.append(e[start:n].strip())
            start = n = n + 2
            continue
        n += 1
    parts.append(e[start:].strip())
    if len(parts) > 1 and any("||" in part and not part.startswith("(") for part in parts):
        return [e]
    return parts


def implies(lines, name, implied, depth=0):
    """Whether the bool `name` can be true only when one of `implied` is: it is one of them, false, an alias of such
    a name, or a conjunction (as the HLSL text defines it) with an operand that is."""
    if name in implied or name == "false":
        return True
    if depth > 16 or not re.fullmatch(r"[A-Za-z_]\w*", name):
        return False
    pattern = re.compile(rf"\s*bool {re.escape(name)} = (.*);")
    for line in reversed(lines):
        if m := pattern.fullmatch(line):
            return any(implies(lines, part, implied, depth + 1) for part in conjuncts(m[1]))
    return False


# Functions whose result depends only on their arguments, for the uniformity lattice (CF-2 section 5): the HLSL
# intrinsics the lowering emits and the helper functions that read no texture, memory or other lane.
PURE_INTRINSICS = {
    "asfloat", "asuint", "asint", "float", "uint", "int", "bool", "float2", "float3", "float4", "uint2", "uint3",
    "uint4", "int2", "int3", "int4", "abs", "min", "max", "floor", "ceil", "round", "trunc", "frac", "sqrt", "rsqrt",
    "rcp", "exp2", "log2", "exp", "log", "sin", "cos", "isnan", "isinf", "isfinite", "f16tof32", "f32tof16", "mad",
    "fma", "clamp", "saturate", "sign", "countbits", "firstbithigh", "firstbitlow", "reversebits", "ldexp", "pow",
    "lerp", "step", "dot", "any", "all",
}
IMPURE_TEXT = ("Texture", "Sample", "Load", "Gather", "GetDimensions", "Quad", "Wave", "ddx", "ddy", "title_", "uv",
               "frag_position", "GetAttributeAtVertex")


def pure_functions():
    from .hlsl import PREAMBLE, SALU_HELPERS
    names = set(PURE_INTRINSICS)
    head = PREAMBLE.split("float4 main(", 1)[0]
    for body in [head, *SALU_HELPERS.values()]:
        if body is head or not any(word in body for word in IMPURE_TEXT):
            names.update(re.findall(r"(?m)^\w+\s+(\w+)\(", body))
    return names


ASSIGNMENT = re.compile(r"\s*(?:precise\s+)?(?:(?:float|uint|int|bool)[234]?\s+)?([A-Za-z_]\w*)(?:\.\w+)?\s*=(?!=)\s*(.*);")
IDENTIFIER = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(\s*\()?")


def uniform_names(lines, excluded=()):
    """The HLSL names whose value is the same on every lane of the wave: the greatest set in which every assignment
    to a name reads only constants, params[] words, pure functions and names of the set. A name assigned nowhere
    (uv, a sample, an interpolated attribute) is not uniform. Lowered HLSL has no divergent scope (CF-2c lowers skips
    as predicated straight-line code and branches only on uniform conditions), so an assignment inside an if or a loop
    is uniform when what it reads is."""
    pure = pure_functions()
    assigned = {}
    for line in lines:
        if m := ASSIGNMENT.fullmatch(line):
            assigned.setdefault(m[1], []).append(m[2])
    uniform = set(assigned)
    changed = True
    while changed:
        changed = False
        for name in sorted(uniform):
            if not all(reads_uniform(rhs, uniform, pure, excluded) for rhs in assigned[name]):
                uniform.discard(name)
                changed = True
    return uniform


def reads_uniform(expression, uniform, pure, excluded=()):
    if any(value in expression for value in excluded):
        return False
    for m in IDENTIFIER.finditer(expression):
        word, call = m[1], m[2]
        if call:
            if word not in pure:
                return False
        elif word not in uniform and word not in ("params", "true", "false"):
            return False
    return True


def scope_free(value):
    """A word that names no local variable, so it means the same in every HLSL scope."""
    return isinstance(value, int) or (isinstance(value, tuple) and len(value) == 2 and value[0] == "uint"
                                      and re.fullmatch(r"params\[\d+\]\.[xyzw]|\d+u", value[1]) is not None)


def plan_join(entry, ends, tag, *, loop):
    """Join variables for a region that starts in state `entry` and finishes in each state of `ends`.

    A register that every end leaves as the entry had it is kept. A data register that differs becomes `uint jv_..`
    (vector) or `uint js_..` (scalar), a lane mask `bool jc_..`; the variable starts with the entry value. A
    register defined on only some paths is dropped (after an if, a register defined on every path is kept; in a loop,
    one defined only by the body is local to it). Provenance must be the same on every path, and in a loop the same
    as at entry. Returns (declarations, joined, state) where joined maps (space, register) to its variable and state
    holds the registers after the region."""
    declarations, joined, groups = [], {}, {}
    state = {"scalar": {}, "vector": {}}
    for space in ("scalar", "vector"):
        for reg in sorted(set(entry[space]).union(*(end[space] for end in ends))):
            old = entry[space].get(reg)
            new = [end[space].get(reg) for end in ends]
            if all(value == old for value in new):
                if old is not None:
                    state[space][reg] = old
                continue
            if any(value is None for value in new) or (old is None and loop):
                continue
            if any(reg in end["pending"] or reg in end["sample_dest"] for end in ends):
                raise ValueError("Outstanding load at a join")
            if any(value in (POISON, JOIN_POISON) for value in new):
                # CF-2c: poisoned on some path, so poisoned after the region (and, in a loop, from its first iteration).
                state[space][reg] = POISON if POISON in new else JOIN_POISON
                continue
            if all(is_condition(value) for value in new):
                if len({value[2:] for value in new}) != 1:
                    raise ValueError("Lane mask layout differs at a join")
                groups.setdefault((tuple(value[1] for value in new), new[0][3]), []).append((reg, new[0][2]))
            elif all(word_expr(value) is not None for value in new):
                if not loop and all(value == new[0] for value in new) and scope_free(new[0]):
                    state[space][reg] = new[0]
                    continue
                name = f"j{'v' if space == 'vector' else 's'}_{reg}_{tag}"
                declarations.append(f"    uint {name} = {word_expr(old) or '0u'};")
                joined[space, reg] = ("word", name)
                state[space][reg] = ("uint", name)
            elif not loop and all(value == new[0] for value in new):
                state[space][reg] = new[0]
            elif not loop and space == "scalar":
                state[space][reg] = JOIN_POISON
            else:
                raise ValueError("Descriptor state differs at a join" if not loop else "Descriptor state differs at a loop back edge")
    for number, ((names, width), members) in enumerate(groups.items()):
        name = f"jc_{tag}_{number}"
        before = [entry["scalar"].get(reg) for reg, _ in members]
        same = all(is_condition(v) and v[2:] == (j, width) for v, (_, j) in zip(before, members)) \
            and len({v[1] for v in before}) == 1
        if loop and not same:
            raise ValueError("Lane mask differs at a loop entry")
        initial = before[0][1] if same else "false"
        declarations.append(f"    bool {name} = {initial};")
        for reg, j in members:
            joined["scalar", reg] = ("cond", name, j, width)
            state["scalar"][reg] = ("condition", name, j, width)
    return declarations, joined, state


def sync_lines(live, joined, held):
    """Assignments that copy the registers of the state `live` into their join variables. `held` maps a register to
    the value its variable already holds, for which no assignment is needed."""
    lines, assigned = [], {}
    for (space, reg), info in joined.items():
        value = live[space].get(reg)
        if value is None or value == held.get((space, reg)):
            continue
        if info[0] == "word":
            if word_expr(value) is None:
                raise ValueError("Descriptor state differs at a join")
            lines.append(f"        {info[1]} = {word_expr(value)};")
        else:
            if not is_condition(value) or value[2:] != info[2:]:
                raise ValueError("Lane mask differs at a join")
            if assigned.setdefault(info[1], value[1]) != value[1]:
                raise ValueError("Lane mask differs at a join")
    lines.extend(f"        {name} = {value};" for name, value in assigned.items())
    return lines


def split_blocks(instructions):
    """Basic blocks of a program. A block is {"labels", "ins": [(index, text)], "term"} where term is None (falls
    through), ("br", label, index) or ("cbr", scc value, label, index). A label starts a block and a branch ends one;
    a label after the last instruction is an empty last block."""
    blocks, labels = [], {}
    current = {"labels": [], "ins": [], "term": None}
    for i, line in enumerate(instructions):
        if m := re.fullmatch(rf"({LABEL}):", line):
            if current["ins"]:
                blocks.append(current)
                current = {"labels": [], "ins": [], "term": None}
            if m[1] in labels:
                raise ValueError(f"Label {m[1]} defined twice")
            labels[m[1]] = len(blocks)
            current["labels"].append(m[1])
        elif m := re.fullmatch(rf"s_branch ({LABEL})", line):
            current["term"] = ("br", m[1], i)
            blocks.append(current)
            current = {"labels": [], "ins": [], "term": None}
        elif m := re.fullmatch(rf"s_cbranch_scc([01]) ({LABEL})", line):
            current["term"] = ("cbr", int(m[1]), m[2], i)
            blocks.append(current)
            current = {"labels": [], "ins": [], "term": None}
        elif m := re.fullmatch(rf"s_cbranch_(exec|vcc)(z|nz) ({LABEL})", line):
            # CF-2c: ("exec", nz, label, index) is a skip branch on this lane's EXEC bit, ("vcc", nz, label, index) a
            # branch on VCC, which program() accepts only when VCC holds a compare of uniform operands. nz is 1 when
            # the branch is taken on a nonzero mask, as scc1 is taken on a set SCC.
            current["term"] = (m[1], int(m[2] == "nz"), m[3], i)
            blocks.append(current)
            current = {"labels": [], "ins": [], "term": None}
        else:
            current["ins"].append((i, line))
    if current["ins"] or current["labels"]:
        blocks.append(current)
    return blocks, labels


def find_loops(blocks, labels):
    """Check that every branch target is a label and map each loop header to its latch, the one block that branches
    back to it. Loops must nest."""
    latch_of = {}
    for k, block in enumerate(blocks):
        if block["term"]:
            name = block["term"][-2]
            if name not in labels:
                raise ValueError(f"Branch to unknown label {name}")
            if labels[name] <= k:
                if labels[name] in latch_of:
                    raise ValueError("A loop header has more than one back edge")
                latch_of[labels[name]] = k
    spans = sorted(latch_of.items())
    for n, (h1, x1) in enumerate(spans):
        for h2, x2 in spans[n + 1:]:
            if h2 <= x1 < x2:
                raise ValueError("Loops overlap; the control flow is not structured")
    return latch_of


def program(st, blocks, labels, latch_of):
    """Yield (index, text) for each instruction of the blocks in program order. The walk emits the HLSL structure
    into st.lines around them and snapshots and restores st at branches and loops; lower() lowers each one."""
    def snapshot():
        return {"scalar": dict(st.scalar), "vector": dict(st.vector), "pending": set(st.pending), "scc": st.scc,
                "ex": st.ex, "wqm": st.wqm, "samples": st.samples, "vm_issued": st.vm_issued,
                "sample_dest": dict(st.sample_dest), "exports": st.exports, "exported": st.exported, "ended": st.ended}

    def restore(state):
        st.scalar.clear(), st.vector.clear(), st.pending.clear(), st.sample_dest.clear()
        st.scalar.update(state["scalar"]), st.vector.update(state["vector"])
        st.pending.update(state["pending"]), st.sample_dest.update(state["sample_dest"])
        st.scc, st.ex, st.wqm, st.samples = state["scc"], state["ex"], state["wqm"], state["samples"]
        st.vm_issued, st.exported, st.ended = state["vm_issued"], state["exported"], state["ended"]
        st.exports = state["exports"]

    def forget_scc():
        st.scc = None

    def same_provenance(first, second, where):
        for key in ("ex", "wqm", "pending", "sample_dest", "exports"):
            if first[key] != second[key]:
                raise ValueError(f"Execution or load state differs at {where}")
        if first["sample_dest"] and first["vm_issued"] != second["vm_issued"]:
            raise ValueError(f"Execution or load state differs at {where}")

    def condition(term):
        """Capture the SCC of a branch in a local, so that join assignments cannot change it. The SCC comes from uniform
        scalar data, so every lane, active or not and in whole-quad mode or not, takes the same edge."""
        if term[0] == "exec":
            raise ValueError("A skip branch on EXEC must jump forward over a region")
        if term[0] == "vcc":
            st.lines.append(f"    bool cf{term[-1]} = {uniform_vcc()};")
            return f"cf{term[-1]}"
        if st.scc is None:
            raise ValueError("Branch condition requires a tracked SCC from uniform scalar data")
        st.lines.append(f"    bool cf{term[-1]} = {st.scc};")
        return f"cf{term[-1]}"

    def uniform_vcc():
        """CF-2c (section 5): s_cbranch_vccz/vccnz only on a compare of wave-uniform operands, lowered on the compare
        without the EXEC mask, so that a lane that is inactive here follows the wave. The operands are checked against
        the uniformity lattice once the whole text is known (uniform_claims), and must not have been reassigned since
        the compare. The compare must have run while the wave provably had an active lane (`live`)."""
        value = st.scalar.get("vcc")
        if "vcc" in st.pending or value == POISON or not is_condition(value) or value[2:] != (0, 1) \
                or value[1] not in st.compares:
            raise ValueError("s_cbranch_vccz/vccnz needs VCC from a compare of wave-uniform operands")
        relation, position, ex = st.compares[value[1]]
        if ex not in live and ex not in dead_skips:
            # VCC is the OR of the compare over the lanes active then; it equals the uniform relation only when the
            # wave had an active lane: this one (ex true), or one that kept it from skipping the enclosing region.
            raise ValueError("s_cbranch_vccz/vccnz on a compare made while the wave may have had no active lane")
        for name in {m[1] for m in IDENTIFIER.finditer(relation) if not m[2]}:
            if any(re.match(rf"\s*(?:[\w ]+\s)?{re.escape(name)}(?:\.\w+)?\s*=(?!=)", line) for line in st.lines[position:]):
                raise ValueError("s_cbranch_vccz/vccnz: an operand of the compare changed before the branch")
        uniform_claims.append(relation)
        return f"({relation})"

    def check_exec(before):
        """Narrow-only regions (section 4): inside a skipped region, and after a branch to the all-lanes-dead block,
        every new EXEC bit must imply the bit the lane had where the region began."""
        if st.ex == before:
            return
        for implied in narrow:
            if not implies(st.lines, st.ex, implied):
                raise ValueError("EXEC re-enabled inside a skipped region (a mask saved outside it is restored)")
            implied.add(st.ex)

    def run(instructions):
        for instruction in instructions:
            before = st.ex
            yield instruction
            if narrow:
                check_exec(before)

    def is_null(k):
        return [text for _, text in blocks[k]["ins"]] == NULL_BLOCK and blocks[k]["term"] is None

    def skip_region(first, stop, term):
        """s_cbranch_execz over blocks first..stop-1 in predicate mode (section 4): the branch is dropped and the region
        runs straight-line, its VGPR writes masked by ex, so HLSL flow stays uniform (an implicit-LOD sample in it keeps
        its quad). execnz runs its fall-through region only when no lane is active, so there every write is masked
        off. Scalars the region leaves different are poisoned, unless the lane is provably active (ex true), when the
        wave cannot skip (execz) or always skips (execnz)."""
        before = snapshot()
        if term[1]:
            st.ex = "false"
        implied = {st.ex} if st.ex != "true" else None
        if implied is not None:
            narrow.append(implied)
        live.append(st.ex if not term[1] else "true")  # execz: the wave runs the region only with an active lane
        depth = len(live)
        yield from walk_region(first, stop)
        del live[depth - 1:]
        if implied is not None:
            narrow[:] = [region for region in narrow if region is not implied]
        after = snapshot()
        if after["exported"] or after["ended"]:
            raise ValueError("Color export or program end inside a skipped region")
        if after["wqm"] != before["wqm"]:
            raise ValueError("Whole-quad mode changes inside a skipped region")
        if before["ex"] == "true" and term[1]:
            # The wave always takes the branch: the region never runs.
            restore(dict(after, ex=before["ex"], scalar=before["scalar"], scc=before["scc"], pending=before["pending"],
                         sample_dest=before["sample_dest"], vm_issued=before["vm_issued"]))
            return
        if term[1]:
            st.ex = before["ex"]
        if before["ex"] != "true":
            for reg in set(before["scalar"]) | set(after["scalar"]):
                if before["scalar"].get(reg) != after["scalar"].get(reg):
                    st.scalar[reg] = POISON
            if before["scc"] != after["scc"]:
                st.scc = None
            st.pending.update(before["pending"])
            st.sample_dest.update(before["sample_dest"])
            if after["vm_issued"] != before["vm_issued"]:
                # Whether the region's loads were issued is not known, so neither is the number outstanding: every load
                # still outstanding counts as the newest, and only vmcnt(0) or enough later loads complete it.
                for reg, (_, kind) in list(st.sample_dest.items()):
                    st.sample_dest[reg] = (st.vm_issued, kind)

    def walk_region(first, stop, ignore_last=False, entered=None):
        """Yield the instructions of blocks first..stop-1 in program order, emitting the structure around them. The
        branch that ends block stop-1 is skipped when ignore_last (an arm's jump to its join, or a loop's back edge)."""
        k = first
        while k < stop:
            block = blocks[k]
            forget_scc()
            if k in latch_of and k != entered:
                if latch_of[k] >= stop:
                    raise ValueError("Loop leaves its region: the control flow is irreducible")
                yield from walk_loop(k, latch_of[k])
                k = latch_of[k] + 1
                continue
            if k in null_targets and k > 0 and blocks[k - 1]["term"] is None and blocks[k - 1]["ins"] \
                    and blocks[k - 1]["ins"][-1][1] == "s_endpgm" and is_null(k):
                # The all-lanes-dead block after the program's end, reached only by branches lowered as not taken.
                k += 1
                continue
            yield from run(block["ins"])
            term = block["term"]
            if term is None or (ignore_last and k == stop - 1):
                k += 1
                continue
            target = labels[term[-2]]
            if term[0] == "exec" and not term[1] and target > k and is_null(target):
                # s_cbranch_execz to the all-lanes-dead block: not taken. The wave takes it only when no lane is left;
                # a lane that falls through inactive must stay so to the end (narrow-only from here on).
                null_targets.add(target)
                if st.ex != "true":
                    narrow.append({st.ex})
                    dead_skips.add(st.ex)
                k += 1
                continue
            if target <= k:
                raise ValueError("Unstructured loop: a back edge must close a loop that starts at its target")
            if target > stop:
                raise ValueError("Branch leaves its region: the control flow is multi-exit or irreducible")
            if term[0] == "br":
                if target != k + 1:
                    raise ValueError("Unconditional branch is not the end of an if-else arm or a loop")
                k += 1
                continue
            if term[0] == "exec":
                yield from skip_region(k + 1, target, term)
                k = target
                continue
            if target == k + 1:
                condition(term)
                k += 1
                continue
            join = target
            other = None
            last = blocks[target - 1]["term"]
            if last and last[0] == "br" and target - 1 > k:
                other = labels[last[-2]]
                exit_term = blocks[stop - 1]["term"] if ignore_last else None
                if (other > stop and exit_term and exit_term[0] == "br" and labels[exit_term[-2]] == other
                        and target < stop):
                    # CF-2c: both arms of this if-else jump to the join of the enclosing arm (ACO's else-if chains
                    # on uniform VCC, post_process_color_cycle): the if-else ends that arm, so its join is the end of
                    # the region, and the else arm's jump is the arm's own.
                    other = stop
                elif not target < other <= stop:
                    raise ValueError("If-else arm jumps outside its region: the control flow is irreducible")
                join = other
            cond = condition(term)
            before = snapshot()
            decl_at = len(st.lines) - 1
            # The fall-through arm runs when the branch is not taken: SCC clear for scc1, set for scc0.
            st.lines.append(f"    if ({'!' if term[1] == 1 else ''}{cond}) {{")
            yield from walk_region(k + 1, target, ignore_last=other is not None)
            arms = [(snapshot(), len(st.lines))]
            restore(before)
            if other is not None:
                st.lines.append("    } else {")
                yield from walk_region(target, other, ignore_last=other == stop and exit_term is not None
                                       and exit_term[0] == "br" and labels[exit_term[-2]] > stop)
                arms.append((snapshot(), len(st.lines)))
                restore(before)
            st.lines.append("    }")
            merge_if(before, arms, decl_at, term[-1])
            k = join

    def merge_if(before, arms, decl_at, tag):
        """Continue after an if or if-else: `arms` holds each arm's end state and the line where it ends."""
        ends = [state for state, _ in arms]
        total = before["samples"] + sum(state["samples"] - before["samples"] for state in ends)
        paths = [state for state in ends if not state["ended"]]
        if len(arms) == 1:
            paths.append(before)  # the path that skips the arm
        if not paths:
            restore(dict(before, exported=True, ended=True, samples=total))
            return
        for state in paths[1:]:
            if state["exported"] != paths[0]["exported"]:
                raise ValueError("Color export on only one path")
            same_provenance(paths[0], state, "a join")
        if paths[0]["exported"]:
            # Every path has returned; only s_endpgm may follow, so no register needs to survive.
            registers, declarations, inserts = before, [], []
        else:
            declarations, joined, registers = plan_join(before, paths, tag, loop=False)
            held = {key: before[key[0]].get(key[1]) for key, info in joined.items() if info[0] == "word"}
            inserts = [(position, sync_lines(state, joined, held)) for state, position in arms if not state["ended"]]
        for position, fixes in sorted(inserts, reverse=True):
            st.lines[position:position] = fixes
        st.lines[decl_at:decl_at] = declarations
        restore(dict(paths[0], scalar=dict(registers["scalar"]), vector=dict(registers["vector"]), scc=None,
                     samples=total))

    def walk_loop(header, latch):
        tag = blocks[latch]["term"][-1]
        entry = snapshot()
        mark = len(st.lines)
        ends = []
        yield from loop_body(header, latch, None, {}, ends)
        del st.lines[mark:]
        restore(entry)
        for state in ends:
            same_provenance(entry, state, "a loop back edge")
            if state["exported"] or state["ended"]:
                raise ValueError("Color export or program end inside a loop")
        declarations, joined, joined_state = plan_join(entry, ends, tag, loop=True)
        st.lines.extend(declarations)
        held = {key: joined_state[key[0]][key[1]] for key in joined}
        for key in joined:
            (st.scalar if key[0] == "scalar" else st.vector)[key[1]] = joined_state[key[0]][key[1]]
        poisoned = {reg: value for reg, value in joined_state["scalar"].items() if value in (POISON, JOIN_POISON)}
        st.scalar.update(poisoned)
        starting = snapshot()
        again = []
        yield from loop_body(header, latch, joined, held, again)
        for state in again:
            for space in ("scalar", "vector"):
                for reg, value in starting[space].items():
                    if (space, reg) not in joined and state[space].get(reg) != value:
                        raise ValueError("Loop state is not stable; the program is refused")
        exit_samples = st.samples
        restore(entry)
        for key in joined:
            (st.scalar if key[0] == "scalar" else st.vector)[key[1]] = joined_state[key[0]][key[1]]
        st.scalar.update(poisoned)
        st.samples = exit_samples

    def loop_body(header, latch, joined, held, ends):
        """One lowering of a loop. With joined None this is the dry run that finds which registers the body changes."""
        term = blocks[latch]["term"]
        st.lines.append("    [loop] while (true) {")

        def leave(cond, breaks_when):
            if joined is not None:
                st.lines.extend(sync_lines(snapshot_for_sync(), joined, held))
            st.lines.append(f"        if ({'' if breaks_when else '!'}{cond}) break;")

        def snapshot_for_sync():
            return {"scalar": dict(st.scalar), "vector": dict(st.vector)}

        if term[0] == "br":
            exit_term = blocks[header]["term"]
            if (header == latch or not exit_term or exit_term[0] not in ("cbr", "vcc")
                    or labels[exit_term[2]] != latch + 1):
                raise ValueError("A loop must leave through a conditional branch ending its header or a conditional back edge")
            yield from run(blocks[header]["ins"])
            cond = condition(exit_term)
            ends.append(snapshot())
            leave(cond, exit_term[1] == 1)
            yield from walk_region(header + 1, latch + 1, ignore_last=True)
        else:
            yield from walk_region(header, latch + 1, ignore_last=True, entered=header)
            cond = condition(term)
            leave(cond, term[1] == 0)
        ends.append(snapshot())
        if joined is not None:
            st.lines.extend(sync_lines(snapshot_for_sync(), joined, held))
        st.lines.append("    }")

    narrow = []  # the implied sets of the narrow-only regions the walk is in (check_exec)
    null_targets = set()
    live = ["true"]  # lane bits under which the wave provably has an active lane (uniform_vcc), by region
    dead_skips = set()  # and the bits at skips to the all-lanes-dead block, from there on
    uniform_claims = []  # compares that s_cbranch_vccz/vccnz lowered as uniform
    yield from walk_region(0, len(blocks))
    if uniform_claims:
        uniform = uniform_names(st.lines, st.lane_values)
        pure = pure_functions()
        for relation in uniform_claims:
            if not reads_uniform(relation, uniform, pure, st.lane_values):
                raise ValueError("s_cbranch_vccz/vccnz on a compare of operands that are not wave-uniform")
