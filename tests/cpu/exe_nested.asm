; Adjust the second argument before calling the existing import wrapper.
IFDEF BYPASS_WRAPPER
EXTERN __imp_mix_args:QWORD
ELSE
EXTERN call_mix:PROC
ENDIF
.code
call_nested PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    sub rdx, 1
IFDEF BYPASS_WRAPPER
    call QWORD PTR [__imp_mix_args]
ELSE
    call call_mix
ENDIF
    add rsp, 28h
    pop rsi
    pop rbx
    ret
call_nested ENDP
END
