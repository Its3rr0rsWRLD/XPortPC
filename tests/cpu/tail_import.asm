; coverage: source cpu_aot_import_tail_jump
; Tail jumps through the import address table, as MSVC ends a function whose last action is a call to an
; imported function. mix3(first, second, output) and mix4(first, second, output, fourth) come from
; tail_provider.cpp; R8 is the address of three writable QWORDs.
EXTERN __imp_mix3:QWORD
EXTERN __imp_mix4:QWORD
.code
; mix3(RCX + 5, RDX * 2, R8): three integer arguments.
tail_mix PROC
    add rcx, 5
    add rdx, rdx
    jmp QWORD PTR [__imp_mix3]
tail_mix ENDP

; Three arguments. RCX below RDX: mix4(RCX, RDX, R8, RCX xor RDX), a fourth argument written to R9 here.
; Otherwise [R8+8] = RDX and AX = CX + DX; the other bytes of RAX are not written.
tail_choose PROC
    cmp rcx, rdx
    jae choose_return
    mov r9, rcx
    xor r9, rdx
    jmp QWORD PTR [__imp_mix4]
choose_return:
    mov QWORD PTR [r8+8], rdx
    mov ax, cx
    add ax, dx
    ret
tail_choose ENDP

; Four arguments: mix4(RCX, RDX - RCX, R8, R9), passing on the incoming R9. The jump carries a REX.W
; prefix (48 FF 25), a form MSVC also emits for tail jumps; the displacement still ends at the jump's end.
tail_pass4 PROC
    sub rdx, rcx
    DB 48h
    jmp QWORD PTR [__imp_mix4]
tail_pass4 ENDP

; Rejection only: passes the address of tail_mix, which the translation does not reproduce, in RCX.
tail_guest_arg PROC
    lea rcx, tail_mix
    jmp QWORD PTR [__imp_mix3]
tail_guest_arg ENDP
END
