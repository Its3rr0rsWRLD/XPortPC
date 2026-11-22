; coverage: source cpu_aot_sign_ext_adc
; Source-owned differential fixture for baseline x64 sign-extension and ADC instructions:
; CBW, CWDE, CDQE, CQO, MOVSX (8/16 -> 16/32/64), and ADC (32/64-bit with carry-in/out).
.code

cbw_op PROC FRAME
    .endprolog
    mov rax, rcx
    cbw
    ret
cbw_op ENDP

cwde_op PROC FRAME
    .endprolog
    mov rax, rcx
    cwde
    ret
cwde_op ENDP

cdqe_op PROC FRAME
    .endprolog
    mov rax, rcx
    cdqe
    ret
cdqe_op ENDP

; Returns RDX (the sign-extension word) after CQO.
cqo_op PROC FRAME
    .endprolog
    mov rax, rcx
    cqo
    mov rax, rdx
    ret
cqo_op ENDP

movsx_r16_r8 PROC FRAME
    .endprolog
    mov rax, 0123456789abcdefh
    movsx ax, cl
    ret
movsx_r16_r8 ENDP

movsx_r32_r8 PROC FRAME
    .endprolog
    mov rax, -1
    movsx eax, cl
    ret
movsx_r32_r8 ENDP

movsx_r64_r8 PROC FRAME
    .endprolog
    movsx rax, cl
    ret
movsx_r64_r8 ENDP

movsx_r32_r16 PROC FRAME
    .endprolog
    mov rax, -1
    movsx eax, cx
    ret
movsx_r32_r16 ENDP

movsx_r64_r16 PROC FRAME
    .endprolog
    movsx rax, cx
    ret
movsx_r64_r16 ENDP

; RCX = a, RDX = b, R8 = carry_in (0 or 1), R9 = flags_out ((CF << 1) | ZF)
adc32_op PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10, r8         ; CF=1 iff carry_in != 0
    mov rax, rcx
    adc eax, edx
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r9], r10
    ret
adc32_op ENDP

adc64_op PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10, r8         ; CF=1 iff carry_in != 0
    mov rax, rcx
    adc rax, rdx
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r9], r10
    ret
adc64_op ENDP

END
