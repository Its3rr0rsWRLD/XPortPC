; coverage: source cpu_aot_import_calls
; Ordinary calls of an imported function, as MSVC emits them: call QWORD PTR [__imp_x] through the import
; address table, and call x or jmp x to the import thunk (jmp QWORD PTR [__imp_x]) that the linker adds when
; the import is declared without __imp_. mix3(first, second, output) and mix4(first, second, output, fourth)
; come from tail_provider.cpp; R8 is the address of three writable QWORDs. Each export takes x in RCX and y
; in RDX. The register probe seeds RBX and RSI, so a nonvolatile register that the translation loses shows
; up as a changed sentinel.
EXTERN __imp_mix3:QWORD
EXTERN __imp_mix4:QWORD
EXTERN mix4:PROC
EXTERN __ImageBase:BYTE
.code

; (mix3(x + 3, y, trace) XOR x) + y. x is kept in RBX and y in a frame slot above the import's home space.
call_keep PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 30h
    .allocstack 30h
    .endprolog
    mov rbx, rcx
    mov QWORD PTR [rsp+28h], rdx
    add rcx, 3
    call QWORD PTR [__imp_mix3]
    xor rax, rbx
    add rax, QWORD PTR [rsp+28h]
    add rsp, 30h
    pop rbx
    ret
call_keep ENDP

; mix3(mix3(x, y, trace), y, trace) + y. y is kept in RBX and the trace pointer in RSI; RCX, RDX and R8 are
; written again between the two calls.
call_twice PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    mov rbx, rdx
    mov rsi, r8
    call QWORD PTR [__imp_mix3]
    mov rcx, rax
    mov rdx, rbx
    mov r8, rsi
    call QWORD PTR [__imp_mix3]
    add rax, rbx
    add rsp, 28h
    pop rsi
    pop rbx
    ret
call_twice ENDP

; mix3(x, y + 7, trace) + 1. Not exported: outer_call reaches it through a direct call.
inner_call PROC FRAME
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    add rdx, 7
    call QWORD PTR [__imp_mix3]
    add rax, 1
    add rsp, 28h
    ret
inner_call ENDP

; inner_call(x, y, trace) + x, with x kept in RBX.
outer_call PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov rbx, rcx
    call inner_call
    add rax, rbx
    add rsp, 20h
    pop rbx
    ret
outer_call ENDP

; mix3(x, y, trace) returned as it is: its return width is the number of bytes the binding guarantees.
pass_result PROC FRAME
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    call QWORD PTR [__imp_mix3]
    add rsp, 28h
    ret
pass_result ENDP

; Fault check only (x is an address): mix3([x], y, trace). The guest read of [x] comes before the call.
read_then_call PROC FRAME
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    mov rcx, QWORD PTR [rcx]
    call QWORD PTR [__imp_mix3]
    add rsp, 28h
    ret
read_then_call ENDP

; Fault check only (x is an address): mix3(x, y, trace) + [x]. The guest read of [x] comes after the call.
call_then_read PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov rbx, rcx
    call QWORD PTR [__imp_mix3]
    add rax, QWORD PTR [rbx]
    add rsp, 20h
    pop rbx
    ret
call_then_read ENDP

; (mix3(x, y, trace) AND 0FFh) + x: only AL of the import's result is read.
low_result PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov rbx, rcx
    call QWORD PTR [__imp_mix3]
    movzx eax, al
    add rax, rbx
    add rsp, 20h
    pop rbx
    ret
low_result ENDP

; mix4(x, y, trace, x XOR y) - x. call mix4 is a direct call of the import thunk.
thunk_call PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov rbx, rcx
    mov r9, rcx
    xor r9, rdx
    call mix4
    sub rax, rbx
    add rsp, 20h
    pop rbx
    ret
thunk_call ENDP

; mix4(x, y, trace, x + y) through a tail jump to the import thunk.
thunk_tail PROC FRAME
    .endprolog
    lea r9, [rcx+rdx]
    jmp mix4
thunk_tail ENDP

; mix4(x, y, trace, y - x) through a tail jump through the IAT. Not exported: outer_tail reaches it through
; a direct call.
inner_tail PROC FRAME
    .endprolog
    mov r9, rdx
    sub r9, rcx
    jmp QWORD PTR [__imp_mix4]
inner_tail ENDP

; inner_tail(x + 1, y, trace) + y, with y kept in RBX.
outer_tail PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov rbx, rdx
    add rcx, 1
    call inner_tail
    add rax, rbx
    add rsp, 20h
    pop rbx
    ret
outer_tail ENDP

; Rejection only: R9, R10 and R11 are written before the call, and RBX is read after it. The controls patch
; that read to a volatile register or to a flag read.
clobber_read PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov rbx, rcx
    mov r9, rcx
    mov r10, rcx
    mov r11, rcx
    call QWORD PTR [__imp_mix3]
    add rax, rbx
    add rsp, 20h
    pop rbx
    ret
clobber_read ENDP

; Rejection only: R10 gets the image base of an MSVC jump table before the call and is used as the table
; base after it, when the call may have changed R10.
table_after_call PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov ebx, ecx
    lea r10, __ImageBase
    call QWORD PTR [__imp_mix3]
    cmp ebx, 1
    ja after_default
    movsxd r9, ebx
    mov r9d, DWORD PTR [(IMAGEREL after_table) + r10 + r9*4]
    add r9, r10
    jmp r9
after_case0:
    add rax, 1
after_default:
    add rsp, 20h
    pop rbx
    ret
    ALIGN 4
after_table LABEL DWORD
    DD IMAGEREL after_case0
    DD IMAGEREL after_default
table_after_call ENDP

; Rejection only: passes the address of call_keep, which the translation does not reproduce, in RCX.
call_guest_arg PROC FRAME
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    lea rcx, call_keep
    call QWORD PTR [__imp_mix3]
    add rsp, 28h
    ret
call_guest_arg ENDP

; Rejection only, never reached as built: not exported and without unwind data, directly after the unwind
; interval of call_guest_arg. The controls patch it into a jump through the IAT terminator, which is not
; an import slot, or into a call of the import from a range-bound function without unwind data.
embed_site PROC
    mov rax, 1122334455667788h
    ret
embed_site ENDP
END
