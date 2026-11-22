# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v9, v0, attr2.w                         ; c8240b00
	v_interp_p1_f32_e32 v2, v0, attr1.w                         ; c8080700
	v_interp_p1_f32_e32 v4, v0, attr2.x                         ; c8100800
	v_interp_p1_f32_e32 v5, v0, attr1.z                         ; c8140600
	v_interp_p1_f32_e32 v8, v0, attr0.z                         ; c8200200
	v_interp_p1_f32_e32 v11, v0, attr0.y                        ; c82c0100
	v_interp_p1_f32_e32 v12, v0, attr2.z                        ; c8300a00
	v_interp_p2_f32_e32 v9, v1, attr2.w                         ; c8250b01
	v_interp_p2_f32_e32 v2, v1, attr1.w                         ; c8090701
	v_interp_p1_f32_e32 v14, v0, attr0.x                        ; c8380000
	v_interp_p2_f32_e32 v4, v1, attr2.x                         ; c8110801
	v_interp_p2_f32_e32 v5, v1, attr1.z                         ; c8150601
	v_interp_p1_f32_e32 v15, v0, attr2.y                        ; c83c0900
	v_interp_p2_f32_e32 v8, v1, attr0.z                         ; c8210201
	v_interp_p2_f32_e32 v11, v1, attr0.y                        ; c82d0101
	v_interp_p2_f32_e32 v12, v1, attr2.z                        ; c8310a01
	v_interp_p2_f32_e32 v14, v1, attr0.x                        ; c8390001
	v_interp_p2_f32_e32 v15, v1, attr2.y                        ; c83d0901
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v10, v9, v8                                   ; 10141109
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mad_f32 v13, v12, -v11, -v10                              ; d541000d c42a170c
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_mad_f32 v13, v15, -v14, v13 mul:2                         ; d541000d 4c361d0f
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mad_f32 v16, v14, -v13, -v15                              ; d5410010 c43e1b0e
	v_mad_f32 v17, v11, -v13, -v12                              ; d5410011 c4321b0b
	v_mad_f32 v13, v8, -v13, -v9                                ; d541000d c4261b08
	v_add_f32_e32 v9, v9, v4                                    ; 06120909
	v_mul_f32_e32 v18, v17, v17                                 ; 10242311
	v_mul_f32_e32 v6, v5, v3                                    ; 100c0705
	v_add_f32_e32 v5, v15, v5                                   ; 060a0b0f
	v_mul_f32_e32 v7, v2, v3                                    ; 100e0702
	v_add_f32_e32 v2, v12, v2                                   ; 0604050c
	v_mul_f32_e32 v3, v4, v3                                    ; 10060704
	v_mac_f32_e32 v18, v13, v13                                 ; 3e241b0d
	v_mac_f32_e32 v10, v12, v11                                 ; 3e14170c
	v_mul_f32_e32 v19, v2, v2                                   ; 10260502
	v_mac_f32_e32 v18, v16, v16                                 ; 3e242110
	v_mac_f32_e32 v10, v15, v14                                 ; 3e141d0f
	v_mac_f32_e32 v19, v9, v9                                   ; 3e261309
	v_rsq_f32_e32 v18, v18                                      ; 7e245d12
	v_cmp_lt_f32_e32 vcc, 0, v10                                ; 7c021480
	v_mac_f32_e32 v19, v5, v5                                   ; 3e260b05
	v_add_f32_e64 v20, v10, 0 clamp                             ; d5038014 0001010a
	v_rsq_f32_e32 v19, v19                                      ; 7e265d13
	v_add_f32_e32 v20, 0x3dcccccd, v20                          ; 062828ff 3dcccccd
	v_mul_f32_e32 v16, v16, v18                                 ; 10202510
	v_mul_f32_e32 v17, v17, v18                                 ; 10222511
	v_mul_f32_e32 v13, v13, v18                                 ; 101a250d
	v_interp_p1_f32_e32 v21, v0, attr0.w                        ; c8540300
	v_interp_p2_f32_e32 v21, v1, attr0.w                        ; c8550301
	v_max_f32_e64 v10, 0, v10 div:2                             ; d510000a 18021480
	v_mul_f32_e32 v3, v3, v13                                   ; 10061b03
	v_mul_f32_e32 v5, v5, v19                                   ; 100a2705
	v_mul_f32_e32 v9, v9, v19                                   ; 10122709
	v_mul_f32_e32 v2, v2, v19                                   ; 10042702
	v_interp_p1_f32_e32 v23, v0, attr1.x                        ; c85c0400
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v23, v1, attr1.x                        ; c85d0401
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_add_f32_e32 v22, 0x3e4ccccd, v10                          ; 062c14ff 3e4ccccd
	v_mad_f32 v7, v7, -v17, -v3                                 ; d5410007 c40e2307
	v_mul_f32_e32 v9, v9, v8                                    ; 10121109
	v_add_f32_e32 v10, 1.0, v10                                 ; 061414f2
	s_mov_b32 s0, 0x40100000                                    ; be8003ff 40100000
	v_mad_f32 v6, v6, -v16, v7                                  ; d5410006 441e2106
	v_mac_f32_e32 v9, v2, v11                                   ; 3e121702
	v_max_f32_e32 v6, 0, v6                                     ; 200c0c80
	v_mad_f32 v5, v5, v14, v9 clamp                             ; d5418005 04261d05
	v_mul_f32_e32 v6, v6, v6                                    ; 100c0d06
	v_log_f32_e32 v5, v5                                        ; 7e0a4f05
	v_mul_f32_e32 v1, 0x3ec00000, v6                            ; 10020cff 3ec00000
	v_madmk_f32 v6, v6, 0x3f400000, v10                         ; 400c1506 3f400000
	v_mad_f32 v23, v22, v23, v1                                 ; d5410017 04062f16
	v_mad_f32 v21, v22, v21, v1                                 ; d5410015 04062b16
	v_mac_f32_e32 v1, v22, v0                                   ; 3e020116
	v_mov_b32_e32 v7, 0x3dcccccd                                ; 7e0e02ff 3dcccccd
	v_mul_f32_e32 v5, 0x42800000, v5                            ; 100a0aff 42800000
	v_mul_f32_e32 v3, s0, v23                                   ; 10062e00
	v_mul_f32_e32 v2, s0, v21                                   ; 10042a00
	v_mul_f32_e32 v4, s0, v1                                    ; 10080200
	v_exp_f32_e32 v5, v5                                        ; 7e0a4b05
	v_cndmask_b32_e32 v5, 0, v5, vcc                            ; 020a0a80
	v_add_f32_e32 v20, v20, v5                                  ; 06280b14
	v_mul_f32_e32 v5, s0, v6                                    ; 100a0c00
	v_cmp_lt_f32_e32 vcc, 0x3f733333, v20                       ; 7c0228ff 3f733333
	v_cndmask_b32_e32 v1, v1, v4, vcc                           ; 02020901
	v_cndmask_b32_e32 v21, v21, v2, vcc                         ; 022a0515
	v_cndmask_b32_e32 v23, v23, v3, vcc                         ; 022e0717
	v_cndmask_b32_e32 v6, v6, v5, vcc                           ; 020c0b06
	v_cmp_gt_f32_e32 vcc, 0x3e19999a, v20                       ; 7c0828ff 3e19999a
	v_cndmask_b32_e32 v1, v1, v7, vcc                           ; 02020f01
	v_cndmask_b32_e32 v23, v23, v7, vcc                         ; 022e0f17
	v_cndmask_b32_e32 v6, v6, v7, vcc                           ; 020c0f06
	v_cndmask_b32_e32 v21, v21, v7, vcc                         ; 022a0f15
	v_cvt_pkrtz_f16_f32_e32 v1, v1, v6                          ; 5e020d01
	v_cvt_pkrtz_f16_f32_e32 v21, v21, v23                       ; 5e2a2f15
	exp mrt0 v21, v21, v1, v1 done compr vm                     ; f8001c0f 80800115
	s_endpgm                                                    ; bf810000
