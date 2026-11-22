# Control flow in pixel_aot: design

Status: CF-1 implemented; CF-2 and CF-3 proposed. Applies to tools/pixel_aot.py `lower()`.

## Where we are
`lower()` is one forward pass over straight-line code. It tracks each register symbolically (`vector`/`scalar` dicts holding HLSL names, `("uint", expr)` words, descriptor provenance such as `texture_ptr` or `(name, j)`), and the execution mask is only `entry` or `quad`. Every VALU branch refuses anything but `mask == "entry"`. There is no branch, label or loop support.

## Model: one HLSL thread = one console lane
A pixel shader invocation on desktop is one lane of the console wave. Wave-wide state is reduced to *this lane's view*:
- **EXEC** becomes a per-thread `bool exec_on` (this lane's bit). VCC and SGPR lane masks written by VALU compares are already per-lane `("condition", ...)` values. SALU bitwise ops on lane masks (`s_and/or/xor/andn2/orn2_b32/b64`, `*_saveexec_*`, `*_wrexec_*`) operate on this lane's bit, which is exact for bitwise algebra.
- **Wave-uniform questions** about a mask (`s_cbranch_execz/execnz`, `s_cbranch_vccz/vccnz`, `s_bcnt1` / `s_ff1` / `s_cmp_*` on a mask) cannot be answered per lane exactly, because desktop waves are not console waves. Rule:
  - `s_cbranch_execz L` / `s_cbranch_execnz L` that skip or repeat a region are **lowered as if the lane decides for itself** ("this lane inactive" for execz, "this lane active" for execnz). This is exact for the lane's own results whenever the skipped or repeated region only contains masked vector work and scalar work that is either dead afterwards or recomputed identically; it is the shape LLVM's structurizer emits (SI_IF / SI_ELSE / SI_END_CF / SI_LOOP). The translator must *verify* that shape (see "Checks") and refuse otherwise.
  - Population counts and lane searches on masks (`s_bcnt1`, `s_ff1`, readfirstlane) are refused in divergent regions until a later card models them with wave intrinsics.
- **Uniform branches** (`s_cbranch_scc0/1` on an SCC computed only from uniform scalar data, `s_branch`) are ordinary per-thread branches: every lane takes the same edge.

## Representation: basic blocks + join variables (keeps every existing lowering branch)
1. Split the instruction list into basic blocks at labels and after branches. Labels come from the disassembly (`_L1:` or `s_branch label` forms; support the spelling our llvm-mc 15 fixtures use).
2. Lower each block with the existing straight-line code, unchanged. Within a block, values stay symbolic exactly as today.
3. At block boundaries, every register that is live-out and written in any block of the region is spilled to a **join variable** declared once at function scope: `uint jv5;` / `uint js12;` (raw 32-bit bits, so float and integer values both survive bit-exactly; reads become `("uint", "jv5")`, which fp_operand already turns into `asfloat(jv5)`). Lane masks use `bool jc_vcc;`.
4. **Provenance values** (descriptor words, `texture_ptr`, `interp_base`, sample/vmcnt state, `pending`) are not spilled: they must be identical on every incoming edge of a block, or the program is refused ("descriptor state differs at a join"). Real shaders set descriptors up in the entry block.
5. Emission: one HLSL function body in **structured form when the CFG is reducible and matches if / if-else / loop patterns** (`if (c) { ... } else { ... }`, `[loop] while (true) { ...; if (!c) break; }`), which keeps implicit-derivative sampling legal in uniform control flow and lets DXC optimize. A CFG that does not match is refused in the first card (no dispatcher yet); a `switch(pc)` dispatcher can be added later as a fallback.
6. **Masked writes**: when `exec_on` is not provably true (inside a divergent region), each VALU result written to a register becomes `exec_on ? new : old` on the join variable or the previous symbolic value. Implement once: wrap the `vector` dict in a recorder that captures writes per instruction; after a VALU branch runs, the recorder emits the select. Branches stop checking `mask != "entry"` and instead the recorder handles the mask (one mechanical edit across ~27 branches).
7. **Samples and derivatives**: an implicit-LOD `image_sample` inside a divergent region is refused in the first cards (desktop derivatives are undefined in divergent flow; console helper lanes keep computing). A later card can hoist coordinates or use explicit gradients computed in uniform flow.
8. Memory loads (card 4b) inside a divergent region execute only when `exec_on` (wrap in `if (exec_on)`), returning the old destination otherwise.

## Checks the translator performs
- Every branch target resolves; no fallthrough off the end; one export path.
- Divergent regions are single-entry/single-exit and bracketed by saveexec/restore pairs as LLVM emits them; exec restored on every exit edge.
- Provenance agreement at joins.
- No refused operation inside a divergent region (implicit-LOD sample, mask popcount/search, cross-lane DPP/readlane/permlane, LDS swizzle).

## Tests (each card)
Source-built programs assembled by llvm-mc 15 (gfx1013) with labels; draws whose per-pixel inputs differ so lanes really diverge (use the interpolated uv or a per-pixel texture value as the condition); CPU reference per pixel; wrong references for: masked write not applied, else-branch result leaking, loop running one iteration too few/many, exec not restored after the region.

## Cards
- **CF-1**: blocks, labels, `s_branch`, uniform `s_cbranch_scc0/scc1`, join variables, structured if/else and loops on uniform conditions. No exec changes.
- **CF-2**: divergence: `v_cmp` → `s_and_saveexec_b32/b64`, `s_xor_b32/b64 exec`, `s_or_b32/b64 exec` restore, `s_andn2_b32/b64 exec`, `s_cbranch_execz/execnz`, masked writes via the recorder, loops with per-lane exit (`s_cbranch_execnz` back-edge).
- **CF-3**: wave-level questions with wave intrinsics where sound, explicit-gradient sampling in divergent flow, `switch(pc)` fallback for irreducible shapes.
