# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx8 s[8:15], s[2:3], 0x80                        ; f40c0201 fa000080
	s_load_dwordx4 s[4:7], s[2:3], 0xd0                         ; f4080101 fa0000d0
	s_load_dwordx16 s[16:31], s[2:3], 0x20                      ; f4100401 fa000020
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v3, v0, attr0.y                         ; c80c0100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v3, v1, attr0.y                         ; c80d0101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:6], [v0, v3], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220400 00000003
	image_load v7, v2, s[24:31] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm a16 ; f0001108 40060702
	v_bfe_u32 v0, v2, 0, 16                                     ; d5480000 02410102
	v_lshrrev_b32_e32 v3, 16, v2                                ; 2c060490
	v_add_nc_u32_e32 v2, -2, v0                                 ; 4a0400c2
	v_add_nc_u32_e32 v8, 2, v0                                  ; 4a100082
	v_add_nc_u32_e32 v1, 2, v3                                  ; 4a020682
	s_clause 0x1                                                ; bfa10001
	image_load v9, v[2:3], s[24:31] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f0001108 00060902
	image_load v10, v[0:1], s[24:31] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f0001108 00060a00
	image_load v11, [v8, v3], s[24:31] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f000110a 00060b08 00000003
	v_mov_b32_e32 v12, 0x76543210                               ; 7e1802ff 76543210
	s_mov_b32 s1, s25                                           ; be810319
	v_cmp_ne_u32_e64 vcc, 0, s1                                 ; d4c5006a 00000280
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_cndmask_b32_e32 v7, v12, v7, vcc                          ; 020e0f0c
	v_and_b32_e32 v7, 7, v7                                     ; 360e0e87
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_cndmask_b32_e32 v9, v12, v9, vcc                          ; 0212130c
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_cndmask_b32_e32 v10, v12, v10, vcc                        ; 0214150c
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v11, v12, v11, vcc                        ; 0216170c
	v_and_b32_e32 v9, 7, v9                                     ; 36121287
	v_and_b32_e32 v10, 7, v10                                   ; 36141487
	v_and_b32_e32 v11, 7, v11                                   ; 36161687
	image_load v7, [v0, v3, v7], s[16:23] dmask:0x1 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001132 00040700 00000703
	image_load v2, [v2, v3, v9], s[16:23] dmask:0x1 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001132 00040202 00000903
	image_load v1, [v0, v1, v10], s[16:23] dmask:0x1 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001132 00040100 00000a01
	image_load v8, [v8, v3, v11], s[16:23] dmask:0x1 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001132 00040808 00000b03
	v_add_nc_u32_e32 v3, -2, v3                                 ; 4a0606c2
	image_load v13, [v0, v3], s[24:31] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f000110a 00060d00 00000003
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v12, v12, v13, vcc                        ; 02181b0c
	v_and_b32_e32 v12, 7, v12                                   ; 36181887
	image_load v0, [v0, v3, v12], s[16:23] dmask:0x1 dim:SQ_RSRC_IMG_2D_MSAA unorm ; f0001132 00040000 00000c03
	s_load_dwordx4 s[0:3], s[2:3], null                         ; f4080001 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx2 s[0:1], s[0:3], null                  ; f4240000 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_sub_f32_e64 v15, s0, s1                                   ; d504000f 00000200
	v_mul_f32_e64 v14, s0, s1                                   ; d508000e 00000200
	v_mad_f32 v1, v1, v15, s1                                   ; d5410001 00061f01
	v_mad_f32 v8, v8, v15, s1                                   ; d5410008 00061f08
	v_mad_f32 v7, v7, v15, s1                                   ; d5410007 00061f07
	v_mad_f32 v2, v2, v15, s1                                   ; d5410002 00061f02
	v_rcp_f32_e32 v1, v1                                        ; 7e025501
	v_rcp_f32_e32 v8, v8                                        ; 7e105508
	v_rcp_f32_e32 v7, v7                                        ; 7e0e5507
	v_rcp_f32_e32 v2, v2                                        ; 7e045502
	v_mul_f32_e32 v7, v14, v7                                   ; 100e0f0e
	v_mad_f32 v1, v14, -v1, v7                                  ; d5410001 441e030e
	v_add_f32_e32 v1, v7, v1                                    ; 06020307
	v_mad_f32 v2, v14, -v2, v1                                  ; d5410002 4406050e
	v_add_f32_e32 v2, v7, v2                                    ; 06040507
	v_mad_f32 v8, v14, -v8, v2                                  ; d5410008 440a110e
	v_add_f32_e32 v7, v7, v8                                    ; 060e1107
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v0, v0, v15, s1                                   ; d5410000 00061f00
	v_rcp_f32_e32 v0, v0                                        ; 7e005500
	v_mad_f32 v14, v14, -v0, v7 clamp                           ; d541800e 441e010e
	v_mad_f32 v6, v6, -v14, v6                                  ; d5410006 441a1d06
	v_fma_mixlo_f16 v16, v4, -v14, v4                           ; cc210010 44121d04
	v_fma_mixhi_f16 v16, v5, -v14, v5                           ; cc220010 44161d05
	v_cvt_pkrtz_f16_f32_e64 v6, v6, 0                           ; d52f0006 00010106
	exp mrt0 v16, v16, v6, v6 done compr vm                     ; f8001c0f 80800610
	s_endpgm                                                    ; bf810000
