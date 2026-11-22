; A CRT-free PE entry. The existing call_mix (direct.asm, IMPORT_MIX)
; calls the named DLL import and records the two actual arguments and its output.
IFDEF TWO_PROVIDERS
EXTERN call_twice:PROC
ELSE
EXTERN call_mix:PROC
IFDEF FRAME_SELECTOR
EXTERN call_bare:PROC
ENDIF
IFDEF NESTED_TARGET
EXTERN call_nested:PROC
ENDIF
IFDEF TWO_TARGETS
EXTERN call_alt:PROC
ENDIF
ENDIF
EXTERN __imp_read_selector:QWORD
EXTERN __imp_emit_trace:QWORD

.code
native_entry PROC FRAME
    sub rsp, 72
    .allocstack 72
    .endprolog
    call qword ptr [__imp_read_selector]
    cmp eax, -1
    je io_error
IFDEF FRAME_SELECTOR
    ; call_bare returns 5 * selector - 5 through a nested, no-unwind leaf.
    mov ecx, eax
    mov edx, 5
    lea r8, [rsp+32]
    call call_bare
ENDIF
    test eax, eax
IFDEF FLIP_SELECTOR
    jnz wide_input
ELSE
    jz wide_input
ENDIF
    mov ecx, 41
    mov edx, 9
IFDEF TWO_TARGETS
    lea r8, [rsp+32]
IFDEF SWAP_TARGETS
    call call_mix
ELSE
    call call_alt
ENDIF
    jmp save_result
ELSE
    jmp dispatch
ENDIF
wide_input:
    mov rcx, 1000002fch
    mov rdx, 100000000h
dispatch:
    lea r8, [rsp+32]
IFDEF NESTED_TARGET
    call call_nested
ELSEIFDEF SWAP_TARGETS
    call call_alt
ELSE
IFDEF TWO_PROVIDERS
    call call_twice
ELSE
    call call_mix
ENDIF
ENDIF
save_result:
    mov [rsp+56], rax
    lea rcx, [rsp+32]
    call qword ptr [__imp_emit_trace]
    test eax, eax
    jz io_error
    mov eax, [rsp+56]
    jmp finished
io_error:
    mov eax, 2
finished:
    add rsp, 72
    ret
native_entry ENDP
END
