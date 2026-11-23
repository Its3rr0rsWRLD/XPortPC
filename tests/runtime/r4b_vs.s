; R4b vertex program (gfx1013): vertex fetch through buffer V#s read from a descriptor table. Entry: v0 vertex id
; from 0; s2 base vertex; s4 low word of the descriptor table address (the positions' V# at byte 0x00, the
; colours' V# at 0x20). Both V#s are the shim's encoding of structured buffer SRVs the title created through the
; API: idxen scales the index by the V#'s stride, and an index at or past num_records reads zero.
v_add_nc_u32_e32 v1, s2, v0
s_movk_i32 s5, 0x8000
s_load_dwordx4 s[8:11], s[4:5], null
s_load_dwordx4 s[12:15], s[4:5], 0x20
s_waitcnt lgkmcnt(0)
buffer_load_dwordx4 v[4:7], v1, s[8:11], 0 idxen
buffer_load_dwordx4 v[8:11], v1, s[12:15], 0 idxen offset:4
s_waitcnt vmcnt(0)
exp param0 v8, v9, v10, v11
exp pos0 v4, v5, v6, v7 done vm
s_endpgm
