# Learns and checks the PC Gaming Runtime's interface layer with the stand-in GDK samples (Microsoft's
# public Xbox-GDK-Samples, built for PC by tools/build_standin_samples.ps1; cards: standin-titles).
# For the PC worker's script jobs (cards: pc-gpu-queue, "Script jobs"): -Build is out\build\dev of the
# job's worktree, -Out the job's results folder.
#
# 1. Runs each -Run sample under x2w_launch --xgr MODE for each -Modes entry (hidden, time-limited):
#    <Out>\<Sample>-<mode>\run.log, stderr.txt (x2w lines only), exit.txt.
# 2. Resolves every "caller=<sample>.exe+0xRVA" of those logs to a function name with dbghelp and the
#    PDB of our own build of the sample: <Out>\<Sample>-<mode>\callers.tsv (rva, symbol+offset).
# 3. Static facts from each sample's own linked code (-Scan samples): for every function whose name
#    starts with a Gaming Runtime family prefix, the GUIDs its RIP-relative LEAs load, its indirect
#    call/jmp [reg+disp] displacements and the functions it calls directly: <Out>\thunks-<Sample>.tsv.
# 4. Lines of the public PC GDK NuGet headers (-Gdk) that mention QueryApiImpl or InitializeApiImpl:
#    <Out>\gdk-headers.txt (file, line number, first 200 characters).
# Writes only names, numbers and GUIDs; copies no sample or SDK files.
param(
    [Parameter(Mandatory = $true)][string]$Build,
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Samples = "C:\Users\brady\Documents\GitHub\anyps5-agents\jobs\standin\bin",
    [string]$Gdk = "C:\Users\brady\Projects\xport-report\out\standin\gdk",
    [string]$Run = "AsynchronousProgramming,GameSaveCombo",
    [string]$Scan = "AsynchronousProgramming,GameSaveCombo,SystemInfo,SimpleTriangleDesktop,GameInputSequential",
    [string]$Modes = "trace,ours",
    [int]$Timeout = 20
)
$ErrorActionPreference = "Continue"
$launcher = Join-Path $Build "x2w_launch.exe"
$shims = Join-Path $Build "shims"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

$source = @"
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

public static class XgrSym {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct SYMBOL_INFOW {
        public uint SizeOfStruct; public uint TypeIndex; public ulong Reserved0; public ulong Reserved1;
        public uint Index; public uint Size; public ulong ModBase; public uint Flags; public ulong Value;
        public ulong Address; public uint Register; public uint Scope; public uint Tag; public uint NameLen;
        public uint MaxNameLen;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 1024)] public string Name;
    }
    public delegate bool EnumCallback(IntPtr info, uint size, IntPtr context);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr LoadLibraryW(string path);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr LoadLibraryExW(string path, IntPtr file, uint flags);
    [DllImport("dbghelp.dll", CharSet = CharSet.Unicode)] static extern uint SymSetOptions(uint options);
    [DllImport("dbghelp.dll", CharSet = CharSet.Unicode)] static extern bool SymInitializeW(IntPtr process, string path, bool invade);
    [DllImport("dbghelp.dll", CharSet = CharSet.Unicode)] static extern bool SymCleanup(IntPtr process);
    [DllImport("dbghelp.dll", CharSet = CharSet.Unicode)] static extern ulong SymLoadModuleExW(IntPtr process, IntPtr file, string image, string module, ulong baseOfDll, uint size, IntPtr data, uint flags);
    [DllImport("dbghelp.dll", CharSet = CharSet.Unicode)] static extern bool SymFromAddrW(IntPtr process, ulong address, out ulong displacement, ref SYMBOL_INFOW info);
    [DllImport("dbghelp.dll", CharSet = CharSet.Unicode)] static extern bool SymFromNameW(IntPtr process, string name, ref SYMBOL_INFOW info);
    [DllImport("dbghelp.dll", CharSet = CharSet.Unicode)] static extern bool SymEnumSymbolsW(IntPtr process, ulong baseOfDll, string mask, EnumCallback callback, IntPtr context);

    static IntPtr process = new IntPtr(0x5851);  // any unique value identifies the dbghelp session
    const ulong Base = 0x10000000;
    static byte[] image;   // the exe laid out at its RVAs
    static List<uint[]> sections = new List<uint[]>();  // rva, size, characteristics

    public static void PreferDbgHelp(string path) { if (File.Exists(path)) LoadLibraryW(path); }

    public static string Open(string exe) {
        SymCleanup(process);
        SymSetOptions(0x2 | 0x200 | 0x80000);  // UNDNAME, FAIL_CRITICAL_ERRORS, NO_PROMPTS
        if (!SymInitializeW(process, Path.GetDirectoryName(exe), false)) return "SymInitialize failed " + Marshal.GetLastWin32Error();
        if (SymLoadModuleExW(process, IntPtr.Zero, exe, null, Base, 0, IntPtr.Zero, 0) == 0) return "SymLoadModuleEx failed " + Marshal.GetLastWin32Error();
        LayOut(File.ReadAllBytes(exe));
        return "ok";
    }

    static void LayOut(byte[] file) {
        int pe = BitConverter.ToInt32(file, 0x3c);
        int count = BitConverter.ToUInt16(file, pe + 6);
        int optSize = BitConverter.ToUInt16(file, pe + 20);
        uint sizeOfImage = BitConverter.ToUInt32(file, pe + 24 + 56);
        image = new byte[sizeOfImage];
        sections.Clear();
        int table = pe + 24 + optSize;
        for (int i = 0; i < count; i++) {
            int s = table + 40 * i;
            uint vsize = BitConverter.ToUInt32(file, s + 8), rva = BitConverter.ToUInt32(file, s + 12);
            uint rawSize = BitConverter.ToUInt32(file, s + 16), raw = BitConverter.ToUInt32(file, s + 20);
            uint flags = BitConverter.ToUInt32(file, s + 36);
            Array.Copy(file, raw, image, rva, Math.Min(rawSize, Math.Min(vsize == 0 ? rawSize : vsize, sizeOfImage - rva)));
            sections.Add(new uint[] { rva, Math.Max(vsize, rawSize), flags });
        }
    }

    // The TLS directory: template range, zero fill, characteristics, the template's bytes (at most 64: the
    // C runtime's own thread-local words) and where dbghelp puts _Init_thread_epoch.
    public static string Tls(string exe) {
        byte[] file = File.ReadAllBytes(exe);
        int pe = BitConverter.ToInt32(file, 0x3c);
        ulong imageBase = BitConverter.ToUInt64(file, pe + 24 + 24);
        uint dirRva = BitConverter.ToUInt32(file, pe + 24 + 112 + 9 * 8);
        if (dirRva == 0) return "no TLS directory";
        ulong start = BitConverter.ToUInt64(image, (int)dirRva), end = BitConverter.ToUInt64(image, (int)dirRva + 8);
        ulong index = BitConverter.ToUInt64(image, (int)dirRva + 16), callbacks = BitConverter.ToUInt64(image, (int)dirRva + 24);
        uint zeroFill = BitConverter.ToUInt32(image, (int)dirRva + 32), chars = BitConverter.ToUInt32(image, (int)dirRva + 36);
        var text = new StringBuilder();
        text.Append("template=0x" + (start - imageBase).ToString("x") + "..0x" + (end - imageBase).ToString("x") +
                    " size=" + (end - start) + " zerofill=" + zeroFill + " chars=0x" + chars.ToString("x") +
                    " index=0x" + (index - imageBase).ToString("x") + " callbacks=0x" + (callbacks == 0 ? "0" : (callbacks - imageBase).ToString("x")) + " bytes=");
        for (ulong i = 0; i < Math.Min(end - start, 64UL); i++) text.Append(image[(int)(start - imageBase + i)].ToString("x2"));
        var info = new SYMBOL_INFOW();
        info.SizeOfStruct = 88;
        info.MaxNameLen = 1024;
        if (SymFromNameW(process, "_Init_thread_epoch", ref info))
            text.Append(" _Init_thread_epoch: address=0x" + info.Address.ToString("x") + " flags=0x" + info.Flags.ToString("x") + " size=" + info.Size);
        else text.Append(" _Init_thread_epoch: not found");
        return text.ToString();
    }

    static bool InData(long rva, int length) {
        foreach (var s in sections)
            if (rva >= s[0] && rva + length <= s[0] + s[1]) return (s[2] & 0x20000000) == 0;  // not executable
        return false;
    }

    static string GuidAt(long rva) {
        byte[] b = new byte[16];
        Array.Copy(image, rva, b, 0, 16);
        return new System.Guid(b).ToString();
    }

    public static string Name(ulong rva) {
        var info = new SYMBOL_INFOW();
        info.SizeOfStruct = 88;
        info.MaxNameLen = 1024;
        ulong displacement;
        if (!SymFromAddrW(process, Base + rva, out displacement, ref info)) return "?";
        return info.Name + "+0x" + displacement.ToString("x");
    }

    static readonly string[] Prefixes = { "XAsync", "XTaskQueue", "XThread", "XUser", "XGameSave", "XSystem",
        "XPackage", "XGameUi", "XGameRuntime", "XError", "XStore", "XNetworking", "XLauncher", "XGame",
        "XAccessibility", "XDisplay", "XPersistentLocalStorage", "XAppCapture", "XSpeech", "XClosedCaption",
        "XLaunchUri", "XNotification", "XWindows", "XAppBroadcast", "XHighContrast", "XGameStreaming",
        "XGameInvite", "XGameEvent", "XGameProtocol", "XGameActivation", "XGameRuntimeFeature", "XGameUI",
        "XUserDevice", "XSpeechSynthesizer", "XDisplayTimeout", "QueryApiImpl", "InitializeApiImpl" };

    static readonly string[] Regs = { "rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
                                      "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15" };

    // "name<TAB>rva<TAB>size" for every symbol matching a dbghelp mask (data and functions).
    public static string[] Find(string mask) {
        var rows = new List<string>();
        EnumCallback callback = (IntPtr info, uint size, IntPtr context) => {
            uint symSize = (uint)Marshal.ReadInt32(info, 28);
            ulong address = (ulong)Marshal.ReadInt64(info, 56);
            int nameLen = Marshal.ReadInt32(info, 76);
            string name = Marshal.PtrToStringUni(new IntPtr(info.ToInt64() + 84), Math.Max(0, Math.Min(nameLen, 1000)));
            if (address >= Base) rows.Add(name + "\t0x" + (address - Base).ToString("x") + "\t" + symSize);
            return rows.Count < 400;
        };
        SymEnumSymbolsW(process, Base, mask, callback, IntPtr.Zero);
        GC.KeepAlive(callback);
        return rows.ToArray();
    }

    // The bytes of the named function (hex) and every exact data symbol a rel32 inside it could name
    // (offset of the rel32, target RVA, symbol), for disassembly next to its references.
    public static string[] Dump(string name) {
        var info = new SYMBOL_INFOW();
        info.SizeOfStruct = 88;
        info.MaxNameLen = 1024;
        if (!SymFromNameW(process, name, ref info)) return new string[] { "# " + name + " not found" };
        long start = (long)(info.Address - Base), size = Math.Min(info.Size == 0 ? 256u : info.Size, 4096u);
        var rows = new List<string>();
        var hex = new StringBuilder();
        for (long i = 0; i < size; i++) hex.Append(image[start + i].ToString("x2"));
        rows.Add("dump " + name + " rva=0x" + start.ToString("x") + " size=" + size + " " + hex);
        for (long o = start; o + 4 <= start + size; o++) {
            int disp = BitConverter.ToInt32(image, (int)o);
            foreach (int extra in new int[] { 0, 1, 4 }) {
                long target = o + 4 + extra + disp;
                if (target <= 0 || target >= image.Length || !InData(target, 1)) continue;
                string n = Name((ulong)target);
                if (n.EndsWith("+0x0")) rows.Add("ref +0x" + (o - start).ToString("x") + " (+" + extra + ") 0x" + target.ToString("x") + " " + n);
            }
        }
        return rows.ToArray();
    }

    // One TSV row per function: name, rva, size, leas (reg=guid), indirect (call|jmp reg+disp), direct callees.
    public static string[] Scan() {
        var rows = new List<string>();
        var seen = new HashSet<ulong>();
        EnumCallback callback = (IntPtr info, uint size, IntPtr context) => {
            // SYMBOL_INFOW: Size at 28, Address at 56, Tag at 72, NameLen at 76, Name at 84.
            uint symSize = (uint)Marshal.ReadInt32(info, 28);
            ulong address = (ulong)Marshal.ReadInt64(info, 56);
            uint tag = (uint)Marshal.ReadInt32(info, 72);
            int nameLen = Marshal.ReadInt32(info, 76);
            string name = Marshal.PtrToStringUni(new IntPtr(info.ToInt64() + 84), Math.Max(0, Math.Min(nameLen, 1000)));
            bool match = false;
            foreach (var p in Prefixes) if (name.StartsWith(p)) { match = true; break; }
            if (tag != 5 && tag != 10) return true;  // SymTagFunction, SymTagPublicSymbol
            if (symSize == 0) symSize = 192;
            if (!match || symSize > 4096 || address < Base || !seen.Add(address)) return true;
            long start = (long)(address - Base), end = Math.Min(start + symSize, image.Length);
            var leas = new List<string>(); var indirect = new List<string>(); var direct = new List<string>();
            for (long o = start; o + 2 < end; o++) {
                byte b0 = image[o], b1 = image[o + 1], b2 = image[o + 2];
                // lea r64, [rip+d32]: REX.W (48/4C) 8D modrm(mod=00, rm=101)
                if ((b0 == 0x48 || b0 == 0x4C) && b1 == 0x8D && (b2 & 0xC7) == 0x05 && o + 7 <= end) {
                    long target = o + 7 + BitConverter.ToInt32(image, (int)o + 3);
                    int reg = ((b2 >> 3) & 7) + (b0 == 0x4C ? 8 : 0);
                    if (InData(target, 16)) leas.Add(Regs[reg] + "=" + GuidAt(target) + "@0x" + (target).ToString("x"));
                }
                // call/jmp [reg+disp]: (41|48|49)? FF modrm(mod=01|10, reg=2|4, rm!=100)
                int at = (int)o; int rex = 0;
                if (b0 == 0x41 || b0 == 0x48 || b0 == 0x49) { rex = b0; at++; }
                if (at + 2 < end && image[at] == 0xFF) {
                    byte m = image[at + 1]; int mod = m >> 6, op = (m >> 3) & 7, rm = m & 7;
                    if ((mod == 1 || mod == 2) && (op == 2 || op == 4) && rm != 4) {
                        long disp = mod == 1 ? (sbyte)image[at + 2] : (at + 6 <= end ? BitConverter.ToInt32(image, at + 2) : -1);
                        if (disp >= 0 && disp % 8 == 0)
                            indirect.Add((op == 2 ? "call " : "jmp ") + Regs[rm + ((rex & 1) != 0 ? 8 : 0)] + "+0x" + disp.ToString("x") + "@+0x" + (o - start).ToString("x"));
                    }
                }
                // mov r64, [reg+disp]: REX.W (48/49/4C/4D) 8B modrm(mod=01|10, rm!=100). With CFG the vtable
                // slot is loaded into rax and called through _guard_dispatch_icall.
                if ((b0 & 0xF8) == 0x48 && (b0 & 0x2) == 0 && b1 == 0x8B && o + 3 < end) {
                    int mod = b2 >> 6, rm = b2 & 7, reg = ((b2 >> 3) & 7) + ((b0 & 4) != 0 ? 8 : 0);
                    if ((mod == 1 || mod == 2) && rm != 4) {
                        long disp = mod == 1 ? (sbyte)image[o + 3] : (o + 7 <= end ? BitConverter.ToInt32(image, (int)o + 3) : -1);
                        if (disp >= 0 && disp % 8 == 0 && disp < 0x800)
                            indirect.Add("ld " + Regs[reg] + "<-" + Regs[rm + ((b0 & 1) != 0 ? 8 : 0)] + "+0x" + disp.ToString("x") + "@+0x" + (o - start).ToString("x"));
                    }
                }
                // call rel32
                if (b0 == 0xE8 && o + 5 <= end) {
                    long target = o + 5 + BitConverter.ToInt32(image, (int)o + 1);
                    if (target >= 0 && target < image.Length) direct.Add("{" + target + "}@+0x" + (o - start).ToString("x"));
                }
            }
            rows.Add(name + "\t0x" + start.ToString("x") + "\t" + symSize + "\t" + string.Join(" ", leas) + "\t" +
                     string.Join(" ", indirect) + "\t" + string.Join(" ", direct));
            return true;
        };
        SymEnumSymbolsW(process, Base, "*", callback, IntPtr.Zero);
        GC.KeepAlive(callback);
        // Name the direct callees after the enumeration (dbghelp is not reentrant).
        var pattern = new System.Text.RegularExpressions.Regex(@"\{(\d+)\}");
        for (int i = 0; i < rows.Count; i++)
            rows[i] = pattern.Replace(rows[i], m => Name(ulong.Parse(m.Groups[1].Value)));
        rows.Sort(StringComparer.Ordinal);
        return rows.ToArray();
    }
}
"@
try { Add-Type -TypeDefinition $source -Language CSharp } catch { Write-Output "add-type failed: $_" }
foreach ($candidate in @("C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\dbghelp.dll",
                         "C:\Program Files\Windows Kits\10\Debuggers\x64\dbghelp.dll")) {
    if (Test-Path $candidate) { [XgrSym]::PreferDbgHelp($candidate); Write-Output "dbghelp $candidate"; break }
}

function Exe-Of($name) {
    $dir = Join-Path $Samples $name
    if (-not (Test-Path $dir)) { return $null }
    return Get-ChildItem -File -Path $dir -Filter *.exe | Select-Object -First 1
}

# 0. Magic statics in a /MD title of our own, under Windows and under x2w_launch.
$statics = Join-Path $Build "x2w_xgr_statics_title.exe"
if (Test-Path $statics) {
    $rows = @()
    foreach ($how in "windows", "x2w_launch") {
        $file = Join-Path $Out "statics-$how.txt"
        if ($how -eq "windows") {
            $p = Start-Process -FilePath $statics -WindowStyle Hidden -PassThru -RedirectStandardOutput $file
        } else {
            $p = Start-Process -FilePath $launcher -WindowStyle Hidden -PassThru -RedirectStandardOutput $file `
                -RedirectStandardError (Join-Path $Out "statics-launch-err.txt") `
                -ArgumentList @("--shims", "`"$shims`"", "--log", "`"$(Join-Path $Out 'statics-run.log')`"", "--timeout", "20", "`"$statics`"")
        }
        $null = $p.Handle
        if (-not $p.WaitForExit(40000)) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
        $rows += "$how exit=0x$('{0:x}' -f $p.ExitCode) $((Get-Content $file -ErrorAction SilentlyContinue) -join ' ')"
    }
    $opened = [XgrSym]::Open($statics)
    $rows += "tls $([XgrSym]::Tls($statics))"
    $rows | Set-Content (Join-Path $Out "statics.txt")
    $rows | ForEach-Object { Write-Output "statics $_" }
}

$summary = @("sample`tmode`texit`tseconds`tlast-lines")
foreach ($name in $Run.Split(",")) {
    $exe = Exe-Of $name
    if (-not $exe) { $summary += "$name`t-`tmissing`t0`t"; continue }
    foreach ($mode in $Modes.Split(",")) {
        $target = Join-Path $Out "$name-$mode"
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        $log = Join-Path $target "run.log"
        $err = Join-Path $target "stderr-full.txt"
        $outFile = Join-Path $target "stdout.txt"
        # Diagnostics for the title's C++ throws (X2W_XGR_PEEK, src/xgr/xgr_gateway.cpp): the magic-static
        # objects and guards of the UITK element class IDs, the C runtime's global epoch and _tls_index.
        $null = [XgrSym]::Open($exe.FullName)
        $found = @([XgrSym]::Find("*ClassID*")) + @([XgrSym]::Find("_Init_global_epoch")) + @([XgrSym]::Find("_tls_index"))
        $found | Set-Content (Join-Path $target "peek-symbols.tsv")
        $dumps = @()
        foreach ($fn in @("ATG::UITK::UIStaticText::ClassID", "ATG::UITK::UIPanel::ClassID", "_Init_thread_header", "_Init_thread_footer")) {
            $dumps += [XgrSym]::Dump($fn)
        }
        $dumps | Set-Content (Join-Path $target "dumps.txt")
        $peek = @()
        foreach ($row in $found) {
            $cols = $row.Split("`t")
            if ($cols[0] -ne "_tls_index" -and ($cols[0] -match "TSS0|::id|_Init_global_epoch")) { $peek += "$($cols[1].Substring(2)):$('{0:x}' -f [math]::Max(8, [math]::Min([int]$cols[2], 32)))" }
            if ($cols[0] -eq "_tls_index") { $env:X2W_XGR_TLS_INDEX = $cols[1].Substring(2) }
        }
        $env:X2W_XGR_PEEK = ($peek | Select-Object -First 40) -join ","
        if (-not $env:X2W_XGR_PEEK) { $env:X2W_XGR_PEEK = "0:8" }
        $start = Get-Date
        $p = Start-Process -FilePath $launcher -WorkingDirectory $exe.DirectoryName -WindowStyle Hidden -PassThru `
            -RedirectStandardError $err -RedirectStandardOutput $outFile `
            -ArgumentList @("--shims", "`"$shims`"", "--xgr", $mode, "--log", "`"$log`"", "--timeout", "$Timeout", "`"$($exe.FullName)`"")
        $null = $p.Handle
        if (-not $p.WaitForExit(($Timeout + 30) * 1000)) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            $code = "killed"
        } else {
            $code = "0x{0:x}" -f $p.ExitCode
        }
        $seconds = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)
        if (Test-Path $err) {
            Get-Content $err | Where-Object { $_.StartsWith("[x2w] ") -and -not $_.StartsWith("[x2w] import ") } |
                Select-Object -First 4000 | Set-Content (Join-Path $target "stderr.txt")
            Remove-Item $err -Force
        }
        if (Test-Path $outFile) { Remove-Item $outFile -Force }
        Set-Content (Join-Path $target "exit.txt") "$code $seconds s"
        $tail = if (Test-Path $log) { (Get-Content $log | Select-Object -Last 2) -join " | " } else { "no log" }
        $summary += "$name`t$mode`t$code`t$seconds`t$tail"

        # Callers -> function names through our own build's PDB.
        if (Test-Path $log) {
            $stem = $exe.BaseName.ToLower() + ".exe"
            $rvas = Select-String -Path $log -Pattern ([regex]::Escape($stem) + '\+0x([0-9a-f]+)') -AllMatches |
                ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
            $opened = [XgrSym]::Open($exe.FullName)
            $rows = @("# $opened")
            foreach ($rva in $rvas) { $rows += "0x$rva`t$([XgrSym]::Name([Convert]::ToUInt64($rva, 16)))" }
            $rows | Set-Content (Join-Path $target "callers.tsv")
        }
    }
}
$summary | Set-Content (Join-Path $Out "summary.tsv")
$summary | ForEach-Object { Write-Output $_ }

foreach ($name in $Scan.Split(",")) {
    $exe = Exe-Of $name
    if (-not $exe) { continue }
    $opened = [XgrSym]::Open($exe.FullName)
    $rows = @("# $opened", "# tls $([XgrSym]::Tls($exe.FullName))", "function`trva`tsize`tleas`tindirect`tdirect")
    try { $rows += [XgrSym]::Scan() } catch { $rows += "# scan failed: $_" }
    $rows | Set-Content (Join-Path $Out "thunks-$name.tsv")
    Write-Output "thunks $name $($rows.Count - 2) $opened"
}

if (Test-Path $Gdk) {
    $hits = Get-ChildItem -Recurse -File -Path $Gdk -Include *.h, *.hpp, *.idl, *.inl -ErrorAction SilentlyContinue |
        Select-String -Pattern "QueryApiImpl|InitializeApiImpl|XErrorReport" -ErrorAction SilentlyContinue |
        Select-Object -First 300 |
        ForEach-Object { "$($_.Path.Substring($Gdk.Length))`t$($_.LineNumber)`t$($_.Line.Trim().Substring(0, [math]::Min(200, $_.Line.Trim().Length)))" }
    $libs = Get-ChildItem -Recurse -File -Path $Gdk -Filter "xgameruntime*.lib" -ErrorAction SilentlyContinue |
        ForEach-Object { "lib`t$($_.FullName.Substring($Gdk.Length))`t$($_.Length)" }
    (@("# headers under $Gdk mentioning the interface entry points") + $hits + $libs) | Set-Content (Join-Path $Out "gdk-headers.txt")
    Write-Output "gdk-headers $($hits.Count) lines, $($libs.Count) libs"
} else {
    Set-Content (Join-Path $Out "gdk-headers.txt") "# no GDK at $Gdk"
}
exit 0
