#include <cstdint>

extern "C" std::uint32_t crc_step(std::uint32_t crc, std::uint32_t byte)
{
    crc ^= byte;
    for (unsigned bit = 0; bit < 8; ++bit) {
        const auto mask = 0u - (crc & 1u);
        crc = (crc >> 1) ^ (CRC_POLYNOMIAL & mask);
    }
    return crc;
}
