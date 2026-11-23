#include "check.h"
#include "sys_audio.h"

#include <cstring>
#include <vector>

using namespace x2w_sys;
using namespace x2w_sys::audio;

namespace {
template <typename T>
void put(std::vector<uint8_t>& v, T x) {
    const auto* p = reinterpret_cast<const uint8_t*>(&x);
    v.insert(v.end(), p, p + sizeof x);
}

std::vector<uint8_t> wfx(uint16_t tag, uint16_t ch, uint32_t rate, uint16_t bits, uint16_t cb = 0) {
    std::vector<uint8_t> v;
    put<uint16_t>(v, tag);
    put<uint16_t>(v, ch);
    put<uint32_t>(v, rate);
    put<uint32_t>(v, rate * ch * bits / 8);
    put<uint16_t>(v, static_cast<uint16_t>(ch * bits / 8));
    put<uint16_t>(v, bits);
    put<uint16_t>(v, cb);
    return v;
}

std::vector<uint8_t> xma2() {
    auto v = wfx(0x0166, 2, 48000, 16, 34);
    put<uint16_t>(v, 1);          // NumStreams
    put<uint32_t>(v, 3);          // ChannelMask
    put<uint32_t>(v, 96000);      // SamplesEncoded
    put<uint32_t>(v, 2048);       // BytesPerBlock
    put<uint32_t>(v, 0);          // PlayBegin
    put<uint32_t>(v, 96000);      // PlayLength
    put<uint32_t>(v, 1000);       // LoopBegin
    put<uint32_t>(v, 5000);       // LoopLength
    put<uint8_t>(v, 2);           // LoopCount
    put<uint8_t>(v, 4);           // EncoderVersion
    put<uint16_t>(v, 12);         // BlockCount
    return v;
}
}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) { std::fprintf(stderr, "usage: sys_audio_check <fake_runtime.dll>\n"); return 2; }
    chk::capture();
    reset_for_test();

    // ---- classification -------------------------------------------------------------------------------
    {
        auto pcm = wfx(1, 2, 48000, 16);
        FormatInfo f = classify(pcm.data(), pcm.size());
        CHECK(f.format == Format::Pcm && f.channels == 2 && f.sample_rate == 48000 && f.bits == 16);
        auto adpcm = wfx(2, 2, 44100, 4, 32);
        adpcm.resize(adpcm.size() + 32);
        CHECK(classify(adpcm.data(), adpcm.size()).format == Format::AdPcm);
        auto flt = wfx(3, 1, 48000, 32);
        CHECK(classify(flt.data(), flt.size()).format == Format::Float);
        // Extensible with a PCM sub-format: tag is the first word of the sub-format GUID (at +6 of the extra bytes).
        auto ext = wfx(0xFFFE, 6, 48000, 24, 22);
        put<uint16_t>(ext, 24);   // valid bits
        put<uint32_t>(ext, 0x3F); // channel mask
        put<uint16_t>(ext, 1);    // sub-format Data1 low word: PCM
        for (int i = 0; i < 14; ++i) ext.push_back(0);
        CHECK(classify(ext.data(), ext.size()).format == Format::Pcm);
        CHECK(classify(ext.data(), ext.size()).tag == 1);
        auto x2 = xma2();
        f = classify(x2.data(), x2.size());
        CHECK(f.format == Format::Xma2 && f.xma2_complete);
        CHECK(f.xma2_streams == 1 && f.xma2_samples_encoded == 96000 && f.xma2_bytes_per_block == 2048);
        CHECK(f.xma2_block_count == 12 && f.xma2_loop_begin == 1000 && f.xma2_loop_length == 5000 && f.xma2_loop_count == 2);
        // Truncated XMA2 extra data: still XMA2, not complete.
        f = classify(x2.data(), x2.size() - 10);
        CHECK(f.format == Format::Xma2 && !f.xma2_complete);
        auto x1 = wfx(0x0165, 2, 44100, 16, 0);
        CHECK(classify(x1.data(), x1.size()).format == Format::Xma1);
        auto odd = wfx(0x1234, 2, 44100, 16);
        CHECK(classify(odd.data(), odd.size()).format == Format::Other);
        CHECK(classify(nullptr).format == Format::Unknown);
        CHECK(classify(pcm.data(), 4).format == Format::Unknown);
    }

    // ---- decisions and logging --------------------------------------------------------------------------
    {
        auto pcm = wfx(1, 2, 48000, 16);
        auto adpcm = wfx(2, 2, 44100, 4, 32);
        adpcm.resize(adpcm.size() + 32);
        auto x2 = xma2();
        auto odd = wfx(0x1234, 2, 44100, 16);
        CHECK(check_format(pcm.data()) == Decision::PassThrough);
        CHECK(check_format(pcm.data()) == Decision::PassThrough);
        CHECK(check_format(adpcm.data()) == Decision::PassThrough);
        CHECK(check_format(x2.data()) == Decision::DecodeRequired);
        CHECK(check_format(x2.data()) == Decision::DecodeRequired);
        CHECK(check_format(odd.data()) == Decision::Reject);
        CHECK_EQ(chk::count("PCM 2 ch 48000 Hz 16 bit passes through"), 1);  // logged once, used twice
        CHECK_EQ(chk::count("XMA2 detected"), 1);
        CHECK_EQ(chk::count("12 blocks of 2048 bytes"), 1);
        CHECK_EQ(chk::count("unsupported wave format tag 0x1234"), 1);
        CHECK_EQ(stats().pcm, 2u);
        CHECK_EQ(stats().xma, 2u);
        CHECK_EQ(stats().rejected, 1u);
        CHECK_EQ(X2wXAudio2CheckFormat(pcm.data()), 0);
        CHECK_EQ(X2wXAudio2CheckFormat(x2.data()), 1);
        CHECK_EQ(X2wXAudio2CheckFormat(odd.data()), 2);
    }

    // ---- forwarding to a stand-in runtime: arguments arrive as expected ---------------------------------
    {
        CHECK(resolve_create(argv[1]) != nullptr);
        void* out = nullptr;
        CHECK(X2wXAudio2Create(&out, 2, 0xFFFFFFFFu) == S_OK);
        CHECK_EQ(reinterpret_cast<uintptr_t>(out), 0x100000000ull + 2 * 0x1000 + 0);  // "any" processor became 0
        CHECK(X2wXAudio2Create(&out, 0, 1) == S_OK);
        CHECK_EQ(reinterpret_cast<uintptr_t>(out), 0x100000000ull + 1);
        CHECK(X2wXAudio2Create(nullptr, 0, 0) == E_POINTER);
    }
    reset_for_test();

    // ---- forwarding to the real xaudio2_9.dll ---------------------------------------------------------------
    {
        void* engine = nullptr;
        const HRESULT hr = X2wXAudio2Create(&engine, 0, 0xFFFFFFFFu);
        std::printf("XAudio2Create via xaudio2_9.dll: hr=0x%08lx engine=%p\n", static_cast<unsigned long>(hr), engine);
        CHECK(hr == S_OK && engine != nullptr);
        if (engine) {  // IUnknown::Release is vtable slot 2
            auto** vtbl = *reinterpret_cast<void***>(engine);
            reinterpret_cast<ULONG(STDMETHODCALLTYPE*)(void*)>(vtbl[2])(engine);
        }
    }
    reset_for_test();
    return finish("sys_audio");
}
