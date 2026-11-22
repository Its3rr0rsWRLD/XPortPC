; coverage: source cpu_aot_sse41_int
; Source-owned differential fixture for 14 128-bit SSE4.1 integer vector instructions:
; PMINSB, PMAXSB, PMINUW, PMAXUW, PMINSD, PMAXSD, PMINUD, PMAXUD,
; PMULLD, PMULDQ, PCMPEQQ, PACKUSDW, PBLENDW, PBLENDVB.
.code

pminsb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pminsb xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pminsb_op ENDP

pmaxsb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmaxsb xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmaxsb_op ENDP

pminuw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pminuw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pminuw_op ENDP

pmaxuw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmaxuw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmaxuw_op ENDP

pminsd_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pminsd xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pminsd_op ENDP

pmaxsd_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmaxsd xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmaxsd_op ENDP

pminud_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pminud xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pminud_op ENDP

pmaxud_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmaxud xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmaxud_op ENDP

pmulld_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmulld xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmulld_op ENDP

pmuldq_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmuldq xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmuldq_op ENDP

pcmpeqq_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pcmpeqq xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pcmpeqq_op ENDP

packusdw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    packusdw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
packusdw_op ENDP

pblendw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pblendw xmm0, xmm1, 0a5h
    movdqu xmmword ptr [r8], xmm0
    ret
pblendw_op ENDP

; RCX = dst (xmm1), RDX = src (xmm2), R8 = mask (xmm0), R9 = out
pblendvb_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    movdqu xmm2, xmmword ptr [rdx]
    movdqu xmm0, xmmword ptr [r8]
    pblendvb xmm1, xmm2, xmm0
    movdqu xmmword ptr [r9], xmm1
    ret
pblendvb_op ENDP

END
