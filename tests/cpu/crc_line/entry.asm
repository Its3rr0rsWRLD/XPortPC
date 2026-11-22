; Compute the CRC-32 of the first line from stdin and print eight uppercase hex digits.
EXTERN crc_step:PROC
EXTERN __imp_getchar:QWORD
EXTERN __imp_putchar:QWORD
EXTERN __imp_fflush:QWORD

.code
native_entry PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    mov ebx, -1
    xor esi, esi
read_next:
    call qword ptr [__imp_getchar]
    cmp eax, -1
    je at_eof
    cmp eax, 10
    je emit_crc
    mov edx, eax
    mov ecx, ebx
    call crc_step
    mov ebx, eax
    mov esi, 1
    jmp read_next
at_eof:
    test esi, esi
    jnz emit_crc
    mov eax, 1
    jmp finished
emit_crc:
    not ebx
    mov esi, 8
digit:
    mov ecx, ebx
    shr ecx, 28
    add ecx, 30h
    cmp ecx, 39h
    jbe write_digit
    add ecx, 7
write_digit:
    call qword ptr [__imp_putchar]
    cmp eax, -1
    je io_error
    shl ebx, 4
    dec esi
    jnz digit
    mov ecx, 10
    call qword ptr [__imp_putchar]
    cmp eax, -1
    je io_error
    xor ecx, ecx
    call qword ptr [__imp_fflush]
    test eax, eax
    jnz io_error
    xor eax, eax
    jmp finished
io_error:
    mov eax, 2
finished:
    add rsp, 28h
    pop rsi
    pop rbx
    ret
native_entry ENDP
END
