; coverage: source cpu_aot_sse2_int
; Source-owned differential fixture for 18 baseline 128-bit SSE2 packed integer ALU instructions.
.code

paddb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    paddb xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
paddb_op ENDP

paddw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    paddw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
paddw_op ENDP

paddd_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    paddd xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
paddd_op ENDP

paddq_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    paddq xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
paddq_op ENDP

psubb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    psubb xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
psubb_op ENDP

psubw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    psubw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
psubw_op ENDP

psubd_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    psubd xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
psubd_op ENDP

psubq_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    psubq xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
psubq_op ENDP

pand_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pand xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pand_op ENDP

pandn_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pandn xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pandn_op ENDP

por_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    por xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
por_op ENDP

pxor_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pxor xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pxor_op ENDP

pcmpeqb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pcmpeqb xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pcmpeqb_op ENDP

pcmpeqw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pcmpeqw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pcmpeqw_op ENDP

pcmpeqd_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pcmpeqd xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pcmpeqd_op ENDP

pcmpgtb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pcmpgtb xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pcmpgtb_op ENDP

pcmpgtw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pcmpgtw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pcmpgtw_op ENDP

pcmpgtd_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pcmpgtd xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pcmpgtd_op ENDP

END
