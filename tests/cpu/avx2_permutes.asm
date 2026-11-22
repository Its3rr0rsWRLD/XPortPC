; coverage: source cpu_aot_avx2_permutes
; Source-owned differential fixture for AVX2 128-bit lane ops, blends, and cross-lane permutes:
; VBROADCASTI128, VEXTRACTI128, VINSERTI128, VPBLENDD, VPERM2I128,
; VPERMD, VPERMPS, VPERMQ, VPERMPD.
.code

bcast_i128 PROC FRAME
    .endprolog
    vbroadcasti128 ymm0, xmmword ptr [rcx]
    vmovups ymmword ptr [rdx], ymm0
    vzeroupper
    ret
bcast_i128 ENDP

extract_i128_hi PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vextracti128 xmmword ptr [rdx], ymm0, 1
    vzeroupper
    ret
extract_i128_hi ENDP

insert_i128_hi PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vinserti128 ymm0, ymm1, xmmword ptr [rdx], 1
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
insert_i128_hi ENDP

pblendd256 PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vpblendd ymm0, ymm1, ymm2, 0a5h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
pblendd256 ENDP

pblendd256_mem PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vpblendd ymm0, ymm1, ymmword ptr [rdx], 05h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
pblendd256_mem ENDP

pblendd256_mem_zero PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vpblendd ymm0, ymm1, ymmword ptr [rdx], 0
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
pblendd256_mem_zero ENDP

; imm8 = 0x31: low lane = src1_hi (1), high lane = src2_hi (3)
perm2i128_hi PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vperm2i128 ymm0, ymm1, ymm2, 31h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
perm2i128_hi ENDP

; imm8 = 0x82: low lane = src2_lo (2), high lane = zeroed (bit 7 set)
perm2i128_zero PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vperm2i128 ymm0, ymm1, ymm2, 82h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
perm2i128_zero ENDP

permd256 PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vpermd ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
permd256 ENDP

permps256 PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vpermps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
permps256 ENDP

permq256 PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vpermq ymm0, ymm1, 01bh
    vmovups ymmword ptr [rdx], ymm0
    vzeroupper
    ret
permq256 ENDP

permpd256 PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vpermpd ymm0, ymm1, 093h
    vmovups ymmword ptr [rdx], ymm0
    vzeroupper
    ret
permpd256 ENDP

END
