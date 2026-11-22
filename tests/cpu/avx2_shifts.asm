; coverage: source cpu_aot_avx2_shifts
; Source-owned differential fixture for AVX2 broadcasts and variable per-lane shifts:
; VPBROADCASTB, VPBROADCASTW, VPBROADCASTD, VPBROADCASTQ,
; VPSLLVD, VPSRLVD, VPSRAVD, VPSLLVQ, VPSRLVQ.
.code

bcast_b256 PROC FRAME
    .endprolog
    vpbroadcastb ymm0, byte ptr [rcx]
    vmovups ymmword ptr [rdx], ymm0
    vzeroupper
    ret
bcast_b256 ENDP

bcast_w256 PROC FRAME
    .endprolog
    vpbroadcastw ymm0, word ptr [rcx]
    vmovups ymmword ptr [rdx], ymm0
    vzeroupper
    ret
bcast_w256 ENDP

bcast_d256 PROC FRAME
    .endprolog
    vpbroadcastd ymm0, dword ptr [rcx]
    vmovups ymmword ptr [rdx], ymm0
    vzeroupper
    ret
bcast_d256 ENDP

bcast_q256 PROC FRAME
    .endprolog
    vpbroadcastq ymm0, qword ptr [rcx]
    vmovups ymmword ptr [rdx], ymm0
    vzeroupper
    ret
bcast_q256 ENDP

; Register-source 128-bit broadcast: verifies upper 128 bits of YMM0 are zeroed.
bcast_d128_reg PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rdx]
    vmovups ymm1, ymmword ptr [rcx]
    vpbroadcastd xmm0, xmm1
    vmovups ymmword ptr [rdx], ymm0
    vzeroupper
    ret
bcast_d128_reg ENDP

sllvd256 PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vpsllvd ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
sllvd256 ENDP

srlvd256 PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vpsrlvd ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
srlvd256 ENDP

sravd256 PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vpsravd ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
sravd256 ENDP

sllvq256 PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vpsllvq ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
sllvq256 ENDP

srlvq256 PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vpsrlvq ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
srlvq256 ENDP

END
