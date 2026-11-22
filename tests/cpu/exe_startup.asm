; Enter the same return-based body in a native process or a host mapping.
EXTERN native_entry:PROC
EXTERN __ImageBase:BYTE
EXTERN __imp_finish_exe:QWORD

.code
native_startup PROC FRAME
    sub rsp, 40
    .allocstack 40
    .endprolog
    call native_entry
    mov edx, eax
    lea rcx, [__ImageBase]
    call qword ptr [__imp_finish_exe]
    add rsp, 40
    ret
native_startup ENDP
END
