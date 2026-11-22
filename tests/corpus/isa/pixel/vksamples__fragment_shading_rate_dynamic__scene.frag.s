# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	s_cmp_eq_i32 s3, 0                                          ; bf008003
	v_interp_p1_f32_e32 v4, v0, attr0.y                         ; c8100100
	v_interp_p1_f32_e32 v5, v0, attr0.x                         ; c8140000
	v_interp_p2_f32_e32 v4, v1, attr0.y                         ; c8110101
	v_interp_p2_f32_e32 v5, v1, attr0.x                         ; c8150001
	s_cbranch_scc0 BB2                                          ; bf84001c
BB1:
	s_mov_b32 s0, s2                                            ; be800302
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[0:1], 0x20                        ; f40c0200 fa000020
	s_load_dwordx4 s[4:7], s[0:1], 0x70                         ; f4080100 fa000070
	v_sub_f32_e32 v6, 1.0, v4                                   ; 080c08f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[6:8], v[5:6], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00220605
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_subrev_f32_dpp v9, v6, v6 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 0a120cfa ff0c0006
	v_subrev_f32_dpp v10, v7, v7 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 0a140efa ff0c0007
	v_subrev_f32_dpp v11, v8, v8 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 0a1610fa ff0c0008
	v_mov_b32_dpp v9, v9 quad_perm:[1,1,1,1] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e1202fa ff0c5509
	v_mov_b32_dpp v10, v10 quad_perm:[1,1,1,1] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e1402fa ff0c550a
	v_mov_b32_dpp v11, v11 quad_perm:[1,1,1,1] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e1602fa ff0c550b
	v_mul_f32_e32 v10, v10, v10                                 ; 1014150a
	v_mac_f32_e32 v10, v11, v11                                 ; 3e14170b
	v_mac_f32_e32 v10, v9, v9                                   ; 3e141309
	s_branch BB3                                                ; bf820001
BB2:
	v_mov_b32_e32 v10, 0                                        ; 7e140280
BB3:
	s_cmp_eq_i32 s3, 1                                          ; bf008103
	s_cbranch_scc0 BB5                                          ; bf840067
BB4:
	s_mov_b32 s0, s2                                            ; be800302
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[0:1], 0x80                        ; f40c0200 fa000080
	s_load_dwordx4 s[4:7], s[0:1], 0xd0                         ; f4080100 fa0000d0
	v_sub_f32_e32 v6, 1.0, v4                                   ; 080c08f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[4:6], v[5:6], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00220405
	v_interp_p1_f32_e32 v7, v0, attr0.w                         ; c81c0300
	v_interp_p1_f32_e32 v9, v0, attr1.x                         ; c8240400
	v_interp_p1_f32_e32 v10, v0, attr0.z                        ; c8280200
	v_interp_p1_f32_e32 v11, v0, attr2.y                        ; c82c0900
	v_interp_p1_f32_e32 v13, v0, attr2.z                        ; c8340a00
	v_interp_p1_f32_e32 v14, v0, attr2.x                        ; c8380800
	v_interp_p2_f32_e32 v7, v1, attr0.w                         ; c81d0301
	v_interp_p2_f32_e32 v9, v1, attr1.x                         ; c8250401
	v_interp_p2_f32_e32 v10, v1, attr0.z                        ; c8290201
	v_interp_p2_f32_e32 v11, v1, attr2.y                        ; c82d0901
	v_interp_p2_f32_e32 v13, v1, attr2.z                        ; c8350a01
	v_interp_p2_f32_e32 v14, v1, attr2.x                        ; c8390801
	v_interp_p1_f32_e32 v15, v0, attr1.z                        ; c83c0600
	v_interp_p2_f32_e32 v15, v1, attr1.z                        ; c83d0601
	v_interp_p1_f32_e32 v17, v0, attr1.w                        ; c8440700
	v_interp_p2_f32_e32 v17, v1, attr1.w                        ; c8450701
	v_mul_f32_e32 v8, v7, v7                                    ; 10100f07
	v_mul_f32_e32 v12, v11, v11                                 ; 1018170b
	v_mul_f32_e32 v16, v15, v15                                 ; 10201f0f
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mac_f32_e32 v8, v9, v9                                    ; 3e101309
	v_mac_f32_e32 v12, v13, v13                                 ; 3e181b0d
	v_mac_f32_e32 v16, v17, v17                                 ; 3e202311
	v_mac_f32_e32 v8, v10, v10                                  ; 3e10150a
	v_mac_f32_e32 v12, v14, v14                                 ; 3e181d0e
	v_mac_f32_e32 v16, v0, v0                                   ; 3e200100
	v_rsq_f32_e32 v8, v8                                        ; 7e105d08
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_rsq_f32_e32 v16, v16                                      ; 7e205d10
	v_mul_f32_e32 v10, v10, v8                                  ; 1014110a
	v_mul_f32_e32 v7, v7, v8                                    ; 100e1107
	v_mul_f32_e32 v9, v9, v8                                    ; 10121109
	v_mul_f32_e32 v13, v13, v12                                 ; 101a190d
	v_mul_f32_e32 v14, v14, v12                                 ; 101c190e
	v_mul_f32_e32 v11, v11, v12                                 ; 1016190b
	v_mul_f32_e32 v0, v0, v16                                   ; 10002100
	v_mul_f32_e32 v15, v15, v16                                 ; 101e210f
	v_mul_f32_e32 v17, v17, v16                                 ; 10222111
	v_mul_f32_e32 v18, v13, v9                                  ; 1024130d
	v_mad_f32 v19, v11, -v7, -v18                               ; d5410013 c44a0f0b
	v_mac_f32_e32 v18, v11, v7                                  ; 3e240f0b
	v_mad_f32 v19, v14, -v10, v19 mul:2                         ; d5410013 4c4e150e
	v_mac_f32_e32 v18, v14, v10                                 ; 3e24150e
	v_mad_f32 v9, v9, -v19, -v13                                ; d5410009 c4362709
	v_mad_f32 v20, v10, -v19, -v14                              ; d5410014 c43a270a
	v_mad_f32 v21, v7, -v19, -v11                               ; d5410015 c42e2707
	v_max_f32_e32 v18, 0, v18                                   ; 20242480
	v_mul_f32_e32 v9, v9, v17                                   ; 10122309
	v_mac_f32_e32 v9, v21, v15                                  ; 3e121f15
	v_mac_f32_e32 v9, v20, v0                                   ; 3e120114
	v_max_f32_e32 v9, 0, v9                                     ; 20121280
	v_mul_f32_e32 v9, v9, v9                                    ; 10121309
	(then repeated 1 times)
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v7, v5, v18                                   ; 060e2505
	v_add_f32_e32 v4, v4, v18                                   ; 06082504
	v_add_f32_e32 v8, v6, v18                                   ; 06102506
	v_mac_f32_e32 v7, v9, v9                                    ; 3e0e1309
	v_mad_f32 v6, v9, v9, v4                                    ; d5410006 04121309
	v_mac_f32_e32 v8, v9, v9                                    ; 3e101309
	v_subrev_f32_dpp v0, v7, v7 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 0a000efa ff0c0007
	v_subrev_f32_dpp v22, v6, v6 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 0a2c0cfa ff0c0006
	v_subrev_f32_dpp v4, v8, v8 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 0a0810fa ff0c0008
	v_mov_b32_dpp v1, v0 quad_perm:[1,1,1,1] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e0202fa ff0c5500
	v_mov_b32_dpp v0, v0 quad_perm:[2,2,2,2] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e0002fa ff0caa00
	v_mov_b32_dpp v23, v22 quad_perm:[1,1,1,1] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e2e02fa ff0c5516
	v_mov_b32_dpp v22, v22 quad_perm:[2,2,2,2] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e2c02fa ff0caa16
	v_mov_b32_dpp v5, v4 quad_perm:[1,1,1,1] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e0a02fa ff0c5504
	v_mov_b32_dpp v4, v4 quad_perm:[2,2,2,2] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e0802fa ff0caa04
	v_mul_f32_e32 v10, v1, v1                                   ; 10140301
	v_mul_f32_e32 v0, v0, v0                                    ; 10000100
	v_mac_f32_e32 v10, v5, v5                                   ; 3e140b05
	v_mac_f32_e32 v0, v4, v4                                    ; 3e000904
	v_mac_f32_e32 v10, v23, v23                                 ; 3e142f17
	v_mac_f32_e32 v0, v22, v22                                  ; 3e002d16
	s_branch BB6                                                ; bf820001
BB5:
	v_mov_b32_e32 v0, v10                                       ; 7e00030a
BB6:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx4 s[4:7], s[2:3], null                         ; f4080101 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s0, s[4:7], 0xc0                        ; f4200002 fa0000c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_eq_i32 s0, 1                                          ; bf008100
	s_cbranch_scc0 BB8                                          ; bf840022
BB7:
	v_bfe_u32 v1, v2, 4, 2                                      ; d5480001 02090902
	v_bfe_u32 v2, v2, 2, 2                                      ; d5480002 02090502
	v_cmp_eq_i32_e32 vcc, 1, v1                                 ; 7d040281
	v_cndmask_b32_e64 v3, 0, 1, vcc                             ; d5010003 01a90280
	v_cmp_eq_i32_e32 vcc, 1, v2                                 ; 7d040481
	v_mov_b32_e32 v7, 1.0                                       ; 7e0e02f2
	v_cndmask_b32_e64 v4, 0, 4, vcc                             ; d5010004 01a90880
	v_or_b32_e32 v4, v4, v3                                     ; 38080704
	v_cmp_class_f16_e32 vcc, 0x7c01, v4                         ; 7d1e08ff 00007c01
	v_cndmask_b32_e64 v5, 1, 2, vcc                             ; d5010005 01a90481
	v_cmp_class_f32_e32 vcc, -1, v4                             ; 7d1008c1
	v_cndmask_b32_e64 v5, v5, 4, vcc                            ; d5010005 01a90905
	v_cmp_class_f32_e32 vcc, 0xff800000, v4                     ; 7d1008ff ff800000
	v_cndmask_b32_e64 v6, 1, 2, vcc                             ; d5010006 01a90481
	v_cmp_class_f32_e32 vcc, -1.0, v4                           ; 7d1008f3
	v_cndmask_b32_e64 v6, v6, 4, vcc                            ; d5010006 01a90906
	v_mul_u32_u24_e32 v6, v6, v5                                ; 160c0b06
	v_cvt_f32_i32_e32 v6, v6                                    ; 7e0c0b06
	v_mad_f32 v8, 0x3d800000, -v6, 1.0                          ; d5410008 43ca0cff 3d800000
	v_mov_b32_e32 v5, v8                                        ; 7e0a0308
	v_mov_b32_e32 v6, v8                                        ; 7e0c0308
	s_branch BB12                                               ; bf820010
BB8:
	s_cmp_eq_i32 s0, 2                                          ; bf008200
	s_cbranch_scc0 BB10                                         ; bf84000c
BB9:
	s_load_dwordx8 s[0:7], s[2:3], 0xe0                         ; f40c0001 fa0000e0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_load v[4:7], v3, s[0:7] dmask:0xf dim:SQ_RSRC_IMG_2D unorm a16 ; f0001f08 40000403
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_f32_u32_e32 v7, v7                                    ; 7e0e0d07
	v_cvt_f32_u32_e32 v4, v4                                    ; 7e080d04
	v_cvt_f32_u32_e32 v5, v5                                    ; 7e0a0d05
	v_cvt_f32_u32_e32 v8, v6                                    ; 7e100d06
	v_mov_b32_e32 v6, v4                                        ; 7e0c0304
	s_branch BB12                                               ; bf820002
BB10:
	v_mov_b32_e32 v5, v7                                        ; 7e0a0307
	v_mov_b32_e32 v7, 1.0                                       ; 7e0e02f2
BB12:
	v_mul_f32_e32 v10, 0x437f0000, v10                          ; 101414ff 437f0000
	v_mul_f32_e32 v0, 0x437f0000, v0                            ; 100000ff 437f0000
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v5                          ; 5e0c0b06
	v_cvt_pkrtz_f16_f32_e32 v8, v8, v7                          ; 5e100f08
	v_cvt_u32_f32_e32 v10, v10                                  ; 7e140f0a
	v_cvt_u32_f32_e32 v0, v0                                    ; 7e000f00
	v_cvt_pk_u16_u32 v10, v10, v0                               ; d76a000a 0002010a
	exp mrt0 v6, v6, v8, v8 compr                               ; f800040f 80800806
	exp mrt1 v10, v10, off, off done compr vm                   ; f8001c13 8080800a
	s_endpgm                                                    ; bf810000
