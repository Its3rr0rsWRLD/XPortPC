# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx4 s[4:7], s[2:3], 0x10                         ; f4080101 fa000010
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_mov_f32_e32 v2, p0, attr1.x                        ; c80a0402
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x3                                                ; bfa10003
	buffer_load_dwordx4 v[4:7], v2, s[4:7], 0 offen offset:16   ; e0381010 80010402
	buffer_load_dwordx4 v[8:11], v2, s[4:7], 0 offen            ; e0381000 80010802
	buffer_load_dwordx4 v[12:15], v2, s[4:7], 0 offen offset:48 ; e0381030 80010c02
	buffer_load_dwordx4 v[16:19], v2, s[4:7], 0 offen offset:32 ; e0381020 80011002
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_sub_f32_e32 v6, v6, v10                                   ; 080c1506
	v_sub_f32_e32 v7, v7, v11                                   ; 080e1707
	v_sub_f32_e32 v4, v4, v8                                    ; 08081104
	v_sub_f32_e32 v5, v5, v9                                    ; 080a1305
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_sub_f32_e32 v12, v12, v16                                 ; 0818210c
	v_sub_f32_e32 v13, v13, v17                                 ; 081a230d
	v_sub_f32_e32 v14, v14, v18                                 ; 081c250e
	v_sub_f32_e32 v15, v15, v19                                 ; 081e270f
	v_mac_f32_e32 v10, v3, v6                                   ; 3e140d03
	v_mac_f32_e32 v11, v3, v7                                   ; 3e160f03
	v_mac_f32_e32 v8, v3, v4                                    ; 3e100903
	v_mac_f32_e32 v9, v3, v5                                    ; 3e120b03
	v_mac_f32_e32 v16, v3, v12                                  ; 3e201903
	v_mac_f32_e32 v17, v3, v13                                  ; 3e221b03
	v_mac_f32_e32 v18, v3, v14                                  ; 3e241d03
	v_mac_f32_e32 v19, v3, v15                                  ; 3e261f03
	v_sub_f32_e32 v16, v16, v8                                  ; 08201110
	v_sub_f32_e32 v17, v17, v9                                  ; 08221311
	v_sub_f32_e32 v18, v18, v10                                 ; 08241512
	v_sub_f32_e32 v19, v19, v11                                 ; 08261713
	v_fma_mixlo_f16 v4, v0, v16, v8                             ; cc210004 04222100
	v_fma_mixhi_f16 v4, v0, v17, v9                             ; cc220004 04262300
	v_fma_mixlo_f16 v5, v0, v18, v10                            ; cc210005 042a2500
	v_fma_mixhi_f16 v5, v0, v19, v11                            ; cc220005 042e2700
	exp mrt0 v4, v4, v5, v5 done compr vm                       ; f8001c0f 80800504
	s_endpgm                                                    ; bf810000
