; coverage: record cpu_aot_switch_strings
; Original Windows x64 fixtures: ctx = {source, destination, fill, backwards}.
; Each operation reports remaining count, final pointers and an arithmetic flag.
STRING_CASE MACRO symbol, operation, backwards, repeated
symbol PROC FRAME
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    .endprolog
    mov r9, rcx
    mov rsi, [r9]
    mov rdi, [r9+8]
    mov rax, [r9+16]
    mov rcx, rdx
    cmp rcx, 3
IF backwards
    std
ENDIF
IF repeated
    rep operation
ELSE
    operation
ENDIF
    cld
    setb r10b
    movzx r10d, r10b
    mov [r8], rcx
    mov [r8+8], rsi
    mov [r8+16], rdi
    mov [r8+24], r10
    mov rax, rcx
    pop rdi
    pop rsi
    ret
symbol ENDP
ENDM

.code
STRING_CASE rep_movsb_forward, movsb, 0, 1
STRING_CASE rep_movsw_forward, movsw, 0, 1
STRING_CASE rep_movsd_forward, movsd, 0, 1
STRING_CASE rep_movsq_forward, movsq, 0, 1

; Two paths join with different DF values. The selected direction is live at REP.

; The REP state must not be confused with the enclosing control-flow loop.
loop_copy PROC FRAME
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    .endprolog
    mov r9, rcx
    mov rsi, [r9]
    mov rdi, [r9+8]
    mov r11d, 3
copy_again:
    mov rcx, rdx
    rep movsb
    dec r11d
    jne copy_again
    mov [r8], rcx
    mov [r8+8], rsi
    mov [r8+16], rdi
    mov qword ptr [r8+24], 0
    mov rax, rcx
    pop rdi
    pop rsi
    ret
loop_copy ENDP

call_copy PROC FRAME
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    call rep_movsb_forward
    add rsp, 28h
    ret
call_copy ENDP

; Compiled but never executed: prove DF is clear at every ABI boundary.


END
