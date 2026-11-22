; Source-owned differential fixture for XLATB (AL = [RBX + AL]), its REX.W spelling and its 67h form
; (AL = [EBX + AL], wrapped at 32 bits). Each export takes (table, RAX, flag preset, state) in RCX, RDX,
; R8 and R9. RBX is saved in R11 and restored before the return. ADD R8, R8 sets ZF and CF from the
; preset; XLATB leaves them alone, and (CF << 1) | ZF goes to state[0].
.code

XLAT_LEAVE MACRO
    LOCAL no_carry, no_zero
    mov rbx, r11
    mov r10d, 0
    jae short no_carry
    mov r10d, 2
no_carry:
    jne short no_zero
    or r10d, 1
no_zero:
    mov qword ptr [r9], r10
    ret
ENDM

xlat_basic PROC FRAME
    .endprolog
    mov r11, rbx
    mov rbx, rcx
    mov rax, rdx
    add r8, r8
    xlatb
    XLAT_LEAVE
xlat_basic ENDP

; 48 D7: REX.W does not change the operation.
xlat_rexw PROC FRAME
    .endprolog
    mov r11, rbx
    mov rbx, rcx
    mov rax, rdx
    add r8, r8
    db 48h
    xlatb
    XLAT_LEAVE
xlat_rexw ENDP

; 67 D7: the table address is EBX + AL modulo 2^32, so the upper half of RBX is ignored.
xlat_addr32 PROC FRAME
    .endprolog
    mov r11, rbx
    mov rbx, rcx
    mov rax, rdx
    add r8, r8
    db 67h
    xlatb
    XLAT_LEAVE
xlat_addr32 ENDP

; Two lookups in a row: AL = table[table[AL]].
xlat_twice PROC FRAME
    .endprolog
    mov r11, rbx
    mov rbx, rcx
    mov rax, rdx
    add r8, r8
    xlatb
    xlatb
    XLAT_LEAVE
xlat_twice ENDP

END
