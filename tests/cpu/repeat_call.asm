; Both functions take (uint64_t, uint64_t, uint64_t trace[3]).
; call_twice calls mix_args twice. Only RBX and RSI survive each call, so the
; trace pointer is parked in RSI and copied back to R8 for the second call.
IFDEF IMPORT_MIX
EXTERN __imp_mix_args:QWORD
ENDIF
IFDEF IMPORT_ACCUMULATE
EXTERN __imp_accumulate_args:QWORD
ENDIF
.code
IFNDEF IMPORT_MIX
mix_args PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    sub rsp, 8
    .allocstack 8
    .endprolog
    mov rbx, rdx
    mov rsi, rcx
    mov [r8], rsi
    mov [r8+8], rbx
    mov rax, rsi
    sub rax, rbx
    add rax, 11
    mov [r8+16], rax
IFDEF ALTER_RETURN
    add rax, 1
ENDIF
    add rsp, 8
    pop rsi
    pop rbx
    ret
mix_args ENDP
ENDIF

call_twice PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    mov rbx, rcx
    mov rsi, r8
    add rcx, 7
    sub rdx, 3
IFDEF IMPORT_MIX
    call QWORD PTR [__imp_mix_args]
ELSE
    call mix_args
ENDIF
    ; The second call's arguments depend on the first result. With ADD, a
    ; callee that returns one more changes the caller's return by exactly 2.
    mov rcx, rax
    add rcx, rbx
    mov rdx, rbx
IFNDEF DROP_RELOAD
    mov r8, rsi
ENDIF
IFDEF IMPORT_ACCUMULATE
    call QWORD PTR [__imp_accumulate_args]
ELSEIFDEF IMPORT_MIX
    call QWORD PTR [__imp_mix_args]
ELSE
    call mix_args
ENDIF
    add rax, rbx
    add rsp, 28h
    pop rsi
    pop rbx
    ret
call_twice ENDP
END
