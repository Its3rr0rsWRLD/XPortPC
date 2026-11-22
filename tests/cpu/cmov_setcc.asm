; Source-owned differential fixture for unsigned/equality CMOVcc and SETcc:
; CMOVA, CMOVAE, CMOVB, CMOVE (32-bit and 64-bit) and SETA, SETAE, SETB, SETBE, SETNE.
; 32-bit CMOVcc initializes RAX with upper-half noise to verify unconditional zero-extension;
; SETcc initializes RAX with 0x123456789abcdef0 to verify upper 56 bits are preserved.
.code

cmova32 PROC FRAME
    .endprolog
    mov rax, 0deadbeef00000011h
    cmp ecx, edx
    cmova eax, r8d
    ret
cmova32 ENDP

cmova64 PROC FRAME
    .endprolog
    mov rax, 01122334455667788h
    cmp rcx, rdx
    cmova rax, r8
    ret
cmova64 ENDP

cmovae32 PROC FRAME
    .endprolog
    mov rax, 0deadbeef00000011h
    cmp ecx, edx
    cmovae eax, r8d
    ret
cmovae32 ENDP

cmovae64 PROC FRAME
    .endprolog
    mov rax, 01122334455667788h
    cmp rcx, rdx
    cmovae rax, r8
    ret
cmovae64 ENDP

cmovb32 PROC FRAME
    .endprolog
    mov rax, 0deadbeef00000011h
    cmp ecx, edx
    cmovb eax, r8d
    ret
cmovb32 ENDP

cmovb64 PROC FRAME
    .endprolog
    mov rax, 01122334455667788h
    cmp rcx, rdx
    cmovb rax, r8
    ret
cmovb64 ENDP

cmove32 PROC FRAME
    .endprolog
    mov rax, 0deadbeef00000011h
    cmp ecx, edx
    cmove eax, r8d
    ret
cmove32 ENDP

cmove64 PROC FRAME
    .endprolog
    mov rax, 01122334455667788h
    cmp rcx, rdx
    cmove rax, r8
    ret
cmove64 ENDP

seta_op PROC FRAME
    .endprolog
    mov rax, 0123456789abcdef0h
    cmp rcx, rdx
    seta al
    ret
seta_op ENDP

setae_op PROC FRAME
    .endprolog
    mov rax, 0123456789abcdef0h
    cmp rcx, rdx
    setae al
    ret
setae_op ENDP

setb_op PROC FRAME
    .endprolog
    mov rax, 0123456789abcdef0h
    cmp rcx, rdx
    setb al
    ret
setb_op ENDP

setbe_op PROC FRAME
    .endprolog
    mov rax, 0123456789abcdef0h
    cmp rcx, rdx
    setbe al
    ret
setbe_op ENDP

setne_op PROC FRAME
    .endprolog
    mov rax, 0123456789abcdef0h
    cmp rcx, rdx
    setne al
    ret
setne_op ENDP

END
