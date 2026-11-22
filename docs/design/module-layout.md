# pixel_aot: module layout

The gfx1013 pixel translator and its checks are split by instruction family, so that a card adding a form touches its
family's files and nothing shared. `tools/pixel_aot.py` and `tests/pixel_aot_check.py` stay the entry points, with the
same command lines, outputs and CTest names as before.

## Translator: `tools/pixel_aot_ops/`

| File | Holds |
|---|---|
| `lowering.py` | `lower()`: input checks, the state it threads through the forms (`Lowering`, passed as `st`), the final text |
| `dispatch.py` | `@form(pattern, when=...)`, the registry, and the dispatch of one instruction to its form |
| `registers.py` | the register model and operand readers: `("uint", expr)` words, `vector_u32`, `word_of`, `tracked_word`, `RAW_WORD_PREFIXES`, `fp_operand`, the binary16 readers |
| `control_flow.py` | CF-1 ([control-flow.md](control-flow.md)): blocks, `plan_join`, `sync_lines`, and `program()`, the structured walk |
| `quad.py` | quad lanes: the quad-local DPP16 (`quad_perm`) and DPP8 controls, and `quad_read`, the HLSL quad reads of a uint word |
| `bindings.py` | `PixelBindings`, the binding description of `lower(bindings=...)` ([pixel-bindings.md](pixel-bindings.md)), and the descriptor-key helpers the compute stage shares |
| `hlsl.py` | `PREAMBLE`, title-memory helpers, `SALU_HELPERS` (helper functions emitted by name from `st.helpers`) |
| `forms/<family>.py` | the forms of one family and the tables only they use |

Families today: `sopp`, `sop1`, `sop2`, `sopc`, `exec_mask`, `smem`, `valu_f32`, `valu_int`, `valu_f16`, `valu_f64`, `vopc`,
`sdwa`, `dpp`, `vop3p`, `vintrp`, `mimg`, `mubuf`, `mtbuf`, `flat`, `stores`, `atomics`, `image_writes`, `exp`. A table another module needs is imported from its family
(`sdwa` uses `ALU` from `valu_f32` and `COMPARE` from `vopc`). `tools/pixel_aot.py` re-exports the names it always
had (`lower`, `ALU`, `TITLE_LOOKUP`, ...); new code imports from the package.

### Adding a form

Put it in the module of its family, or in a new `forms/<family>.py`; every module in `forms/` is imported in name order
and needs no registration line. A VALU form writes `st.vector` and needs no execution-mask check: while the lane may be
inactive (`st.ex != "true"`), `lower()` turns each VGPR it wrote into `ex ? new : old`. A form that cannot be masked
(a lane-mask write, a load, an export) refuses `st.ex != "true"` (control-flow.md, CF-2a).
A form is a function of the state, the instruction index and the match:

```python
from ..dispatch import form
from ..registers import vector_u32


@form(r"v_example_b32(?:_e32|_e64)? (v\d+), ([^,\s]+)")
def example(st, i, m):
    dst, src = m.groups()
    st.lines.append(f"    uint valu{i} = {vector_u32(src, st.scalar, st.vector, st.pending, st.sample_pending)};")
    st.vector[dst] = ("uint", f"valu{i}")
```

The pattern must match the whole instruction text. Patterns of different families must never match the same text:
the checks' `lower()` wrapper (`tests/pixel_aot_draws/common.py`) asserts that every instruction of every accepted
program has at most one claiming family (`dispatch.claimants`), so the order of the modules never decides a
lowering. Within one module, forms are tried in the order they are defined, and `when=` lets a form pass on a
match (`s_load_dwordx8` of a texture binding before the general scalar load). A helper function the HLSL needs
goes in `hlsl.SALU_HELPERS` (or is added to it by the family module) and is named in `st.helpers`.

## Checks: `tests/pixel_aot_draws/`

Each draw family is the module of that name (`class_.py` for `class`): it defines
`draw(directory, compiler, renderer, backend)` and usually also

- `controls(directory)`: checks that need neither DXC nor a GPU, run by `pixel_aot_check.py controls`
  (the `pixel_aot_controls` test);
- `binary_fixtures()`: `(program, translator)` pairs that `pixel_aot_check.py binary` assembles with llvm-mc,
  disassembles and lowers again.
- `binary_checks(directory, assembler, objcopy, library)`: binary-mode checks that need more than that round trip
  (`exports.py` patches the EN bits of an assembled export).

A module without `draw` contributes only controls or fixtures (`hints.py`, `container.py`). `common.py` holds what
several families share: the recording `lower()` (which also feeds the form-coverage record), `translate`,
`with_constants`, `assembly`, `must_reject` and the numeric references. Modules are found by listing the directory;
`LEGACY_ORDER` in `__init__.py` only keeps the historical order of the existing families, and a new family needs no
entry there (it sorts after them by name).

A new family is one new file. CMake globs the directory, so the next build re-runs configure and adds
`pixel_aot_<family>_warp` and `pixel_aot_<family>_hardware`.

## Running one family

```bash
python -B tests/pixel_aot_check.py --list-families
python -B tests/pixel_aot_check.py draw <dxc> <offscreen_check> warp --family f16
python -B tests/pixel_aot_check.py controls
ctest --preset dev --no-tests=error -R '^pixel_aot_f16_warp$' -V
```

`--family` may be repeated; `draw` without it runs the controls and then every family.
