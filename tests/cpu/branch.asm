; Windows x64: ECX = unsigned input, RDX = address of one writable DWORD.
.code
branch_value PROC FRAME
    .endprolog
    mov eax, ecx
    cmp eax, 5
IFDEF INVERT_BRANCH
    jae short below_five
ELSE
    jb short below_five
ENDIF
    add eax, 3
    jmp short check_equal
below_five:
    sub eax, 7
check_equal:
    cmp eax, 15
IFDEF INVERT_BRANCH
    jne short is_fifteen
ELSE
    je short is_fifteen
ENDIF
    add eax, 2
    jmp short check_not_equal
is_fifteen:
    sub eax, 5
check_not_equal:
    cmp eax, 21
IFDEF INVERT_BRANCH
    je short not_twenty_one
ELSE
    jne short not_twenty_one
ENDIF
    add eax, 4
    jmp short check_below_equal
not_twenty_one:
    sub eax, 1
check_below_equal:
    cmp eax, 32
IFDEF INVERT_BRANCH
    ja short at_most_thirty_two
ELSE
    jbe short at_most_thirty_two
ENDIF
    add eax, 6
    jmp short check_above_imm32
at_most_thirty_two:
    sub eax, 3
check_above_imm32:
    cmp eax, 300
IFDEF INVERT_BRANCH
    jbe short above_three_hundred
ELSE
    ja short above_three_hundred
ENDIF
    sub eax, 260
    jmp short check_signed_imm8
above_three_hundred:
    add eax, 512
check_signed_imm8:
    cmp eax, -16
IFDEF INVERT_BRANCH
    ja short at_most_minus_sixteen
ELSE
    jbe short at_most_minus_sixteen
ENDIF
    sub eax, 41
    jmp short check_signed_lt
at_most_minus_sixteen:
    add eax, 19
check_signed_lt:
    cmp eax, -12
IFDEF INVERT_BRANCH
    jge short below_minus_twelve_signed
ELSE
    jl short below_minus_twelve_signed
ENDIF
    add eax, 11
    jmp short check_signed_le_imm32
below_minus_twelve_signed:
    sub eax, 13
check_signed_le_imm32:
    cmp eax, -300
IFDEF INVERT_BRANCH
    jg short at_most_minus_three_hundred_signed
ELSE
    jle short at_most_minus_three_hundred_signed
ENDIF
    sub eax, 29
    jmp short store_value
at_most_minus_three_hundred_signed:
    add eax, 37
store_value:
    mov DWORD PTR [rdx], eax
    add eax, 1
    ret
branch_value ENDP
END
