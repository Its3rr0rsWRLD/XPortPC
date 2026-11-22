; Source-built MASM fixture exercising all 18 register-domain AVX2 forms
; (plus mandatory m128 source for vbroadcasti128) across XMM and YMM widths.
; Every export uses the Windows x64 leaf ABI:
;   RCX = const void* input_a (16 or 32 bytes)
;   RDX = const void* input_b (16 or 32 bytes; also used to pre-seed YMM0 on XMM writes)
;   R8  = void*       output  (32 bytes)
.code

; --- 128-bit lane broadcast and permute ---

op_broadcasti128 PROC FRAME
    .endprolog
    vbroadcasti128 ymm0, XMMWORD PTR [rcx]
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_broadcasti128 ENDP

op_extracti128_lo PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vextracti128 xmm0, ymm1, 0FEh
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_extracti128_lo ENDP

op_extracti128_hi PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vextracti128 xmm0, ymm1, 0FFh
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_extracti128_hi ENDP

op_inserti128_lo PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu xmm2, XMMWORD PTR [rdx]
    vinserti128 ymm0, ymm1, xmm2, 0FEh
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_inserti128_lo ENDP

op_inserti128_hi PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu xmm2, XMMWORD PTR [rdx]
    vinserti128 ymm0, ymm1, xmm2, 0FFh
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_inserti128_hi ENDP

op_perm2i128_mix PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
IFDEF ALTER_IMM
    vperm2i128 ymm0, ymm1, ymm2, 31h
ELSE
    vperm2i128 ymm0, ymm1, ymm2, 20h
ENDIF
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_perm2i128_mix ENDP

op_perm2i128_swap PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vperm2i128 ymm0, ymm1, ymm2, 03h
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_perm2i128_swap ENDP

op_perm2i128_zero_lo PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vperm2i128 ymm0, ymm1, ymm2, 28h
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_perm2i128_zero_lo ENDP

op_perm2i128_zero_hi PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vperm2i128 ymm0, ymm1, ymm2, 81h
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_perm2i128_zero_hi ENDP

op_perm2i128_zero_both PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vperm2i128 ymm0, ymm1, ymm2, 88h
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_perm2i128_zero_both ENDP

op_perm2i128_ignored PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vperm2i128 ymm0, ymm1, ymm2, 45h
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_perm2i128_ignored ENDP

; --- Element broadcasts (XMM and YMM) ---

op_pbroadcastb_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vpbroadcastb xmm0, xmm1
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pbroadcastb_xmm ENDP

op_pbroadcastb_ymm PROC FRAME
    .endprolog
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vpbroadcastb ymm0, xmm1
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pbroadcastb_ymm ENDP

op_pbroadcastw_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vpbroadcastw xmm0, xmm1
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pbroadcastw_xmm ENDP

op_pbroadcastw_ymm PROC FRAME
    .endprolog
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vpbroadcastw ymm0, xmm1
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pbroadcastw_ymm ENDP

op_pbroadcastd_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vpbroadcastd xmm0, xmm1
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pbroadcastd_xmm ENDP

op_pbroadcastd_ymm PROC FRAME
    .endprolog
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vpbroadcastd ymm0, xmm1
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pbroadcastd_ymm ENDP

op_pbroadcastq_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vpbroadcastq xmm0, xmm1
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pbroadcastq_xmm ENDP

op_pbroadcastq_ymm PROC FRAME
    .endprolog
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vpbroadcastq ymm0, xmm1
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pbroadcastq_ymm ENDP

; --- Cross-lane permutes ---

op_permd PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vpermd ymm0, ymm1, ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_permd ENDP

op_permps PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vpermps ymm0, ymm1, ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_permps ENDP

op_permq PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
IFDEF ALTER_IMM
    vpermq ymm0, ymm1, 4Eh
ELSE
    vpermq ymm0, ymm1, 1Bh
ENDIF
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_permq ENDP

op_permq_dup PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vpermq ymm0, ymm1, 0B1h
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_permq_dup ENDP

op_permpd PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vpermpd ymm0, ymm1, 93h
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_permpd ENDP

; --- Blend (XMM and YMM) ---

op_pblendd_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rcx]
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vmovdqu xmm2, XMMWORD PTR [rdx]
    vpblendd xmm0, xmm1, xmm2, 0FAh
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pblendd_xmm ENDP

op_pblendd_ymm PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
IFDEF ALTER_IMM
    vpblendd ymm0, ymm1, ymm2, 55h
ELSE
    vpblendd ymm0, ymm1, ymm2, 0AAh
ENDIF
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pblendd_ymm ENDP

op_pblendd_ymm_all PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vpblendd ymm0, ymm1, ymm2, 0FFh
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pblendd_ymm_all ENDP

op_pblendd_ymm_none PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vpblendd ymm0, ymm1, ymm2, 00h
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pblendd_ymm_none ENDP

; --- Variable shifts (XMM and YMM) ---

op_psllvd_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rcx]
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vmovdqu xmm2, XMMWORD PTR [rdx]
    vpsllvd xmm0, xmm1, xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_psllvd_xmm ENDP

op_psllvd_ymm PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vpsllvd ymm0, ymm1, ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_psllvd_ymm ENDP

op_psllvq_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rcx]
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vmovdqu xmm2, XMMWORD PTR [rdx]
    vpsllvq xmm0, xmm1, xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_psllvq_xmm ENDP

op_psllvq_ymm PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vpsllvq ymm0, ymm1, ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_psllvq_ymm ENDP

op_psravd_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rcx]
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vmovdqu xmm2, XMMWORD PTR [rdx]
    vpsravd xmm0, xmm1, xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_psravd_xmm ENDP

op_psravd_ymm PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vpsravd ymm0, ymm1, ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_psravd_ymm ENDP

op_psrlvd_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rcx]
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vmovdqu xmm2, XMMWORD PTR [rdx]
    vpsrlvd xmm0, xmm1, xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_psrlvd_xmm ENDP

op_psrlvd_ymm PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vpsrlvd ymm0, ymm1, ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_psrlvd_ymm ENDP

op_psrlvq_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rcx]
    vmovdqu xmm1, XMMWORD PTR [rcx]
    vmovdqu xmm2, XMMWORD PTR [rdx]
    vpsrlvq xmm0, xmm1, xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_psrlvq_xmm ENDP

op_psrlvq_ymm PROC FRAME
    .endprolog
    vmovdqu ymm1, YMMWORD PTR [rcx]
    vmovdqu ymm2, YMMWORD PTR [rdx]
    vpsrlvq ymm0, ymm1, ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_psrlvq_ymm ENDP

; --- VZEROUPPER upper-lane clearing and multi-instruction pipeline ---

op_zeroupper PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rcx]
    vzeroupper
    vmovdqu YMMWORD PTR [r8], ymm0
    ret
op_zeroupper ENDP

; Chained multi-register sequence exercising register aliasing and mixed widths.
op_pipeline PROC FRAME
    .endprolog
    vbroadcasti128 ymm0, XMMWORD PTR [rcx]
    vmovdqu ymm1, YMMWORD PTR [rdx]
    vpbroadcastd ymm2, xmm1
    vperm2i128 ymm3, ymm0, ymm1, 21h
    vpermd ymm4, ymm1, ymm3
    vpblendd ymm5, ymm4, ymm2, 5Ah
    vpsravd ymm5, ymm5, ymm1
    vextracti128 xmm3, ymm5, 1
    vinserti128 ymm5, ymm5, xmm3, 0
    vpermq ymm5, ymm5, 0D8h
    vmovdqu ymm0, ymm5
    vmovdqu YMMWORD PTR [r8], ymm0
    vzeroupper
    ret
op_pipeline ENDP

; --- Memory-domain AVX2: indexed gathers (VSIB) ---
; ABI for gather exports:
;   RCX = const void* base (inside caller-owned guarded data buffer)
;   RDX = const void* ctrl (96 bytes: [0..31]=init dest, [32..63]=vindex, [64..95]=mask)
;   R8  = void*       out  (64 bytes: [0..31]=post-gather ymm0, [32..63]=post-gather ymm2 mask)

op_gatherdps_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vgatherdps xmm0, DWORD PTR [rcx + xmm1*4], xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_gatherdps_xmm ENDP

op_gatherdps_ymm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
IFDEF ALTER_IMM
    vgatherdps ymm0, DWORD PTR [rcx + ymm1*4 + 16], ymm2
ELSE
    vgatherdps ymm0, DWORD PTR [rcx + ymm1*4], ymm2
ENDIF
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_gatherdps_ymm ENDP

op_gatherdps_ymm_scale1_disp PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vgatherdps ymm0, DWORD PTR [rcx + ymm1*1 - 16], ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_gatherdps_ymm_scale1_disp ENDP

op_gatherdpd_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vgatherdpd xmm0, QWORD PTR [rcx + xmm1*8], xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_gatherdpd_xmm ENDP

op_gatherdpd_ymm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vgatherdpd ymm0, QWORD PTR [rcx + xmm1*8 + 16], ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_gatherdpd_ymm ENDP

op_gatherqps_xmm_vm64x PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vgatherqps xmm0, DWORD PTR [rcx + xmm1*4], xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_gatherqps_xmm_vm64x ENDP

op_gatherqps_xmm_vm64y PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vgatherqps xmm0, DWORD PTR [rcx + ymm1*4], xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_gatherqps_xmm_vm64y ENDP

op_gatherqpd_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vgatherqpd xmm0, QWORD PTR [rcx + xmm1*8], xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_gatherqpd_xmm ENDP

op_gatherqpd_ymm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vgatherqpd ymm0, QWORD PTR [rcx + ymm1*8 - 24], ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_gatherqpd_ymm ENDP

op_pgatherdd_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vpgatherdd xmm0, DWORD PTR [rcx + xmm1*2 + 8], xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_pgatherdd_xmm ENDP

op_pgatherdd_ymm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vpgatherdd ymm0, DWORD PTR [rcx + ymm1*4], ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_pgatherdd_ymm ENDP

op_pgatherdq_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vpgatherdq xmm0, QWORD PTR [rcx + xmm1*1], xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_pgatherdq_xmm ENDP

op_pgatherdq_ymm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vpgatherdq ymm0, QWORD PTR [rcx + xmm1*8], ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_pgatherdq_ymm ENDP

op_pgatherqd_xmm_vm64x PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vpgatherqd xmm0, DWORD PTR [rcx + xmm1*1 - 8], xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_pgatherqd_xmm_vm64x ENDP

op_pgatherqd_xmm_vm64y PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vpgatherqd xmm0, DWORD PTR [rcx + ymm1*4 + 12], xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_pgatherqd_xmm_vm64y ENDP

op_pgatherqq_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vpgatherqq xmm0, QWORD PTR [rcx + xmm1*8], xmm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_pgatherqq_xmm ENDP

op_pgatherqq_ymm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vmovdqu ymm2, YMMWORD PTR [rdx + 64]
    vpgatherqq ymm0, QWORD PTR [rcx + ymm1*8], ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_pgatherqq_ymm ENDP

; --- Memory-domain AVX2: masked loads and stores ---
; ABI for vpmaskmov load exports:
;   RCX = const void* src_mem
;   RDX = const void* ctrl (64 bytes: [0..31]=pre-seed ymm0, [32..63]=mask ymm1)
;   R8  = void*       out  (64 bytes: [0..31]=post-load ymm0, [32..63]=post-load ymm1 mask)
; ABI for vpmaskmov store exports:
;   RCX = const void* src_vec (32 bytes -> ymm2)
;   RDX = const void* mask_vec (32 bytes -> ymm1)
;   R8  = void*       dst_mem (pre-seeded memory destination)

op_pmaskmovd_load_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vpmaskmovd xmm0, xmm1, XMMWORD PTR [rcx]
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm1
    vzeroupper
    ret
op_pmaskmovd_load_xmm ENDP

op_pmaskmovd_load_ymm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
IFDEF ALTER_IMM
    vpmaskmovd ymm0, ymm1, YMMWORD PTR [rcx + 16]
ELSE
    vpmaskmovd ymm0, ymm1, YMMWORD PTR [rcx]
ENDIF
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm1
    vzeroupper
    ret
op_pmaskmovd_load_ymm ENDP

op_pmaskmovq_load_xmm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vpmaskmovq xmm0, xmm1, XMMWORD PTR [rcx]
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm1
    vzeroupper
    ret
op_pmaskmovq_load_xmm ENDP

op_pmaskmovq_load_ymm PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rdx]
    vmovdqu ymm1, YMMWORD PTR [rdx + 32]
    vpmaskmovq ymm0, ymm1, YMMWORD PTR [rcx]
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm1
    vzeroupper
    ret
op_pmaskmovq_load_ymm ENDP

op_pmaskmovd_store_xmm PROC FRAME
    .endprolog
    vmovdqu ymm2, YMMWORD PTR [rcx]
    vmovdqu ymm1, YMMWORD PTR [rdx]
    vpmaskmovd XMMWORD PTR [r8], xmm1, xmm2
    vzeroupper
    ret
op_pmaskmovd_store_xmm ENDP

op_pmaskmovd_store_ymm PROC FRAME
    .endprolog
    vmovdqu ymm2, YMMWORD PTR [rcx]
    vmovdqu ymm1, YMMWORD PTR [rdx]
    vpmaskmovd YMMWORD PTR [r8], ymm1, ymm2
    vzeroupper
    ret
op_pmaskmovd_store_ymm ENDP

op_pmaskmovq_store_xmm PROC FRAME
    .endprolog
    vmovdqu ymm2, YMMWORD PTR [rcx]
    vmovdqu ymm1, YMMWORD PTR [rdx]
    vpmaskmovq XMMWORD PTR [r8], xmm1, xmm2
    vzeroupper
    ret
op_pmaskmovq_store_xmm ENDP

op_pmaskmovq_store_ymm PROC FRAME
    .endprolog
    vmovdqu ymm2, YMMWORD PTR [rcx]
    vmovdqu ymm1, YMMWORD PTR [rdx]
    vpmaskmovq YMMWORD PTR [r8], ymm1, ymm2
    vzeroupper
    ret
op_pmaskmovq_store_ymm ENDP

; --- XMM-width vmovdqu load/store and register copy paths ---

op_movdqu_store128 PROC FRAME
    .endprolog
    vmovdqu xmm0, XMMWORD PTR [rcx]
    vmovdqu XMMWORD PTR [r8], xmm0
    vzeroupper
    ret
op_movdqu_store128 ENDP

op_movdqu_copy128 PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rcx]
    vmovdqu ymm1, YMMWORD PTR [rdx]
    vmovdqu xmm1, xmm0
    vmovdqu YMMWORD PTR [r8], ymm1
    vzeroupper
    ret
op_movdqu_copy128 ENDP

; --- Gather rooted in RDX instead of RCX (ctrl moves to RCX) ---

op_pgatherdd_ymm_rdx PROC FRAME
    .endprolog
    vmovdqu ymm0, YMMWORD PTR [rcx]
    vmovdqu ymm1, YMMWORD PTR [rcx + 32]
    vmovdqu ymm2, YMMWORD PTR [rcx + 64]
    vpgatherdd ymm0, DWORD PTR [rdx + ymm1*4 + 8], ymm2
    vmovdqu YMMWORD PTR [r8], ymm0
    vmovdqu YMMWORD PTR [r8 + 32], ymm2
    vzeroupper
    ret
op_pgatherdd_ymm_rdx ENDP

END
