# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[16:19], s[2:3], 0x50                       ; f4080401 fa000050
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s1, s[4:7], 0x4                         ; f4200042 fa000004
	v_lshrrev_b64 v[3:4], 0, 0                                  ; d7000003 00010080
	v_lshrrev_b64 v[5:6], 0, 0                                  ; d7000005 00010080
	v_mov_b32_e32 v7, 0                                         ; 7e0e0280
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_cvt_f32_i32_e32 v8, s1                                    ; 7e100a01
	image_sample_l  v[3:7], [v0, v2, v8], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D tfe ; f0910f0a 00820300 00000802
	s_buffer_load_dword s2, s[4:7], 0x8                         ; f4200082 fa000008
	s_mov_b64 s[20:21], exec                                    ; be94047e
	s_add_u32 s1, s1, 1                                         ; 80018101
	s_nop 0                                                     ; bf800000
BB1:
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_ge_i32 s2, s1                                         ; bf030102
	s_cselect_b64 s[22:23], -1, 0                               ; 859680c1
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_ne_i32_e32 vcc, 0, v7                                 ; 7d0a0e80
	s_nand_b64 s[22:23], s[22:23], vcc                          ; 8c966a16
	s_and_saveexec_b64 s[22:23], s[22:23]                       ; be962416
BB2:
	v_mov_b32_e32 v0, s1                                        ; 7e000201
	s_andn2_b64 s[22:23], s[22:23], exec                        ; 8a967e16
	s_cbranch_scc0 BB10                                         ; bf84000c
BB9:
	s_mov_b64 exec, s[22:23]                                    ; befe0416
	v_cvt_f32_i32_e32 v1, s1                                    ; 7e020a01
	v_lshrrev_b64 v[3:4], 0, 0                                  ; d7000003 00010080
	v_lshrrev_b64 v[5:6], 0, 0                                  ; d7000005 00010080
	v_mov_b32_e32 v7, 0                                         ; 7e0e0280
	image_sample_l  v[3:7], [v0, v2, v1], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D tfe ; f0910f0a 00820300 00000102
	s_add_u32 s1, s1, 1                                         ; 80018101
	s_branch BB1                                                ; bf82ffea
BB10:
	s_buffer_load_dword s0, s[4:7], null                        ; f4200002 fa000000
	s_mov_b64 exec, s[20:21]                                    ; befe0414
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_lg_i32 s0, 0                                          ; bf018000
	s_cbranch_scc0 BB13                                         ; bf84000f
BB11:
	v_mul_lo_u32 v0, 12, v0                                     ; d5690000 0002008c
	s_getpc_b64 s[0:1]                                          ; be801f00
	s_mov_b32 s2, 60                                            ; be8203bc
	s_mov_b32 s3, 0x31016fac                                    ; be8303ff 31016fac
	s_add_u32 s0, s0, 0x58                                      ; 8000ff00 00000058
	v_add_nc_u32_e32 v0, -12, v0                                ; 4a0000cc
	buffer_load_dwordx3 v[0:2], v0, s[0:3], 0 offen             ; e03c1000 80000000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v3, v3, v0                                    ; 10060103
	v_mul_f32_e32 v4, v4, v1                                    ; 10080304
	v_mul_f32_e32 v5, v5, v2                                    ; 100a0505
BB13:
	v_cvt_pkrtz_f16_f32_e32 v3, v3, v4                          ; 5e060903
	v_cvt_pkrtz_f16_f32_e32 v5, v5, v6                          ; 5e0a0d05
	exp mrt0 v3, v3, v5, v5 done compr vm                       ; f8001c0f 80800503
	s_endpgm                                                    ; bf810000
