; Source-owned differential fixture for XCHG in register and memory forms.
; The value exports take (x, y, slot, state). They enter with RAX = R9 = x, RCX = R8 = y, the slot
; pointer in R10 and the state pointer in R11, run one XCHG and write RAX, RCX, R8 and R9 to
; state[0..3]. The token exports take (slot, tokens, previous, count) and exchange each token into
; the shared slot, storing the value each exchange returned; several threads run them at once.
.code

XCHG_ENTER MACRO
    mov r10, r8
    mov r11, r9
    mov rax, rcx
    mov r9, rcx
    mov rcx, rdx
    mov r8, rdx
ENDM

XCHG_LEAVE MACRO
    mov qword ptr [r11], rax
    mov qword ptr [r11+8], rcx
    mov qword ptr [r11+16], r8
    mov qword ptr [r11+24], r9
    ret
ENDM

xchg_al_cl PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg al, cl
    XCHG_LEAVE
xchg_al_cl ENDP

xchg_ah_al PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg ah, al
    XCHG_LEAVE
xchg_ah_al ENDP

xchg_ah_ch PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg ah, ch
    XCHG_LEAVE
xchg_ah_ch ENDP

xchg_r8b_al PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg r8b, al
    XCHG_LEAVE
xchg_r8b_al ENDP

xchg_ax_cx PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg ax, cx
    XCHG_LEAVE
xchg_ax_cx ENDP

xchg_r9w_r8w PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg r9w, r8w
    XCHG_LEAVE
xchg_r9w_r8w ENDP

xchg_eax_ecx PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg eax, ecx
    XCHG_LEAVE
xchg_eax_ecx ENDP

xchg_ecx_r9d PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg ecx, r9d
    XCHG_LEAVE
xchg_ecx_r9d ENDP

; 87 C0: unlike the one-byte 90 (NOP), this form writes EAX and clears the upper half of RAX.
xchg_eax_eax PROC FRAME
    .endprolog
    XCHG_ENTER
    db 87h, 0c0h
    XCHG_LEAVE
xchg_eax_eax ENDP

xchg_rax_rcx PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg rax, rcx
    XCHG_LEAVE
xchg_rax_rcx ENDP

xchg_r8_r9 PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg r8, r9
    XCHG_LEAVE
xchg_r8_r9 ENDP

xchg_m8_al PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg byte ptr [r10], al
    XCHG_LEAVE
xchg_m8_al ENDP

xchg_ah_m8 PROC FRAME
    .endprolog
    XCHG_ENTER
    mov rdx, r10                ; AH cannot be encoded with a REX prefix, so no R10 base
    xchg ah, byte ptr [rdx+1]
    XCHG_LEAVE
xchg_ah_m8 ENDP

xchg_m16_cx PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg word ptr [r10+2], cx
    XCHG_LEAVE
xchg_m16_cx ENDP

xchg_m32_eax PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg dword ptr [r10+4], eax
    XCHG_LEAVE
xchg_m32_eax ENDP

xchg_r8d_m32 PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg r8d, dword ptr [r10]
    XCHG_LEAVE
xchg_r8d_m32 ENDP

xchg_m64_r9 PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg qword ptr [r10], r9
    XCHG_LEAVE
xchg_m64_r9 ENDP

; A misaligned operand stays atomic on x64 (a split lock); the lowering must accept it unchanged.
xchg_m64_misaligned PROC FRAME
    .endprolog
    XCHG_ENTER
    xchg qword ptr [r10+3], rcx
    XCHG_LEAVE
xchg_m64_misaligned ENDP

swap_tokens64 PROC FRAME
    .endprolog
    xor r10d, r10d
next64:
    mov rax, qword ptr [rdx+r10*8]
    xchg qword ptr [rcx], rax
    mov qword ptr [r8+r10*8], rax
    inc r10
    cmp r10, r9
    jne next64
    ret
swap_tokens64 ENDP

swap_tokens32 PROC FRAME
    .endprolog
    xor r10d, r10d
next32:
    mov eax, dword ptr [rdx+r10*4]
    xchg eax, dword ptr [rcx]
    mov dword ptr [r8+r10*4], eax
    inc r10
    cmp r10, r9
    jne next32
    ret
swap_tokens32 ENDP

END
