; Source-owned differential fixture for 21 SSE3 and SSE4.1 floating-point and data-movement instructions.
.code

addsubps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    addsubps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
addsubps_op ENDP

addsubpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    addsubpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
addsubpd_op ENDP

haddps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    haddps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
haddps_op ENDP

haddpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    haddpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
haddpd_op ENDP

hsubps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    hsubps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
hsubps_op ENDP

hsubpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    hsubpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
hsubpd_op ENDP

movddup_op PROC FRAME
    .endprolog
    movupd xmm1, xmmword ptr [rcx]
    movddup xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
movddup_op ENDP

movsldup_op PROC FRAME
    .endprolog
    movups xmm1, xmmword ptr [rcx]
    movsldup xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
movsldup_op ENDP

movshdup_op PROC FRAME
    .endprolog
    movups xmm1, xmmword ptr [rcx]
    movshdup xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
movshdup_op ENDP

lddqu_op PROC FRAME
    .endprolog
    lddqu xmm0, xmmword ptr [rcx]
    movups xmmword ptr [r8], xmm0
    ret
lddqu_op ENDP

blendps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    blendps xmm0, xmm1, 0Ah
    movups xmmword ptr [r8], xmm0
    ret
blendps_op ENDP

blendpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    blendpd xmm0, xmm1, 02h
    movupd xmmword ptr [r8], xmm0
    ret
blendpd_op ENDP

blendvps_op PROC FRAME
    .endprolog
    movups xmm1, xmmword ptr [rcx]
    movups xmm2, xmmword ptr [rdx]
    movups xmm0, xmmword ptr [r9]
    blendvps xmm1, xmm2, xmm0
    movups xmmword ptr [r8], xmm1
    ret
blendvps_op ENDP

blendvpd_op PROC FRAME
    .endprolog
    movupd xmm1, xmmword ptr [rcx]
    movupd xmm2, xmmword ptr [rdx]
    movupd xmm0, xmmword ptr [r9]
    blendvpd xmm1, xmm2, xmm0
    movupd xmmword ptr [r8], xmm1
    ret
blendvpd_op ENDP

dpps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    dpps xmm0, xmm1, 0D5h
    movups xmmword ptr [r8], xmm0
    ret
dpps_op ENDP

dppd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    dppd xmm0, xmm1, 031h
    movupd xmmword ptr [r8], xmm0
    ret
dppd_op ENDP

roundps_nearest_op PROC FRAME
    .endprolog
    movups xmm1, xmmword ptr [rcx]
    roundps xmm0, xmm1, 08h
    movups xmmword ptr [r8], xmm0
    ret
roundps_nearest_op ENDP

roundps_floor_op PROC FRAME
    .endprolog
    movups xmm1, xmmword ptr [rcx]
    roundps xmm0, xmm1, 09h
    movups xmmword ptr [r8], xmm0
    ret
roundps_floor_op ENDP

roundpd_ceil_op PROC FRAME
    .endprolog
    movupd xmm1, xmmword ptr [rcx]
    roundpd xmm0, xmm1, 0Ah
    movupd xmmword ptr [r8], xmm0
    ret
roundpd_ceil_op ENDP

roundpd_trunc_op PROC FRAME
    .endprolog
    movupd xmm1, xmmword ptr [rcx]
    roundpd xmm0, xmm1, 0Bh
    movupd xmmword ptr [r8], xmm0
    ret
roundpd_trunc_op ENDP

roundss_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rdx]
    movups xmm1, xmmword ptr [rcx]
    roundss xmm0, xmm1, 08h
    movups xmmword ptr [r8], xmm0
    ret
roundss_op ENDP

roundsd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rdx]
    movupd xmm1, xmmword ptr [rcx]
    roundsd xmm0, xmm1, 09h
    movupd xmmword ptr [r8], xmm0
    ret
roundsd_op ENDP

extractps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    extractps eax, xmm0, 2
    ret
extractps_op ENDP

END
