; Source-owned differential fixture for ADX instructions (ADCX, ADOX) in 32-bit and 64-bit forms,
; plus interleaved ADCX/ADOX proving independent CF and OF carry chains.
; Output slot receives (CF << 1) | OF.
.code

; RCX = a, RDX = b, R8 = cin (0/1), R9 = out ((CF << 1) | OF)
adcx32_op PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10, r8         ; CF = (cin != 0), OF = 0
    mov rax, rcx
    adcx eax, edx
    mov r10d, 0
    seto r10b
    jae short @F
    or r10d, 2
@@:
    mov qword ptr [r9], r10
    ret
adcx32_op ENDP

adcx64_op PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10, r8
    mov rax, rcx
    adcx rax, rdx
    mov r10d, 0
    seto r10b
    jae short @F
    or r10d, 2
@@:
    mov qword ptr [r9], r10
    ret
adcx64_op ENDP

; RCX = a, RDX = b, R8 = oin (0/1), R9 = out ((CF << 1) | OF)
adox32_op PROC FRAME
    .endprolog
    xor r10d, r10d      ; CF = 0, OF = 0
    test r8, r8
    je short @F
    mov r10d, 07fffffffh
    add r10d, 1         ; OF = 1, CF = 0
@@:
    mov rax, rcx
    adox eax, edx
    mov r10d, 0
    seto r10b
    jae short @F
    or r10d, 2
@@:
    mov qword ptr [r9], r10
    ret
adox32_op ENDP

adox64_op PROC FRAME
    .endprolog
    xor r10d, r10d
    test r8, r8
    je short @F
    mov r10d, 07fffffffh
    add r10d, 1
@@:
    mov rax, rcx
    adox rax, rdx
    mov r10d, 0
    seto r10b
    jae short @F
    or r10d, 2
@@:
    mov qword ptr [r9], r10
    ret
adox64_op ENDP

; Interleaved dual-carry chain: RCX = a, RDX = b, R8 = c, R9 = out[2] (out[0]=adox_sum, out[1]=(CF<<1)|OF).
; Returns adcx_sum.
adx_dual64 PROC FRAME
    .endprolog
    xor r10d, r10d      ; CF = 0, OF = 0
    mov rax, rcx
    mov r11, rdx
    adcx rax, r8        ; sets CF, preserves OF=0
    adox r11, r8        ; uses OF=0, sets OF, preserves CF
    adcx rax, rdx       ; uses CF from first adcx, preserves OF from first adox
    adox r11, rcx       ; uses OF from first adox, preserves CF from second adcx
    mov qword ptr [r9], r11
    mov r10d, 0
    seto r10b
    jae short @F
    or r10d, 2
@@:
    mov qword ptr [r9 + 8], r10
    ret
adx_dual64 ENDP

; OF producer compositions: shl-by-1 -> adox, imul -> seto, andn clears OF -> seto.
shl1_adox32 PROC FRAME
    .endprolog
    shl ecx, 1          ; sets OF = MSB(result) ^ CF
    mov eax, edx
    adox eax, r8d       ; consumes OF from shl-by-1
    mov r10d, 0
    seto r10b
    mov qword ptr [r9], r10
    ret
shl1_adox32 ENDP

imul_seto32 PROC FRAME
    .endprolog
    imul ecx, edx       ; sets OF = CF = (product != int32(product))
    mov eax, 0
    seto al
    ret
imul_seto32 ENDP

andn_clears_of32 PROC FRAME
    .endprolog
    mov r10d, 07fffffffh
    add r10d, 1         ; seed OF = 1
    andn r10d, ecx, edx ; BMI1 clears OF = 0
    mov eax, 0
    seto al
    ret
andn_clears_of32 ENDP

END
