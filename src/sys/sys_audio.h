// XAudio2: forward the console XAudio2 entry to the PC xaudio2_9.dll, and classify the wave formats a title
// submits so that XMA2 can be detected and logged (decode comes later); PCM, IEEE float and MS ADPCM pass through.
//
// Facts used, all public: XAudio2 on Windows 10 and later is xaudio2_9.dll with the XAudio2Create export (XAudio2
// Learn pages); WAVEFORMATEX format tags 0x0001 PCM, 0x0002 MS ADPCM, 0x0003 IEEE float, 0xFFFE extensible
// (mmreg.h); XMA1 0x0165 and XMA2 0x0166 and the XMA2WAVEFORMATEX layout (xma2defs.h in the XAudio2 redist headers
// and DirectXTK, MIT). The console-side XAudio2 extensions are not public; calls this module does not handle are
// logged by the gateway, not guessed.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

namespace x2w_sys::audio {

enum class Format { Unknown, Pcm, AdPcm, Float, Xma1, Xma2, Other };

struct FormatInfo {
    Format format = Format::Unknown;
    uint16_t tag = 0;       // effective tag (the sub-format for WAVE_FORMAT_EXTENSIBLE)
    uint16_t channels = 0;
    uint32_t sample_rate = 0;
    uint16_t bits = 0;
    // XMA2 only (valid when format == Xma2 and the extra data is complete):
    bool xma2_complete = false;
    uint16_t xma2_streams = 0;
    uint32_t xma2_samples_encoded = 0;
    uint32_t xma2_bytes_per_block = 0;
    uint16_t xma2_block_count = 0;
    uint32_t xma2_loop_begin = 0, xma2_loop_length = 0;
    uint8_t xma2_loop_count = 0;
};

const char* format_name(Format f);
// `wfx` points at a WAVEFORMATEX (or larger); `available` is the byte count readable at it (0: trust cbSize).
FormatInfo classify(const void* wfx, size_t available = 0);

enum class Decision { PassThrough, DecodeRequired, Reject };
// Logs each distinct format once. XMA1 and XMA2 return DecodeRequired (the gateway fails the submit with a logged
// reason until the decoder exists); unknown tags return Reject.
Decision check_format(const void* wfx, size_t available = 0);

struct Stats {
    uint64_t pcm = 0, adpcm = 0, flt = 0, xma = 0, rejected = 0;
};
Stats& stats();

// Loads the PC runtime (xaudio2_9.dll, or `override_dll` / env X2W_XAUDIO2_DLL) and returns its XAudio2Create.
using XAudio2CreateFn = HRESULT(WINAPI*)(void** out, UINT32 flags, UINT32 processor);
XAudio2CreateFn resolve_create(const char* override_dll = nullptr);
void reset_for_test();
void apply_config_line(const std::string& key, const std::string& value);

}  // namespace x2w_sys::audio

extern "C" {
// Console-facing entry, same shape as the public XAudio2Create(IXAudio2** out, UINT32 Flags, XAUDIO2_PROCESSOR).
// Flags are passed through; a processor of 0xFFFFFFFF becomes 0, the PC default (XAUDIO2_USE_DEFAULT_PROCESSOR).
HRESULT WINAPI X2wXAudio2Create(void** out, UINT32 flags, UINT32 processor);
// Format gate for the submit path: 0 pass through, 1 decode required (XMA), 2 reject.
int WINAPI X2wXAudio2CheckFormat(const void* wfx);
}
