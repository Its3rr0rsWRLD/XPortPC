# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x120                        ; f4080101 fa000120
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s16, s[4:7], 0xd0                       ; f4200402 fa0000d0
	s_mov_b32 m0, s0                                            ; befc0300
	s_bfe_u32 s1, s9, 0x2001e                                   ; 9381ff09 0002001e
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	s_add_u32 s1, s1, 1                                         ; 80018101
	s_and_b32 s19, s10, 0x3fff                                  ; 8713ff0a 00003fff
	s_lshl2_add_u32 s19, s19, s1                                ; 97930113
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	s_cselect_b32 s19, 0, s19                                   ; 85131380
	s_bfe_u32 s18, s10, 0x10000e                                ; 9392ff0a 0010000e
	v_cvt_f32_i32_e32 v3, s19                                   ; 7e060a13
	s_add_u32 s18, s18, 1                                       ; 80128112
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	s_cselect_b32 s18, 0, s18                                   ; 85121280
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_lt_i32 0, s16                                         ; bf041080
	v_cvt_f32_i32_e32 v4, s18                                   ; 7e080a12
	v_cvt_i32_f32_e32 v2, v2                                    ; 7e041102
	v_mul_f32_e32 v0, v0, v4                                    ; 10000900
	v_cvt_i32_f32_e32 v3, v0                                    ; 7e061100
	s_cbranch_scc0 BB14                                         ; bf840045
BB1:
	s_cmp_eq_i32 s16, 1                                         ; bf008110
	s_cbranch_scc0 BB4                                          ; bf84000d
BB2:
	s_load_dwordx8 s[24:31], s[2:3], 0x20                       ; f40c0601 fa000020
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_load v0, v[2:3], s[24:31] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f0001108 00060002
	v_cmp_ne_u32_e64 vcc, 0, s25                                ; d4c5006a 00003280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v0, 0x76543210, v0, vcc                   ; 020000ff 76543210
	v_and_b32_e32 v4, 7, v0                                     ; 36080087
	image_load v[4:6], v[2:4], s[8:15] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001730 00020402
BB4:
	s_cmp_eq_i32 s16, 2                                         ; bf008210
	s_cbranch_scc0 BB7                                          ; bf84000e
BB5:
	s_load_dwordx16 s[32:47], s[2:3], 0x60                      ; f4100801 fa000060
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_load v0, v[2:3], s[40:47] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f0001108 000a0002
	s_mov_b32 s0, s41                                           ; be800329
	v_cmp_ne_u32_e64 vcc, 0, s0                                 ; d4c5006a 00000080
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v0, 0x76543210, v0, vcc                   ; 020000ff 76543210
	v_and_b32_e32 v4, 7, v0                                     ; 36080087
	image_load v[4:6], v[2:4], s[32:39] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001730 00080402
BB7:
	s_cmp_eq_i32 s16, 3                                         ; bf008310
	s_cbranch_scc0 BB10                                         ; bf84000f
BB8:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_load_dwordx16 s[32:47], s[2:3], 0xc0                      ; f4100801 fa0000c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_load v0, v[2:3], s[40:47] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f0001108 000a0002
	s_mov_b32 s0, s41                                           ; be800329
	v_cmp_ne_u32_e64 vcc, 0, s0                                 ; d4c5006a 00000080
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v0, 0x76543210, v0, vcc                   ; 020000ff 76543210
	v_and_b32_e32 v4, 7, v0                                     ; 36080087
	image_load v[4:6], v[2:4], s[32:39] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001730 00080402
BB10:
	s_cmp_eq_i32 s16, 4                                         ; bf008410
	s_cbranch_scc0 BB20                                         ; bf8401fa
BB11:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_load_dwordx16 s[0:15], s[2:3], 0xc0                       ; f4100001 fa0000c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_load v0, v[2:3], s[8:15] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f0001108 00020002
	s_mov_b32 s16, s9                                           ; be900309
	v_cmp_ne_u32_e64 vcc, 0, s16                                ; d4c5006a 00002080
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v0, 0x76543210, v0, vcc                   ; 020000ff 76543210
	v_and_b32_e32 v4, 7, v0                                     ; 36080087
	image_load v6, v[2:4], s[0:7] dmask:0x8 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001830 00000602
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mov_b32_e32 v4, v6                                        ; 7e080306
	v_mov_b32_e32 v5, v6                                        ; 7e0a0306
	s_branch BB20                                               ; bf8201e7
BB14:
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx16 s[16:31], s[2:3], 0xc0                      ; f4100401 fa0000c0
	s_load_dwordx8 s[32:39], s[2:3], 0x20                       ; f40c0801 fa000020
	s_load_dwordx16 s[48:63], s[2:3], 0x60                      ; f4100c01 fa000060
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_load v0, v[2:3], s[24:31] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f0001108 00060002
	image_load v1, v[2:3], s[32:39] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f0001108 00080102
	image_load v4, v[2:3], s[56:63] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f0001108 000e0402
	s_mov_b32 s0, s25                                           ; be800319
	v_cmp_ne_u32_e64 vcc, 0, s0                                 ; d4c5006a 00000080
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_cndmask_b32_e32 v0, 0x76543210, v0, vcc                   ; 020000ff 76543210
	v_and_b32_e32 v5, 7, v0                                     ; 360a0087
	v_bfe_u32 v6, v0, 4, 3                                      ; d5480006 020d0900
	v_bfe_u32 v7, v0, 8, 3                                      ; d5480007 020d1100
	v_bfe_u32 v8, v0, 12, 3                                     ; d5480008 020d1900
	image_load v[9:11], [v2, v3, v5], s[16:23] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001732 00040902 00000503
	image_load v[12:14], [v2, v3, v6], s[16:23] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001732 00040c02 00000603
	image_load v[15:17], [v2, v3, v7], s[16:23] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001732 00040f02 00000703
	image_load v[18:20], [v2, v3, v8], s[16:23] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001732 00041202 00000803
	s_mov_b32 s1, s33                                           ; be810321
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[32:47], s[4:7], null               ; f4300802 fa000000
	s_buffer_load_dwordx4 s[24:27], s[4:7], 0xc0                ; f4280602 fa0000c0
	v_bfe_u32 v21, v0, 16, 3                                    ; d5480015 020d2100
	image_load v[22:24], [v2, v3, v21], s[16:23] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001732 00041602 00001503
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[64:79], s[4:7], 0x40               ; f4301002 fa000040
	s_buffer_load_dwordx16 s[80:95], s[4:7], 0x80               ; f4301402 fa000080
	v_bfe_u32 v25, v0, 20, 3                                    ; d5480019 020d2900
	v_bfe_u32 v29, v0, 24, 3                                    ; d548001d 020d3100
	v_bfe_u32 v33, v0, 28, 3                                    ; d5480021 020d3900
	image_load v[26:28], [v2, v3, v25], s[16:23] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001732 00041a02 00001903
	image_load v[30:32], [v2, v3, v29], s[16:23] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001732 00041e02 00001d03
	image_load v[34:36], [v2, v3, v33], s[16:23] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001732 00042202 00002103
	s_mov_b32 s2, s57                                           ; be820339
	v_cmp_ne_u32_e64 vcc, 0, s1                                 ; d4c5006a 00000280
	v_cmp_ne_u32_e64 s[0:1], 0, s2                              ; d4c50000 00000480
	s_waitcnt vmcnt(9)                                          ; bf8c3f79
	v_cndmask_b32_e32 v1, 0x76543210, v1, vcc                   ; 020202ff 76543210
	s_waitcnt vmcnt(8)                                          ; bf8c3f78
	v_cndmask_b32_e64 v4, 0x76543210, v4, s[0:1]                ; d5010004 000208ff 76543210
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v11, v11, v14                                 ; 06161d0b
	v_add_f32_e32 v9, v9, v12                                   ; 06121909
	v_add_f32_e32 v10, v10, v13                                 ; 06141b0a
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v11, v11, v17                                 ; 0616230b
	v_add_f32_e32 v9, v9, v15                                   ; 06121f09
	v_add_f32_e32 v10, v10, v16                                 ; 0614210a
	s_mov_b32 s0, 0                                             ; be800380
	v_lshrrev_b64 v[5:6], 0, 0                                  ; d7000005 00010080
	v_mov_b32_e32 v7, 0                                         ; 7e0e0280
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v11, v11, v20                                 ; 0616290b
	v_add_f32_e32 v9, v9, v18                                   ; 06122509
	v_add_f32_e32 v10, v10, v19                                 ; 0614270a
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v11, v11, v24                                 ; 0616310b
	v_add_f32_e32 v9, v9, v22                                   ; 06122d09
	v_add_f32_e32 v10, v10, v23                                 ; 06142f0a
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v11, v11, v28                                 ; 0616390b
	v_add_f32_e32 v9, v9, v26                                   ; 06123509
	v_add_f32_e32 v10, v10, v27                                 ; 0614370a
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v11, v11, v32                                 ; 0616410b
	v_add_f32_e32 v9, v9, v30                                   ; 06123d09
	v_add_f32_e32 v10, v10, v31                                 ; 06143f0a
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v11, v11, v36                                 ; 0616490b
	v_add_f32_e32 v9, v9, v34                                   ; 06124509
	v_add_f32_e32 v10, v10, v35                                 ; 0614470a
	s_nop 0                                                     ; bf800000
	(then repeated 3 times)
BB15:
	s_lshl_b32 s1, s0, 2                                        ; 8f018200
	v_bfe_u32 v8, v1, s1, 3                                     ; d5480008 020c0301
	image_load v[12:14], [v2, v3, v8], s[8:15] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001732 00020c02 00000803
	v_bfe_u32 v15, v4, s1, 3                                    ; d548000f 020c0304
	image_load v[16:18], [v2, v3, v15], s[48:55] dmask:0x7 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001732 000c1002 00000f03
	v_bfe_u32 v19, v0, s1, 3                                    ; d5480013 020c0300
	image_load v[20:23], [v2, v3, v19], s[16:23] dmask:0xf dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001f32 00041402 00001303
	s_add_u32 s0, s0, 1                                         ; 80008100
	s_cmp_ge_i32 s0, 8                                          ; bf038800
	s_waitcnt vmcnt(2) lgkmcnt(0)                               ; bf8c0072
	v_sub_f32_e32 v29, s25, v13                                 ; 083a1a19
	v_sub_f32_e32 v30, s26, v14                                 ; 083c1c1a
	v_sub_f32_e32 v24, s32, v12                                 ; 08301820
	v_sub_f32_e32 v25, s33, v13                                 ; 08321a21
	v_sub_f32_e32 v26, s34, v14                                 ; 08341c22
	v_sub_f32_e32 v28, s24, v12                                 ; 08381818
	v_mul_f32_e32 v31, v29, v29                                 ; 103e3b1d
	v_mul_f32_e32 v27, v25, v25                                 ; 10363319
	v_sub_f32_e32 v33, s40, v12                                 ; 08421828
	v_sub_f32_e32 v34, s41, v13                                 ; 08441a29
	v_mac_f32_e32 v31, v30, v30                                 ; 3e3e3d1e
	v_sub_f32_e32 v35, s42, v14                                 ; 08461c2a
	v_mac_f32_e32 v27, v26, v26                                 ; 3e36351a
	v_mul_f32_e32 v36, v34, v34                                 ; 10484522
	v_mac_f32_e32 v31, v28, v28                                 ; 3e3e391c
	v_mac_f32_e32 v27, v24, v24                                 ; 3e363118
	v_mac_f32_e32 v36, v35, v35                                 ; 3e484723
	v_rsq_f32_e32 v31, v31                                      ; 7e3e5d1f
	v_rsq_f32_e32 v32, v27                                      ; 7e405d1b
	v_add_f32_e32 v27, 1.0, v27                                 ; 063636f2
	v_mac_f32_e32 v36, v33, v33                                 ; 3e484321
	v_sub_f32_e32 v38, s64, v12                                 ; 084c1840
	v_sub_f32_e32 v39, s65, v13                                 ; 084e1a41
	v_sub_f32_e32 v40, s66, v14                                 ; 08501c42
	v_mul_f32_e32 v28, v28, v31                                 ; 10383f1c
	v_mul_f32_e32 v29, v29, v31                                 ; 103a3f1d
	v_mul_f32_e32 v30, v30, v31                                 ; 103c3f1e
	v_rcp_f32_e32 v27, v27                                      ; 7e36551b
	v_rsq_f32_e32 v37, v36                                      ; 7e4a5d24
	v_add_f32_e32 v36, 1.0, v36                                 ; 064848f2
	v_mul_f32_e32 v41, v39, v39                                 ; 10524f27
	v_mul_f32_e32 v24, v24, v32                                 ; 10304118
	v_mul_f32_e32 v25, v25, v32                                 ; 10324119
	v_mul_f32_e32 v26, v26, v32                                 ; 1034411a
	v_sub_f32_e32 v43, s72, v12                                 ; 08561848
	v_rcp_f32_e32 v36, v36                                      ; 7e485524
	v_mul_f32_e32 v27, s39, v27                                 ; 10363627
	v_sub_f32_e32 v44, s73, v13                                 ; 08581a49
	v_mac_f32_e32 v41, v40, v40                                 ; 3e525128
	v_sub_f32_e32 v45, s74, v14                                 ; 085a1c4a
	v_mul_f32_e32 v33, v33, v37                                 ; 10424b21
	v_mul_f32_e32 v35, v35, v37                                 ; 10464b23
	v_mul_f32_e32 v34, v34, v37                                 ; 10444b22
	v_mul_f32_e32 v46, v44, v44                                 ; 105c592c
	v_mac_f32_e32 v41, v38, v38                                 ; 3e524d26
	v_mul_f32_e32 v36, s47, v36                                 ; 1048482f
	v_mac_f32_e32 v46, v45, v45                                 ; 3e5c5b2d
	v_rsq_f32_e32 v42, v41                                      ; 7e545d29
	v_add_f32_e32 v41, 1.0, v41                                 ; 065252f2
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mul_f32_e32 v8, v17, v17                                  ; 10102311
	v_mac_f32_e32 v46, v43, v43                                 ; 3e5c572b
	v_rcp_f32_e32 v41, v41                                      ; 7e525529
	v_mac_f32_e32 v8, v18, v18                                  ; 3e102512
	v_rsq_f32_e32 v47, v46                                      ; 7e5e5d2e
	v_add_f32_e32 v46, 1.0, v46                                 ; 065c5cf2
	v_mul_f32_e32 v39, v39, v42                                 ; 104e5527
	v_mul_f32_e32 v40, v40, v42                                 ; 10505528
	v_mul_f32_e32 v38, v38, v42                                 ; 104c5526
	v_mac_f32_e32 v8, v16, v16                                  ; 3e102110
	v_mul_f32_e32 v41, s71, v41                                 ; 10525247
	v_rcp_f32_e32 v46, v46                                      ; 7e5c552e
	v_mul_f32_e32 v43, v43, v47                                 ; 10565f2b
	v_rsq_f32_e32 v8, v8                                        ; 7e105d08
	v_mul_f32_e32 v44, v44, v47                                 ; 10585f2c
	v_mul_f32_e32 v45, v45, v47                                 ; 105a5f2d
	v_sub_f32_e32 v47, s80, v12                                 ; 085e1850
	v_mul_f32_e32 v46, s79, v46                                 ; 105c5c4f
	v_mul_f32_e32 v18, v18, v8                                  ; 10241112
	v_mul_f32_e32 v16, v16, v8                                  ; 10201110
	v_mul_f32_e32 v17, v17, v8                                  ; 10221111
	v_mul_f32_e32 v15, v18, v26                                 ; 101e3512
	v_mad_f32 v19, v17, v25, v15                                ; d5410013 043e3311
	v_mad_f32 v15, v17, -v25, -v15                              ; d541000f c43e3311
	v_mac_f32_e32 v19, v16, v24                                 ; 3e263110
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v31, s38, v22                                 ; 103e2c26
	v_mad_f32 v15, v16, -v24, v15 mul:2                         ; d541000f 4c3e3110
	v_max_f32_e32 v19, 0, v19                                   ; 20262680
	v_mad_f32 v25, v17, -v15, -v25                              ; d5410019 c4661f11
	v_mad_f32 v24, v16, -v15, -v24                              ; d5410018 c4621f10
	v_mad_f32 v15, v18, -v15, -v26                              ; d541000f c46a1f12
	v_mul_f32_e32 v26, s37, v21                                 ; 10342a25
	v_mul_f32_e32 v32, s36, v23                                 ; 10402e24
	v_mul_f32_e32 v37, s37, v23                                 ; 104a2e25
	v_mul_f32_e32 v42, s38, v23                                 ; 10542e26
	v_mul_f32_e32 v31, v31, v19                                 ; 103e271f
	v_mul_f32_e32 v15, v15, v30                                 ; 101e3d0f
	v_mul_f32_e32 v26, v26, v19                                 ; 1034271a
	v_mac_f32_e32 v15, v25, v29                                 ; 3e1e3b19
	v_mul_f32_e32 v25, s36, v20                                 ; 10322824
	v_mac_f32_e32 v15, v24, v28                                 ; 3e1e3918
	v_mul_f32_e32 v24, v18, v35                                 ; 10304712
	v_mul_f32_e32 v25, v25, v19                                 ; 10322719
	v_mul_f32_e32 v19, s45, v21                                 ; 10262a2d
	v_max_f32_e32 v15, 0, v15                                   ; 201e1e80
	v_mad_f32 v8, v17, v34, v24                                 ; d5410008 04624511
	v_mul_f32_e32 v15, v15, v15                                 ; 101e1f0f
	v_mad_f32 v24, v17, -v34, -v24                              ; d5410018 c4624511
	v_mac_f32_e32 v8, v16, v33                                  ; 3e104310
	v_mul_f32_e32 v15, v15, v15                                 ; 101e1f0f
	v_mad_f32 v24, v16, -v33, v24 mul:2                         ; d5410018 4c624310
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_mul_f32_e32 v15, v15, v15                                 ; 101e1f0f
	v_mad_f32 v34, v17, -v24, -v34                              ; d5410022 c48a3111
	v_mad_f32 v33, v16, -v24, -v33                              ; d5410021 c4863110
	v_mad_f32 v24, v18, -v24, -v35                              ; d5410018 c48e3112
	v_mul_f32_e32 v19, v19, v8                                  ; 10261113
	v_mac_f32_e32 v26, v37, v15                                 ; 3e341f25
	v_mac_f32_e32 v25, v32, v15                                 ; 3e321f20
	v_mul_f32_e32 v32, s44, v23                                 ; 10402e2c
	v_mac_f32_e32 v31, v42, v15                                 ; 3e3e1f2a
	v_mul_f32_e32 v15, s44, v20                                 ; 101e282c
	v_mul_f32_e32 v24, v24, v30                                 ; 10303d18
	v_mul_f32_e32 v26, v27, v26                                 ; 1034351b
	v_mul_f32_e32 v25, v27, v25                                 ; 1032331b
	v_mul_f32_e32 v27, v27, v31                                 ; 10363f1b
	v_mul_f32_e32 v31, s46, v22                                 ; 103e2c2e
	v_mul_f32_e32 v15, v15, v8                                  ; 101e110f
	v_mac_f32_e32 v24, v34, v29                                 ; 3e303b22
	v_mul_f32_e32 v34, s46, v23                                 ; 10442e2e
	v_mac_f32_e32 v26, v19, v36                                 ; 3e344913
	v_mul_f32_e32 v35, v18, v40                                 ; 10465112
	v_mul_f32_e32 v31, v31, v8                                  ; 103e111f
	v_mac_f32_e32 v25, v15, v36                                 ; 3e32490f
	v_mac_f32_e32 v24, v33, v28                                 ; 3e303921
	v_mul_f32_e32 v33, s45, v23                                 ; 10422e2d
	v_mul_f32_e32 v37, s68, v20                                 ; 104a2844
	v_mul_f32_e32 v42, s69, v21                                 ; 10542a45
	v_mul_f32_e32 v8, s70, v22                                  ; 10102c46
	v_mac_f32_e32 v27, v31, v36                                 ; 3e36491f
	v_max_f32_e32 v24, 0, v24                                   ; 20303080
	v_mul_f32_e32 v24, v24, v24                                 ; 10303118
	(then repeated 2 times)
	v_mul_f32_e32 v32, v32, v24                                 ; 10403120
	v_mul_f32_e32 v33, v33, v24                                 ; 10423121
	v_mul_f32_e32 v34, v34, v24                                 ; 10443122
	v_mac_f32_e32 v25, v32, v36                                 ; 3e324920
	v_mac_f32_e32 v26, v33, v36                                 ; 3e344921
	v_mul_f32_e32 v15, s68, v23                                 ; 101e2e44
	v_mac_f32_e32 v27, v34, v36                                 ; 3e364922
	v_mad_f32 v36, v17, v39, v35                                ; d5410024 048e4f11
	v_mad_f32 v35, v17, -v39, -v35                              ; d5410023 c48e4f11
	v_mul_f32_e32 v19, s69, v23                                 ; 10262e45
	v_mul_f32_e32 v24, s70, v23                                 ; 10302e46
	v_mac_f32_e32 v36, v16, v38                                 ; 3e484d10
	v_mad_f32 v35, v16, -v38, v35 mul:2                         ; d5410023 4c8e4d10
	v_max_f32_e32 v36, 0, v36                                   ; 20484880
	v_mad_f32 v38, v16, -v35, -v38                              ; d5410026 c49a4710
	v_mad_f32 v39, v17, -v35, -v39                              ; d5410027 c49e4711
	v_mad_f32 v35, v18, -v35, -v40                              ; d5410023 c4a24712
	v_mul_f32_e32 v42, v42, v36                                 ; 1054492a
	v_mul_f32_e32 v37, v37, v36                                 ; 104a4925
	v_mul_f32_e32 v8, v8, v36                                   ; 10104908
	v_mul_f32_e32 v35, v35, v30                                 ; 10463d23
	v_mul_f32_e32 v31, v18, v45                                 ; 103e5b12
	v_mac_f32_e32 v26, v42, v41                                 ; 3e34532a
	v_mac_f32_e32 v25, v37, v41                                 ; 3e325325
	v_mac_f32_e32 v27, v8, v41                                  ; 3e365308
	v_mul_f32_e32 v33, s76, v20                                 ; 1042284c
	v_mul_f32_e32 v34, s77, v21                                 ; 10442a4d
	v_mac_f32_e32 v35, v39, v29                                 ; 3e463b27
	v_mad_f32 v32, v17, v44, v31                                ; d5410020 047e5911
	v_mac_f32_e32 v35, v38, v28                                 ; 3e463926
	v_mac_f32_e32 v32, v16, v43                                 ; 3e405710
	v_mad_f32 v31, v17, -v44, -v31                              ; d541001f c47e5911
	v_max_f32_e32 v35, 0, v35                                   ; 20464680
	v_max_f32_e32 v32, 0, v32                                   ; 20404080
	v_mad_f32 v31, v16, -v43, v31 mul:2                         ; d541001f 4c7e5710
	v_mul_f32_e32 v35, v35, v35                                 ; 10464723
	v_mul_f32_e32 v34, v34, v32                                 ; 10444122
	v_mul_f32_e32 v33, v33, v32                                 ; 10424121
	v_mad_f32 v44, v17, -v31, -v44                              ; d541002c c4b23f11
	v_mad_f32 v43, v16, -v31, -v43                              ; d541002b c4ae3f10
	v_mad_f32 v31, v18, -v31, -v45                              ; d541001f c4b63f12
	v_mul_f32_e32 v36, s76, v23                                 ; 10482e4c
	v_mul_f32_e32 v37, s77, v23                                 ; 104a2e4d
	v_mul_f32_e32 v38, s78, v23                                 ; 104c2e4e
	v_mul_f32_e32 v35, v35, v35                                 ; 10464723
	v_mul_f32_e32 v31, v31, v30                                 ; 103e3d1f
	v_mul_f32_e32 v35, v35, v35                                 ; 10464723
	v_mac_f32_e32 v31, v44, v29                                 ; 3e3e3b2c
	v_mul_f32_e32 v24, v24, v35                                 ; 10304718
	v_mul_f32_e32 v19, v19, v35                                 ; 10264713
	v_mul_f32_e32 v15, v15, v35                                 ; 101e470f
	v_mul_f32_e32 v35, s78, v22                                 ; 10462c4e
	v_mac_f32_e32 v31, v43, v28                                 ; 3e3e392b
	v_mac_f32_e32 v27, v24, v41                                 ; 3e365318
	v_mac_f32_e32 v26, v19, v41                                 ; 3e345313
	v_sub_f32_e32 v39, s81, v13                                 ; 084e1a51
	v_mac_f32_e32 v25, v15, v41                                 ; 3e32530f
	v_sub_f32_e32 v40, s82, v14                                 ; 08501c52
	v_mul_f32_e32 v35, v35, v32                                 ; 10464123
	v_max_f32_e32 v31, 0, v31                                   ; 203e3e80
	v_mac_f32_e32 v26, v34, v46                                 ; 3e345d22
	v_mul_f32_e32 v41, v39, v39                                 ; 10524f27
	v_mac_f32_e32 v25, v33, v46                                 ; 3e325d21
	v_mac_f32_e32 v27, v35, v46                                 ; 3e365d23
	v_mul_f32_e32 v31, v31, v31                                 ; 103e3f1f
	v_mac_f32_e32 v41, v40, v40                                 ; 3e525128
	v_mul_f32_e32 v31, v31, v31                                 ; 103e3f1f
	v_mac_f32_e32 v41, v47, v47                                 ; 3e525f2f
	v_mul_f32_e32 v31, v31, v31                                 ; 103e3f1f
	v_rsq_f32_e32 v42, v41                                      ; 7e545d29
	v_add_f32_e32 v41, 1.0, v41                                 ; 065252f2
	v_mul_f32_e32 v45, s84, v20                                 ; 105a2854
	v_mul_f32_e32 v38, v38, v31                                 ; 104c3f26
	v_mul_f32_e32 v36, v36, v31                                 ; 10483f24
	v_mul_f32_e32 v37, v37, v31                                 ; 104a3f25
	v_mul_f32_e32 v8, s86, v22                                  ; 10102c56
	v_rcp_f32_e32 v41, v41                                      ; 7e525529
	v_mac_f32_e32 v27, v38, v46                                 ; 3e365d26
	v_mac_f32_e32 v25, v36, v46                                 ; 3e325d24
	v_mul_f32_e32 v40, v40, v42                                 ; 10505528
	v_mul_f32_e32 v47, v47, v42                                 ; 105e552f
	v_mac_f32_e32 v26, v37, v46                                 ; 3e345d25
	v_mul_f32_e32 v46, s85, v21                                 ; 105c2a55
	v_mul_f32_e32 v39, v39, v42                                 ; 104e5527
	v_mul_f32_e32 v43, v18, v40                                 ; 10565112
	v_mul_f32_e32 v15, s84, v23                                 ; 101e2e54
	v_mul_f32_e32 v41, s87, v41                                 ; 10525257
	v_mul_f32_e32 v19, s85, v23                                 ; 10262e55
	v_mul_f32_e32 v24, s86, v23                                 ; 10302e56
	v_mad_f32 v44, v17, v39, v43                                ; d541002c 04ae4f11
	v_mad_f32 v43, v17, -v39, -v43                              ; d541002b c4ae4f11
	v_mac_f32_e32 v44, v16, v47                                 ; 3e585f10
	v_mad_f32 v43, v16, -v47, v43 mul:2                         ; d541002b 4cae5f10
	v_max_f32_e32 v44, 0, v44                                   ; 20585880
	v_mad_f32 v39, v17, -v43, -v39                              ; d5410027 c49e5711
	v_mad_f32 v47, v16, -v43, -v47                              ; d541002f c4be5710
	v_mad_f32 v43, v18, -v43, -v40                              ; d541002b c4a25712
	v_mul_f32_e32 v8, v8, v44                                   ; 10105908
	v_mul_f32_e32 v45, v45, v44                                 ; 105a592d
	v_mul_f32_e32 v46, v46, v44                                 ; 105c592e
	v_mul_f32_e32 v43, v43, v30                                 ; 10563d2b
	v_sub_f32_e32 v12, s88, v12                                 ; 08181858
	v_sub_f32_e32 v13, s89, v13                                 ; 081a1a59
	v_mac_f32_e32 v27, v8, v41                                  ; 3e365308
	v_sub_f32_e32 v14, s90, v14                                 ; 081c1c5a
	v_mac_f32_e32 v25, v45, v41                                 ; 3e32532d
	v_mac_f32_e32 v26, v46, v41                                 ; 3e34532e
	v_mac_f32_e32 v43, v39, v29                                 ; 3e563b27
	v_mul_f32_e32 v31, v13, v13                                 ; 103e1b0d
	v_mac_f32_e32 v43, v47, v28                                 ; 3e56392f
	v_mac_f32_e32 v31, v14, v14                                 ; 3e3e1d0e
	v_max_f32_e32 v43, 0, v43                                   ; 20565680
	v_mac_f32_e32 v31, v12, v12                                 ; 3e3e190c
	v_mul_f32_e32 v43, v43, v43                                 ; 1056572b
	v_rsq_f32_e32 v32, v31                                      ; 7e405d1f
	v_add_f32_e32 v31, 1.0, v31                                 ; 063e3ef2
	v_mul_f32_e32 v43, v43, v43                                 ; 1056572b
	v_mul_f32_e32 v20, s92, v20                                 ; 1028285c
	v_mul_f32_e32 v21, s93, v21                                 ; 102a2a5d
	v_mul_f32_e32 v22, s94, v22                                 ; 102c2c5e
	v_rcp_f32_e32 v31, v31                                      ; 7e3e551f
	v_mul_f32_e32 v43, v43, v43                                 ; 1056572b
	v_mul_f32_e32 v12, v12, v32                                 ; 1018410c
	v_mul_f32_e32 v13, v13, v32                                 ; 101a410d
	v_mul_f32_e32 v14, v14, v32                                 ; 101c410e
	v_mul_f32_e32 v24, v24, v43                                 ; 10305718
	v_mul_f32_e32 v15, v15, v43                                 ; 101e570f
	v_mul_f32_e32 v19, v19, v43                                 ; 10265713
	v_mul_f32_e32 v33, v18, v14                                 ; 10421d12
	v_mul_f32_e32 v31, s95, v31                                 ; 103e3e5f
	v_mac_f32_e32 v27, v24, v41                                 ; 3e365318
	v_mac_f32_e32 v25, v15, v41                                 ; 3e32530f
	v_mac_f32_e32 v26, v19, v41                                 ; 3e345313
	v_mul_f32_e32 v35, s92, v23                                 ; 10462e5c
	v_mul_f32_e32 v36, s93, v23                                 ; 10482e5d
	v_mad_f32 v34, v17, v13, v33                                ; d5410022 04861b11
	v_mad_f32 v33, v17, -v13, -v33                              ; d5410021 c4861b11
	v_mul_f32_e32 v23, s94, v23                                 ; 102e2e5e
	v_mac_f32_e32 v34, v16, v12                                 ; 3e441910
	v_mad_f32 v33, v16, -v12, v33 mul:2                         ; d5410021 4c861910
	v_max_f32_e32 v34, 0, v34                                   ; 20444480
	v_mad_f32 v16, v16, -v33, -v12                              ; d5410010 c4324310
	v_mad_f32 v17, v17, -v33, -v13                              ; d5410011 c4364311
	v_mad_f32 v18, v18, -v33, -v14                              ; d5410012 c43a4312
	v_mul_f32_e32 v21, v21, v34                                 ; 102a4515
	v_mul_f32_e32 v20, v20, v34                                 ; 10284514
	v_mul_f32_e32 v22, v22, v34                                 ; 102c4516
	v_mul_f32_e32 v18, v18, v30                                 ; 10243d12
	v_mac_f32_e32 v26, v21, v31                                 ; 3e343f15
	v_mac_f32_e32 v25, v20, v31                                 ; 3e323f14
	v_mac_f32_e32 v27, v22, v31                                 ; 3e363f16
	v_mac_f32_e32 v18, v17, v29                                 ; 3e243b11
	v_mac_f32_e32 v18, v16, v28                                 ; 3e243910
	v_max_f32_e32 v18, 0, v18                                   ; 20242480
	v_mul_f32_e32 v18, v18, v18                                 ; 10242512
	(then repeated 2 times)
	v_mul_f32_e32 v23, v23, v18                                 ; 102e2517
	v_mul_f32_e32 v35, v35, v18                                 ; 10462523
	v_mul_f32_e32 v36, v36, v18                                 ; 10482524
	v_mac_f32_e32 v27, v23, v31                                 ; 3e363f17
	v_mac_f32_e32 v25, v35, v31                                 ; 3e323f23
	v_mac_f32_e32 v26, v36, v31                                 ; 3e343f24
	v_add_f32_e32 v5, v5, v27                                   ; 060a3705
	v_add_f32_e32 v7, v7, v25                                   ; 060e3307
	v_add_f32_e32 v6, v6, v26                                   ; 060c3506
	s_cbranch_scc0 BB15                                         ; bf84fe9b
BB19:
	v_madmk_f32 v11, v11, 0x3e19999a, v5                        ; 40160b0b 3e19999a
	v_madmk_f32 v9, v9, 0x3e19999a, v7                          ; 40120f09 3e19999a
	v_madmk_f32 v10, v10, 0x3e19999a, v6                        ; 40140d0a 3e19999a
	v_mul_f32_e32 v6, 0x3e000000, v11                           ; 100c16ff 3e000000
	v_mul_f32_e32 v4, 0x3e000000, v9                            ; 100812ff 3e000000
	v_mul_f32_e32 v5, 0x3e000000, v10                           ; 100a14ff 3e000000
BB20:
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e64 v6, v6, 1.0                         ; d52f0006 0001e506
	v_cvt_pkrtz_f16_f32_e32 v4, v4, v5                          ; 5e080b04
	exp mrt0 v4, v4, v6, v6 done compr vm                       ; f8001c0f 80800604
	s_endpgm                                                    ; bf810000
