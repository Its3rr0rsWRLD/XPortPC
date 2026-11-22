; Source-owned differential fixture for baseline x64 MUL, DIV, IDIV, XADD, and CMPXCHG
; in 32-bit and 64-bit forms.
.code

; RCX = a, RDX = b, R8 = hi_out, R9 = cf_out. Returns lo.
mul32_op PROC FRAME
    .endprolog
    mov rax, rcx
    mov r10, rdx
    mov rdx, -1
    mul r10d
    mov qword ptr [r8], rdx
    mov r10d, 0
    jae short @F
    mov r10d, 1
@@:
    mov qword ptr [r9], r10
    ret
mul32_op ENDP

mul64_op PROC FRAME
    .endprolog
    mov rax, rcx
    mov r10, rdx
    mul r10
    mov qword ptr [r8], rdx
    mov r10d, 0
    jae short @F
    mov r10d, 1
@@:
    mov qword ptr [r9], r10
    ret
mul64_op ENDP

; RCX = lo, RDX = hi, R8 = divisor, R9 = rem_out. Returns quot.
div32_op PROC FRAME
    .endprolog
    mov rax, rcx
    div r8d
    mov qword ptr [r9], rdx
    ret
div32_op ENDP

div64_op PROC FRAME
    .endprolog
    mov rax, rcx
    div r8
    mov qword ptr [r9], rdx
    ret
div64_op ENDP

idiv32_op PROC FRAME
    .endprolog
    mov rax, rcx
    idiv r8d
    mov qword ptr [r9], rdx
    ret
idiv32_op ENDP

idiv64_op PROC FRAME
    .endprolog
    mov rax, rcx
    idiv r8
    mov qword ptr [r9], rdx
    ret
idiv64_op ENDP

; RCX = dst, RDX = src, R8 = old_dst_out, R9 = flags_out ((CF << 1) | ZF). Returns sum.
xadd32_op PROC FRAME
    .endprolog
    mov rax, rcx
    mov r10, rdx
    xadd eax, r10d
    mov qword ptr [r8], r10
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r9], r10
    ret
xadd32_op ENDP

xadd64_op PROC FRAME
    .endprolog
    mov rax, rcx
    mov r10, rdx
    xadd rax, r10
    mov qword ptr [r8], r10
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r9], r10
    ret
xadd64_op ENDP

; RCX = expected (RAX), RDX = dst, R8 = desired (src), R9 = dst_and_flags_out[2]. Returns final RAX.
cmpxchg32_op PROC FRAME
    .endprolog
    mov rax, rcx
    mov r10, rdx
    cmpxchg r10d, r8d
    mov qword ptr [r9], r10
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r9 + 8], r10
    ret
cmpxchg32_op ENDP

cmpxchg64_op PROC FRAME
    .endprolog
    mov rax, rcx
    mov r10, rdx
    cmpxchg r10, r8
    mov qword ptr [r9], r10
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r9 + 8], r10
    ret
cmpxchg64_op ENDP

; Memory-operand XADD where source register is also the address base: xadd [rcx], rcx.
; Returns old memory value (now in RCX) via RAX; memory at original RCX receives old + addr.
xadd64_mem PROC FRAME
    .endprolog
    xadd qword ptr [rcx], rcx
    mov rax, rcx
    ret
xadd64_mem ENDP

END
