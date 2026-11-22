; Source-owned differential fixture for all 12 SSE4.1 pmovsx/pmovzx instructions.
.code

pmovsxbw_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovsxbw xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovsxbw_op ENDP

pmovsxbd_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovsxbd xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovsxbd_op ENDP

pmovsxbq_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovsxbq xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovsxbq_op ENDP

pmovsxwd_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovsxwd xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovsxwd_op ENDP

pmovsxwq_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovsxwq xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovsxwq_op ENDP

pmovsxdq_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovsxdq xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovsxdq_op ENDP

pmovzxbw_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovzxbw xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovzxbw_op ENDP

pmovzxbd_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovzxbd xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovzxbd_op ENDP

pmovzxbq_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovzxbq xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovzxbq_op ENDP

pmovzxwd_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovzxwd xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovzxwd_op ENDP

pmovzxwq_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovzxwq xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovzxwq_op ENDP

pmovzxdq_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    pmovzxdq xmm0, xmm1
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovzxdq_op ENDP

pmovsxbd_mem PROC FRAME
    .endprolog
    pmovsxbd xmm0, dword ptr [rcx]
    movdqu xmmword ptr [rdx], xmm0
    ret
pmovsxbd_mem ENDP

END
