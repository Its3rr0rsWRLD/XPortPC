; A CRT-free PE that isolates the process-exit path, the deterministic control for #281.
;
; The entry point starts a worker thread that never returns, writes a ready marker, and then either
; returns (the loader's thread start calls ExitProcess with the return value) or exits the
; entry thread only (ExitThread), leaving the worker alone in the process.
;
; The worker signals an event before it sleeps, and the entry waits on that event before it
; leaves. Without that handshake the two could race: a fast machine can return from the entry
; before the new thread has ever run, and the fixture would then exercise a different case.
; The event turns "a live worker exists when the entry leaves" into a fact instead of an
; assumption.
;
;   original    worker started, entry thread exits with ExitThread  -> process stays alive
;   RETURNING   worker started, entry returns                       -> exit path is the variable
;   NO_WORKER   no worker, entry returns                            -> exits with the return value
;
; The reported hang shows one live thread-pool worker and no native_entry frame, so the
; question is whether a live worker alone keeps such a process alive. This fixture answers
; that without the CRT, without pe_map and without any dependency of the title's build.
EXTERN __imp_GetStdHandle:QWORD
EXTERN __imp_WriteFile:QWORD
EXTERN __imp_CreateThread:QWORD
EXTERN __imp_ExitThread:QWORD
EXTERN __imp_Sleep:QWORD
EXTERN __imp_CreateEventA:QWORD
EXTERN __imp_SetEvent:QWORD
EXTERN __imp_WaitForSingleObject:QWORD

.data
message     DB "worker-alive control", 13, 10
message_len EQU $ - message
written     DQ 0
started     DQ 0

.code
; SetEvent first: the entry cannot leave until this thread is running.
worker PROC FRAME
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    mov rcx, QWORD PTR [started]
    call QWORD PTR [__imp_SetEvent]
    mov ecx, -1                         ; Sleep(INFINITE): the worker never returns
    call QWORD PTR [__imp_Sleep]
    add rsp, 28h
    ret
worker ENDP

worker_alive_entry PROC FRAME
    sub rsp, 38h                        ; 20h shadow space, 18h for a 6th argument and alignment
    .allocstack 38h
    .endprolog
IFNDEF NO_WORKER
    xor ecx, ecx                        ; lpEventAttributes
    mov edx, 1                          ; bManualReset: SetEvent stays signaled
    xor r8d, r8d                        ; bInitialState: not signaled
    xor r9d, r9d                        ; lpName
    call QWORD PTR [__imp_CreateEventA]
    mov QWORD PTR [started], rax
    test rax, rax
    jz failed

    xor ecx, ecx                        ; lpThreadAttributes
    xor edx, edx                        ; dwStackSize
    lea r8, worker                      ; lpStartAddress
    xor r9d, r9d                        ; lpParameter
    mov QWORD PTR [rsp+20h], 0          ; dwCreationFlags
    mov QWORD PTR [rsp+28h], 0          ; lpThreadId
    call QWORD PTR [__imp_CreateThread]
    test rax, rax
    jz failed

    mov rcx, QWORD PTR [started]        ; wait until the worker has run at least once
    mov edx, -1                         ; INFINITE
    call QWORD PTR [__imp_WaitForSingleObject]
    test eax, eax                       ; WAIT_OBJECT_0
    jnz failed
ENDIF
    mov ecx, -11                        ; STD_OUTPUT_HANDLE
    call QWORD PTR [__imp_GetStdHandle]
    mov rcx, rax
    lea rdx, message
    mov r8d, message_len
    lea r9, written
    mov QWORD PTR [rsp+20h], 0
    call QWORD PTR [__imp_WriteFile]
IFDEF RETURN_FROM_ENTRY
    xor eax, eax
    jmp finished
ELSE
    xor ecx, ecx                        ; ExitThread(0): the entry thread leaves, the worker stays
    call QWORD PTR [__imp_ExitThread]
ENDIF
failed:
    mov eax, 3
finished:
    add rsp, 38h
    ret
worker_alive_entry ENDP
END
