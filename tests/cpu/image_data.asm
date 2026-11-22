; coverage: source cpu_aot_image_data
; RIP-relative data for the jump-table translator's --image-data option: globals in the writable
; section, one of them in its zero-filled tail, and a read-only table, read, written, compared, stored
; and returned through RIP-relative operands. Every export takes RCX, RDX and R8 = address of three
; writable QWORDs; only switch_count writes them.
EXTERN __ImageBase:BYTE

.data
counter QWORD 1000h
; An address inside the image: a DIR64 relocation in the writable section.
counter_ptr QWORD counter

.data?
; Uninitialized data that ends past the file-backed part of the writable section: a mapping
; zero-fills it, and scratch is the last QWORD of the section's virtual extent.
padding BYTE 400h DUP (?)
scratch QWORD ?

.code
; RAX = the counter.
read_counter PROC FRAME
    .endprolog
    mov rax, QWORD PTR counter
    ret
read_counter ENDP

; RAX = the counter before RCX is added to it through a second RIP-relative operand.
bump_counter PROC FRAME
    .endprolog
    mov rax, QWORD PTR counter
    add QWORD PTR counter, rcx
    ret
bump_counter ENDP

; RAX = the address of the counter.
counter_address PROC FRAME
    .endprolog
    lea rax, counter
    ret
counter_address ENDP

; RAX = the relocated address held by counter_ptr.
load_counter_ptr PROC FRAME
    .endprolog
    mov rax, QWORD PTR counter_ptr
    ret
load_counter_ptr ENDP

; RAX = 1 if RCX is the address of the counter, else 0.
is_counter PROC FRAME
    .endprolog
    lea rax, counter
    cmp rcx, rax
    sete al
    movzx eax, al
    ret
is_counter ENDP

; Stores the address of the read-only table into the object at RCX; RAX = RCX.
set_vtable PROC FRAME
    .endprolog
    lea rax, vtable
    mov QWORD PTR [rcx], rax
    mov rax, rcx
    ret
set_vtable ENDP

; RAX = the second table entry, the relocated address of bump_counter.
vtable_entry PROC FRAME
    .endprolog
    mov rax, QWORD PTR vtable+8
    ret
vtable_entry ENDP

; RAX = the scratch word, which is replaced by RCX.
swap_scratch PROC FRAME
    .endprolog
    mov rax, QWORD PTR scratch
    mov QWORD PTR scratch, rcx
    ret
swap_scratch ENDP

; RAX = [RCX], a load through a pointer without image data.
load_through PROC FRAME
    .endprolog
    mov rax, QWORD PTR [rcx]
    ret
load_through ENDP

; MSVC-layout jump table on ECX whose cases update the counter or the scratch word with RDX;
; RAX = [R8] = the counter afterwards.
switch_count PROC FRAME
    .endprolog
    cmp ecx, 3
    ja count_default
    movsxd r9, ecx
    lea r10, __ImageBase
    mov r9d, DWORD PTR [(IMAGEREL count_table) + r10 + r9*4]
    add r9, r10
    jmp r9
count_add:
    add QWORD PTR counter, rdx
    jmp count_done
count_sub:
    sub QWORD PTR counter, rdx
    jmp count_done
count_store:
    mov QWORD PTR scratch, rdx
    jmp count_done
count_xor:
    xor QWORD PTR counter, rdx
    jmp count_done
count_default:
    inc QWORD PTR scratch
count_done:
    mov rax, QWORD PTR counter
    mov QWORD PTR [r8], rax
    ret
    ALIGN 4
count_table LABEL DWORD
    DD IMAGEREL count_add, IMAGEREL count_sub, IMAGEREL count_store, IMAGEREL count_xor
switch_count ENDP

; LLVM-layout jump table on ECX without image data: RAX depends only on ECX and EDX.
switch_only PROC FRAME
    .endprolog
    cmp ecx, 3
    ja only_default
    mov eax, ecx
    lea r9, only_table
    movsxd rax, DWORD PTR [r9+rax*4]
    add rax, r9
    jmp rax
only_inc:
    lea eax, [rdx+1]
    ret
only_triple:
    lea eax, [rdx+rdx*2]
    ret
only_not:
    mov eax, edx
    not eax
    ret
only_default:
    mov eax, edx
    ret
    ALIGN 4
only_table LABEL DWORD
    DD only_inc - only_table, only_triple - only_table, only_not - only_table, only_not - only_table
switch_only ENDP

.const
; Two relocated code addresses and a constant: the "vtable" that set_vtable stores.
vtable QWORD read_counter, bump_counter, 0123456789ABCDEFh
END
