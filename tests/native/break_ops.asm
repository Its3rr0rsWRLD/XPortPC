; int3 sites for the launcher's --continue-breakpoints (tests/native/break_check.py): RAX holds a known value at
; both, a one-byte int3 (CC) and the two-byte form (CD 03), then the function returns 42. A leaf without stack use.
.code
break_ops PROC
    mov rax, 1122334455667788h
    db 0CCh
    db 0CDh, 03h
    mov eax, 42
    ret
break_ops ENDP
END
