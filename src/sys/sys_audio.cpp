#include "sys_audio.h"

#include "sys_common.h"

#include <cstdio>
#include <cstring>
#include <vector>
#include <mutex>

namespace x2w_sys::audio {
namespace {
template <typename T>
T rd(const uint8_t* p) { T v; std::memcpy(&v, p, sizeof v); return v; }

std::mutex g_mutex;
HMODULE g_module = nullptr;
XAudio2CreateFn g_create = nullptr;
bool g_resolved = false;
std::string g_override;
Stats g_stats;

// WAVEFORMATEX is 18 bytes (packed): tag u16, channels u16, rate u32, bytes/sec u32, align u16, bits u16, cbSize u16.
struct Wfx {
    uint16_t tag, channels;
    uint32_t rate, bytes_per_sec;
    uint16_t block_align, bits, cb_size;
};
constexpr size_t kWfxSize = 18;
Wfx read_wfx(const uint8_t* p) {
    Wfx w;
    w.tag = rd<uint16_t>(p + 0);
    w.channels = rd<uint16_t>(p + 2);
    w.rate = rd<uint32_t>(p + 4);
    w.bytes_per_sec = rd<uint32_t>(p + 8);
    w.block_align = rd<uint16_t>(p + 12);
    w.bits = rd<uint16_t>(p + 14);
    w.cb_size = rd<uint16_t>(p + 16);
    return w;
}

// XMA2WAVEFORMATEX extra data (34 bytes, cbSize == 34).
struct Xma2Extra {
    uint16_t num_streams;
    uint32_t channel_mask, samples_encoded, bytes_per_block, play_begin, play_length, loop_begin, loop_length;
    uint8_t loop_count, encoder_version;
    uint16_t block_count;
};
constexpr size_t kXma2ExtraSize = 34;

Format from_tag(uint16_t tag) {
    switch (tag) {
        case 0x0001: return Format::Pcm;
        case 0x0002: return Format::AdPcm;
        case 0x0003: return Format::Float;
        case 0x0165: return Format::Xma1;
        case 0x0166: return Format::Xma2;
        default: return Format::Other;
    }
}
}  // namespace

const char* format_name(Format f) {
    switch (f) {
        case Format::Pcm: return "PCM";
        case Format::AdPcm: return "MS-ADPCM";
        case Format::Float: return "IEEE-float";
        case Format::Xma1: return "XMA1";
        case Format::Xma2: return "XMA2";
        case Format::Other: return "other";
        default: return "unknown";
    }
}

FormatInfo classify(const void* wfx, size_t available) {
    FormatInfo info;
    if (!wfx) return info;
    const auto* p = static_cast<const uint8_t*>(wfx);
    if (available && available < kWfxSize) return info;
    const Wfx h = read_wfx(p);
    info.tag = h.tag;
    info.channels = h.channels;
    info.sample_rate = h.rate;
    info.bits = h.bits;
    const size_t total = kWfxSize + h.cb_size;
    const bool readable = !available || available >= total;
    if (h.tag == 0xFFFE) {
        // WAVEFORMATEXTENSIBLE: 22 extra bytes, the sub-format GUID starts at +6 (after Samples and the channel mask); its Data1 low word is the tag.
        if (h.cb_size >= 22 && readable) info.tag = rd<uint16_t>(p + kWfxSize + 6);
        else return info;
    }
    info.format = from_tag(info.tag);
    if (info.format == Format::Xma2 && h.tag == 0x0166 && h.cb_size >= kXma2ExtraSize && readable) {
        const uint8_t* e = p + kWfxSize;
        info.xma2_complete = true;
        info.xma2_streams = rd<uint16_t>(e + 0);
        info.xma2_samples_encoded = rd<uint32_t>(e + 6);
        info.xma2_bytes_per_block = rd<uint32_t>(e + 10);
        info.xma2_loop_begin = rd<uint32_t>(e + 22);
        info.xma2_loop_length = rd<uint32_t>(e + 26);
        info.xma2_loop_count = e[30];
        info.xma2_block_count = rd<uint16_t>(e + 32);
    }
    return info;
}

Stats& stats() { return g_stats; }

Decision check_format(const void* wfx, size_t available) {
    const FormatInfo f = classify(wfx, available);
    char key[64];
    std::snprintf(key, sizeof key, "audiofmt:%d:%u:%u:%u", static_cast<int>(f.format), f.tag, f.channels, f.sample_rate);
    switch (f.format) {
        case Format::Pcm: case Format::AdPcm: case Format::Float:
            if (f.format == Format::Pcm) ++g_stats.pcm; else if (f.format == Format::AdPcm) ++g_stats.adpcm; else ++g_stats.flt;
            log_once(key, "audio: %s %u ch %u Hz %u bit passes through", format_name(f.format), f.channels, f.sample_rate, f.bits);
            return Decision::PassThrough;
        case Format::Xma1: case Format::Xma2:
            ++g_stats.xma;
            if (f.format == Format::Xma2 && f.xma2_complete)
                log_once(key, "audio: XMA2 detected, %u ch %u Hz, %u stream(s), %u samples, %u blocks of %u bytes, loop %u+%u x%u; decode not implemented yet",
                         f.channels, f.sample_rate, f.xma2_streams, f.xma2_samples_encoded, f.xma2_block_count,
                         f.xma2_bytes_per_block, f.xma2_loop_begin, f.xma2_loop_length, f.xma2_loop_count);
            else
                log_once(key, "audio: %s detected, %u ch %u Hz; decode not implemented yet", format_name(f.format), f.channels, f.sample_rate);
            return Decision::DecodeRequired;
        default:
            ++g_stats.rejected;
            log_once(key, "audio: unsupported wave format tag 0x%04x (%u ch %u Hz)", f.tag, f.channels, f.sample_rate);
            return Decision::Reject;
    }
}

XAudio2CreateFn resolve_create(const char* override_dll) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_resolved) return g_create;
    g_resolved = true;
    std::string first = override_dll ? override_dll : (g_override.empty() ? get_env("X2W_XAUDIO2_DLL") : g_override);
    std::vector<std::wstring> names;
    if (!first.empty()) names.push_back(widen(first));
    names.push_back(L"xaudio2_9.dll");
    for (const auto& n : names) {
        HMODULE m = LoadLibraryExW(n.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS | LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (!m) continue;
        auto fn = reinterpret_cast<XAudio2CreateFn>(GetProcAddress(m, "XAudio2Create"));
        if (!fn) { FreeLibrary(m); continue; }
        g_module = m;
        g_create = fn;
        log("audio: forwarding XAudio2Create to %s", narrow(n).c_str());
        return g_create;
    }
    log("audio: no xaudio2_9.dll with XAudio2Create found");
    return nullptr;
}

void reset_for_test() {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_module) FreeLibrary(g_module);
    g_module = nullptr;
    g_create = nullptr;
    g_resolved = false;
    g_stats = {};
}

void apply_config_line(const std::string& key, const std::string& value) {
    if (key == "audio.dll") g_override = value;
}

}  // namespace x2w_sys::audio

extern "C" {
HRESULT WINAPI X2wXAudio2Create(void** out, UINT32 flags, UINT32 processor) {
    if (!out) return E_POINTER;
    *out = nullptr;
    auto fn = x2w_sys::audio::resolve_create();
    if (!fn) return HRESULT_FROM_WIN32(ERROR_MOD_NOT_FOUND);
    if (processor == 0xFFFFFFFFu) {  // "any processor" in older headers: the PC default is 0 (XAUDIO2_USE_DEFAULT_PROCESSOR)
        x2w_sys::log_once("audio:processor", "audio: processor mask 0xffffffff mapped to the PC default processor (0)");
        processor = 0;
    }
    return fn(out, flags, processor);
}

int WINAPI X2wXAudio2CheckFormat(const void* wfx) {
    using x2w_sys::audio::Decision;
    switch (x2w_sys::audio::check_format(wfx)) {
        case Decision::PassThrough: return 0;
        case Decision::DecodeRequired: return 1;
        default: return 2;
    }
}
}
