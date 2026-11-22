; Source-owned fixture for the function-entry rule of direct calls and tail jumps.
; Explicit .pdata/.xdata give the image a chained secondary range. Each caller is fn(x, y, trace)
; with x in RCX and y in RDX and returns RAX; the trace is not written.
OPTION DOTNAME
.data
PUBLIC entry_data
entry_data DQ 0

.code
PUBLIC entry_leaf, entry_inner, entry_caller, entry_tail
; A primary runtime function: RAX = RCX + RDX + 1. entry_inner is an exported interior label.
entry_leaf PROC
    lea rax, [rcx+rdx]
entry_inner::
    add rax, 1
    ret
entry_leaf ENDP
leaf_end LABEL BYTE

; A primary function whose second range is a chained secondary runtime function.
split_head PROC
    mov rax, rcx
    jmp split_tail
split_head ENDP
split_end LABEL BYTE
split_tail::
    sub rax, rdx
    ret
split_tail_end LABEL BYTE

; A framed caller of the primary leaf.
entry_caller PROC
    sub rsp, 28h
    call entry_leaf
    add rsp, 28h
    ret
entry_caller ENDP
caller_end LABEL BYTE

; A tail jump to the primary leaf.
entry_tail PROC
    jmp entry_leaf
entry_tail ENDP
tail_end LABEL BYTE

.xdata SEGMENT READONLY
ALIGN 4
leaf_info DB 1,0,0,0
split_info DB 1,0,0,0
chain_info DB 21h,0,0,0
    DD IMAGEREL split_head, IMAGEREL split_end, IMAGEREL split_info
; Prolog of 4 bytes with one code: at offset 4, UWOP_ALLOC_SMALL of 28h bytes.
caller_info DB 1,4,1,0, 4,42h, 0,0
tail_info DB 1,0,0,0
.xdata ENDS
.pdata SEGMENT READONLY
    DD IMAGEREL entry_leaf, IMAGEREL leaf_end, IMAGEREL leaf_info
    DD IMAGEREL split_head, IMAGEREL split_end, IMAGEREL split_info
    DD IMAGEREL split_tail, IMAGEREL split_tail_end, IMAGEREL chain_info
    DD IMAGEREL entry_caller, IMAGEREL caller_end, IMAGEREL caller_info
    DD IMAGEREL entry_tail, IMAGEREL tail_end, IMAGEREL tail_info
.pdata ENDS
END
