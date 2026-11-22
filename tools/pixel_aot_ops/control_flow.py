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
        return {"scalar": dict(st.scalar), "vector": dict(st.vector), "pending": set(st.pending), "scc": st.scc, "mask": st.mask,
                "samples": st.samples, "sample_pending": st.sample_pending, "sample_dest": set(st.sample_dest),
                "exported": st.exported, "ended": st.ended}

    def restore(state):
        st.scalar.clear(), st.vector.clear(), st.pending.clear(), st.sample_dest.clear()
        st.scalar.update(state["scalar"]), st.vector.update(state["vector"])
        st.pending.update(state["pending"]), st.sample_dest.update(state["sample_dest"])
        st.scc, st.mask, st.samples = state["scc"], state["mask"], state["samples"]
        st.sample_pending, st.exported, st.ended = state["sample_pending"], state["exported"], state["ended"]

    def forget_scc():
        st.scc = None

    def same_provenance(first, second, where):
        for key in ("mask", "sample_pending", "pending", "sample_dest"):
            if first[key] != second[key]:
                raise ValueError(f"Execution or load state differs at {where}")

    def condition(term):
        """Capture the SCC of a branch in a local, so that join assignments cannot change it."""
        if st.mask != "entry":
            raise ValueError("Branches are not supported in quad execution mode")
        if st.scc is None:
            raise ValueError("Branch condition requires a tracked SCC from uniform scalar data")
        st.lines.append(f"    bool cf{term[-1]} = {st.scc};")
        return f"cf{term[-1]}"

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
            yield from block["ins"]
            term = block["term"]
            if term is None or (ignore_last and k == stop - 1):
                k += 1
                continue
            target = labels[term[-2]]
            if target <= k:
                raise ValueError("Unstructured loop: a back edge must close a loop that starts at its target")
            if target > stop:
                raise ValueError("Branch leaves its region: the control flow is multi-exit or irreducible")
            if st.mask != "entry":
                raise ValueError("Branches are not supported in quad execution mode")
            if term[0] == "br":
                if target != k + 1:
                    raise ValueError("Unconditional branch is not the end of an if-else arm or a loop")
                k += 1
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
                if not target < other <= stop:
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
                yield from walk_region(target, other)
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
            if (header == latch or not exit_term or exit_term[0] != "cbr"
                    or labels[exit_term[2]] != latch + 1):
                raise ValueError("A loop must leave through a conditional branch ending its header or a conditional back edge")
            yield from blocks[header]["ins"]
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

    yield from walk_region(0, len(blocks))
