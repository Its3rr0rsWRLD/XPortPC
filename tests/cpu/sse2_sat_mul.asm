; Source-owned differential fixture for 20 baseline 128-bit SSE2 packed saturating, multiply, min/max, avg, and sad instructions.
.code

paddsb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    paddsb xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
paddsb_op ENDP

paddsw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    paddsw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
paddsw_op ENDP

paddusb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    paddusb xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
paddusb_op ENDP

paddusw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    paddusw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
paddusw_op ENDP

psubsb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    psubsb xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
psubsb_op ENDP

psubsw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    psubsw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
psubsw_op ENDP

psubusb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    psubusb xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
psubusb_op ENDP

psubusw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    psubusw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
psubusw_op ENDP

pmulhw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmulhw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmulhw_op ENDP

pmulhuw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmulhuw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmulhuw_op ENDP

pmullw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmullw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmullw_op ENDP

pmaddwd_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmaddwd xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmaddwd_op ENDP

pmuludq_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmuludq xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmuludq_op ENDP

pminub_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pminub xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pminub_op ENDP

pmaxub_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmaxub xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmaxub_op ENDP

pminsw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pminsw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pminsw_op ENDP

pmaxsw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmaxsw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmaxsw_op ENDP

pavgb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pavgb xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pavgb_op ENDP

pavgw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pavgw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pavgw_op ENDP

psadbw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    psadbw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
psadbw_op ENDP

END
