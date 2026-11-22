# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x3                                                ; bfa10003
	s_load_dwordx8 s[8:15], s[2:3], 0x80                        ; f40c0201 fa000080
	s_load_dwordx4 s[4:7], s[2:3], 0xd0                         ; f4080101 fa0000d0
	s_load_dwordx8 s[16:23], s[2:3], 0x20                       ; f40c0401 fa000020
	s_load_dwordx4 s[24:27], s[2:3], null                       ; f4080601 fa000000
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v3, v0, attr0.y                         ; c80c0100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v3, v1, attr0.y                         ; c80d0101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:6], [v0, v3], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220400 00000003
	v_lshrrev_b32_e32 v9, 16, v2                                ; 2c120490
	v_bfe_u32 v0, v2, 0, 16                                     ; d5480000 02410102
	v_add_nc_u32_e32 v1, 2, v9                                  ; 4a021282
	v_add_nc_u32_e32 v10, 2, v0                                 ; 4a140082
	v_add_nc_u32_e32 v8, -2, v0                                 ; 4a1000c2
	s_clause 0x2                                                ; bfa10002
	image_load v7, v2, s[16:23] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm a16 ; f0001108 40040702
	image_load v8, v[8:9], s[16:23] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f0001108 00040808
	image_load v1, v[0:1], s[16:23] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f0001108 00040100
	image_load v10, [v10, v9], s[16:23] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f000110a 00040a0a 00000009
	v_add_nc_u32_e32 v9, -2, v9                                 ; 4a1212c2
	image_load v0, [v0, v9], s[16:23] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm ; f000110a 00040000 00000009
	s_buffer_load_dwordx2 s[0:1], s[24:27], null                ; f424000c fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_sub_f32_e64 v12, s0, s1                                   ; d504000c 00000200
	v_mul_f32_e64 v11, s0, s1                                   ; d508000b 00000200
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mad_f32 v7, v7, v12, s1                                   ; d5410007 00061907
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mad_f32 v8, v8, v12, s1                                   ; d5410008 00061908
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mad_f32 v1, v1, v12, s1                                   ; d5410001 00061901
	v_rcp_f32_e32 v7, v7                                        ; 7e0e5507
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mad_f32 v10, v10, v12, s1                                 ; d541000a 0006190a
	v_rcp_f32_e32 v8, v8                                        ; 7e105508
	v_rcp_f32_e32 v1, v1                                        ; 7e025501
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v0, v0, v12, s1                                   ; d5410000 00061900
	v_rcp_f32_e32 v10, v10                                      ; 7e14550a
	v_mul_f32_e32 v7, v11, v7                                   ; 100e0f0b
	v_rcp_f32_e32 v0, v0                                        ; 7e005500
	v_mad_f32 v1, v11, -v1, v7                                  ; d5410001 441e030b
	v_add_f32_e32 v1, v7, v1                                    ; 06020307
	v_mad_f32 v8, v11, -v8, v1                                  ; d5410008 4406110b
	v_add_f32_e32 v8, v7, v8                                    ; 06101107
	v_mad_f32 v10, v11, -v10, v8                                ; d541000a 4422150b
	v_add_f32_e32 v7, v7, v10                                   ; 060e1507
	v_mad_f32 v11, v11, -v0, v7 clamp                           ; d541800b 441e010b
	v_mad_f32 v6, v6, -v11, v6                                  ; d5410006 441a1706
	v_fma_mixlo_f16 v13, v4, -v11, v4                           ; cc21000d 44121704
	v_fma_mixhi_f16 v13, v5, -v11, v5                           ; cc22000d 44161705
	v_cvt_pkrtz_f16_f32_e64 v6, v6, 0                           ; d52f0006 00010106
	exp mrt0 v13, v13, v6, v6 done compr vm                     ; f8001c0f 8080060d
	s_endpgm                                                    ; bf810000
