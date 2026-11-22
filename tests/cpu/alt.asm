; Alternate caller adds nine to the first import argument.
EXTERN __imp_mix_args:QWORD
.code
call_alt PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    mov rbx, rcx
    mov rsi, rdx
    add rcx, 9
    sub rdx, 3
    call QWORD PTR [__imp_mix_args]
    add rax, rbx
    xor rax, rsi
    add rsp, 28h
    pop rsi
    pop rbx
    ret
call_alt ENDP
END
