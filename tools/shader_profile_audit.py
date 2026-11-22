"""Count local shader records accepted by the fixed desktop profiles. Prints aggregate JSON."""

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import mmap
from pathlib import Path

import compute_store_aot
import depth_mask_aot
import mesh_entry_aot
import pixel_aot
import pixel_cb_read
from resource_inventory import scene_records
import sampled_coverage_aot


STAGES = {0: "PS", 1: "VS", 2: "GS", 5: "CS", 13: "MS"}
SAMPLER = [0x92, 0xC00000, 0x14500000, 0]
GENERAL = [
    (8, 9, SAMPLER, None, None), (8, 9, SAMPLER, 32, None),
    (8, 9, SAMPLER, None, 32), (20, 24, [1, 2, 3, 4], None, 32),
] + [(table, 24, None, cb, None) for table in (8, 9) for cb in (None, 0, 32)]
MESH_GEOMETRY = [1, 0, 0, 2, 0, 0, 0, 32896]
INDEXED_GEOMETRY = [1, 1, 0, 2, 0, 0, 0, 32896, 65536, 2]


def coverage_bindings(slot):
    return dict(interp=16, words=[[13, 12]], selector_byte=12, descriptors=[
        [8, 0x740, "selector", slot], [9, 0, "cb", 0], [9, 32, "cb", 4],
        [14, 0, "texture", 0], [14, 32, "texture", 1], [15, 0x430, "sampler", 0],
    ])


def first_diagnostic(exc):
    reason = str(exc)
    if reason.startswith("Unsupported instruction "):
        return "unsupported " + reason.partition(": ")[2].split()[0]
    return reason


def pixel_profiles(code, llvm, emit):
    decoded = pixel_aot.disassemble(code, llvm, offsets=True)
    lines = [line for _, line in decoded]
    profiles = []
    first_general = None
    for table, interp, sampler, cb, second in GENERAL:
        try:
            source = pixel_aot.lower(lines, table, interp, sampler, cb, second_texture_offset=second)
        except (KeyError, ValueError) as exc:
            if first_general is None:
                first_general = first_diagnostic(exc)
            continue
        emit("general", source)
        profiles.append("general")
        break

    exits = lines.count("s_endpgm")
    if exits == 1 and any(line.startswith("v_interp_") for line in lines) and not any(
        line.startswith("image_") for line in lines
    ):
        for interp, table, cb in itertools.product(range(8, 26), (8, 9), (None, 0, 32)):
            if interp == table:
                continue
            try:
                source = pixel_aot.lower(lines, table, interp, None, cb)
            except (KeyError, ValueError):
                continue
            if "float4 uv : TEXCOORD0" in source:
                emit("attribute", source)
                profiles.append("attribute")
                break

    if exits == 2:
        try:
            emit("depth", depth_mask_aot.lower(decoded, [(8, 0x480), (9, 0)]))
            profiles.append("depth")
        except (KeyError, ValueError):
            pass
    try:
        sources = [sampled_coverage_aot.lower(decoded, coverage_bindings(slot)) for slot in range(2)]
        for slot, source in enumerate(sources):
            emit(f"coverage-{slot}", source)
        profiles.append("coverage")
    except (KeyError, ValueError):
        pass
    return profiles, f"pixel lowering / first general profile: {first_general}"


def compute_profiles(code, width, llvm, emit):
    lines = pixel_aot.disassemble(code, llvm)
    choices = [(4, None), (5, None)] if width == 1 else [(5, 6), (4, 5)]
    strides = [None] if width == 1 else [4, 8, 12, 16]
    for (table, group), offset, stride in itertools.product(choices, (0, 32, 64), strides):
        try:
            source = compute_store_aot.lower(lines, width, table_reg=table, descriptor_offset=offset,
                                             group_reg=group, stride=stride)
            emit("store", source)
            return ["store"]
        except ValueError:
            continue
    return []


def classify(blob, sections, stage, llvm, emit):
    if stage not in (0, 5, 13):
        return [], "no stage profile"
    width = compute_store_aot.group_width(sections.get(b"PSV0", b"")) if stage == 5 else None
    code = pixel_aot.container_code(sections[b"DXIL"], stage=stage, llvm=llvm)
    if stage == 0:
        return pixel_profiles(code, llvm, emit)
    if stage == 5:
        return compute_profiles(code, width, llvm, emit), "store lowering"

    profiles = []
    if len(code) == 832:
        try:
            emit("point-mesh", mesh_entry_aot.translate(blob, MESH_GEOMETRY, llvm))
            profiles.append("point mesh")
        except (ValueError, KeyError, TypeError, IndexError, OverflowError):
            pass
    if len(code) <= 1200:
        try:
            source = mesh_entry_aot.translate(blob, INDEXED_GEOMETRY, llvm, vertex_header=608)
        except (ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
            return profiles, f"indexed mesh: {exc}"
        if "vertexData.Load(" in source:
            emit("indexed-mesh", source)
            profiles.append("indexed mesh")
        return profiles, "no indexed vertex read"
    return profiles, "outside 1200-byte indexed survey"


def cb_diagnostic(program, llvm):
    code = pixel_aot.container_code(program, stage=0, llvm=llvm)
    lines = pixel_aot.disassemble(code, llvm)
    desc = pixel_cb_read.first_descriptor(lines)
    if desc is None:
        return "untraced descriptor", None, None, None, None
    group = f"entry s{desc.table} + {desc.offset:#x}"
    read = pixel_cb_read.first_read(lines, desc)
    if (desc.table, desc.offset) != (9, 0):
        return group, read, None, None, None
    method = "untraced consumer or completion"
    if read is not None:
        offset = read.offset if isinstance(read.offset, str) else hex(read.offset)
        method = f"{read.width} DWORD(s) at {offset}"
    probe = pixel_cb_read.depth_probe(desc, read) if read == pixel_cb_read.Read(4, 16) else None
    try:
        pixel_aot.lower(lines, 9, 24, None, 0)
    except (KeyError, ValueError) as exc:
        stop = first_diagnostic(exc)
    else:
        stop = "complete"
    return group, read, method, stop, probe


def scan(archive, llvm, source_dir=None, *, cb_reads=False):
    cache = {}
    records, accepted = Counter(), Counter()
    profiles, first_stops = defaultdict(Counter), defaultdict(Counter)
    cb_cache = {}
    groups, modes, consumers, after_binding = Counter(), Counter(), Counter(), Counter()
    probe_source = None

    def observe(stage, blob, sections):
        nonlocal probe_source
        name = STAGES.get(stage, str(stage))
        records[name] += 1
        digest = hashlib.sha256(blob).digest()

        def emit(profile, source):
            if source_dir is not None:
                directory = source_dir / profile
                directory.mkdir(exist_ok=True, parents=True)
                (directory / (digest.hex() + ".hlsl")).write_text(source, encoding="utf-8")

        if digest not in cache:
            try:
                cache[digest] = classify(blob, sections, stage, llvm, emit)
            except (ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
                cache[digest] = [], str(exc).split(":")[0]
        hits, reason = cache[digest]
        if hits:
            accepted[name] += 1
            profiles[name].update(hits)
        else:
            first_stops[name][reason] += 1
            if cb_reads and stage == 0 and reason == "pixel lowering / first general profile: Unresolved constant buffer binding":
                if digest not in cb_cache:
                    cb_cache[digest] = cb_diagnostic(sections[b"DXIL"], llvm)
                group, read, method, stop, probe = cb_cache[digest]
                groups[group] += 1
                modes[read.mode() if read else "untraced consumer or completion"] += 1
                if method is not None:
                    consumers[method] += 1
                    after_binding[stop] += 1
                if probe is not None:
                    probe_source = probe

    scene_records(archive, observe=observe)
    result = dict(records=records, hlsl_records=accepted, profiles=profiles,
                  first_stops={stage: counts.most_common() for stage, counts in first_stops.items()})
    if cb_reads:
        result["cb_reads"] = dict(first_descriptor=groups.most_common(), read_modes=modes.most_common(),
                                  s9_zero_reads=consumers.most_common(),
                                  s9_zero_full_shader_stops=after_binding.most_common())
        if probe_source is not None and source_dir is not None:
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "s9-slot0-read-probe.hlsl").write_text(probe_source, encoding="ascii")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--llvm", required=True, help="Path or loader name for the LLVM 15 library")
    parser.add_argument("--source-dir", type=Path, help="Optional local directory for accepted HLSL by profile and container hash")
    parser.add_argument("--cb-reads", action="store_true", help="Trace first-profile unresolved constant buffer reads")
    args = parser.parse_args()
    with args.archive.open("rb") as f:
        if f.seek(0, 2):
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
                result = scan(data, args.llvm, args.source_dir, cb_reads=args.cb_reads)
        else:
            result = scan(b"", args.llvm, args.source_dir, cb_reads=args.cb_reads)
    print(json.dumps(result, indent=2))
