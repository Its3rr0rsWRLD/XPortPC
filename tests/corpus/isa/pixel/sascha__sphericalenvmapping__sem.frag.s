# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v7, v0, attr1.x                         ; c81c0400
	v_interp_p1_f32_e32 v8, v0, attr0.y                         ; c8200100
	v_interp_p1_f32_e32 v2, v0, attr0.w                         ; c8080300
	v_interp_p1_f32_e32 v3, v0, attr1.z                         ; c80c0600
	v_interp_p1_f32_e32 v5, v0, attr1.y                         ; c8140500
	v_interp_p1_f32_e32 v6, v0, attr0.z                         ; c8180200
	v_interp_p2_f32_e32 v7, v1, attr1.x                         ; c81d0401
	v_interp_p2_f32_e32 v8, v1, attr0.y                         ; c8210101
	v_interp_p2_f32_e32 v2, v1, attr0.w                         ; c8090301
	v_interp_p2_f32_e32 v3, v1, attr1.z                         ; c80d0601
	v_interp_p2_f32_e32 v5, v1, attr1.y                         ; c8150501
	v_interp_mov_f32_e32 v13, p0, attr1.w                       ; c8360702
	v_interp_p2_f32_e32 v6, v1, attr0.z                         ; c8190201
	v_mul_f32_e32 v4, v2, v3                                    ; 10080702
	v_rndne_f32_e32 v12, v13                                    ; 7e18470d
	v_mac_f32_e32 v4, v6, v5                                    ; 3e080b06
	v_mad_f32 v4, v8, v7, v4 mul:2                              ; d5410004 0c120f08
	v_mad_f32 v5, v5, -v4, v6                                   ; d5410005 441a0905
	v_mad_f32 v3, v3, -v4, v2                                   ; d5410003 440a0903
	v_mad_f32 v7, v7, -v4, v8                                   ; d5410007 44220907
	v_mul_f32_e32 v9, v5, v5                                    ; 10120b05
	v_add_f32_e32 v3, 1.0, v3                                   ; 060606f2
	v_mac_f32_e32 v9, v3, v3                                    ; 3e120703
	v_mac_f32_e32 v9, v7, v7                                    ; 3e120f07
	v_sqrt_f32_e64 v9, v9 mul:2                                 ; d5b30009 08000109
	v_rcp_f32_e32 v9, v9                                        ; 7e125509
	v_mad_f32 v10, v7, v9, 0.5                                  ; d541000a 03c21307
	v_mad_f32 v11, v5, v9, 0.5                                  ; d541000b 03c21305
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[14:16], v[10:12], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800728 00220e0a
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_add_f32_e64 v0, v0, 0 clamp                               ; d5038000 00010100
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v17, v14, v0, neg(0) op_sel_hi:[0,0,1]      ; cc214011 8202010e
	v_fma_mixhi_f16 v17, v15, v0, neg(0) op_sel_hi:[0,0,1]      ; cc224011 8202010f
	v_mul_f32_e32 v16, v16, v0                                  ; 10200110
	v_cvt_pkrtz_f16_f32_e64 v16, v16, 1.0                       ; d52f0010 0001e510
	exp mrt0 v17, v17, v16, v16 done compr vm                   ; f8001c0f 80801011
	s_endpgm                                                    ; bf810000
