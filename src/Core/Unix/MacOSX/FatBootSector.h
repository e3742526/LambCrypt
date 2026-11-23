/*
 Copyright (c) 2026 LambCrypt contributors
 Governed by the Apache License 2.0, the full text of which is contained in
 the file License.txt included in LambCrypt binary and source code
 distribution packages.
*/

#ifndef TC_HEADER_Core_FatBootSector
#define TC_HEADER_Core_FatBootSector

#include <cstddef>
#include <cstdint>

namespace VeraCrypt
{
	// FAT type is determined by the cluster count, not the informational
	// filesystem name in the extended BIOS parameter block.
	inline int GetFatBootSectorType (const uint8_t *boot, size_t length, uint64_t imageSize)
	{
		if (length < 512 || boot[510] != 0x55 || boot[511] != 0xaa
			|| (boot[0] != 0xe9 && !(boot[0] == 0xeb && boot[2] == 0x90)))
			return 0;

		const auto read16 = [boot] (size_t offset) -> uint32_t {
			return boot[offset] | (uint32_t (boot[offset + 1]) << 8);
		};
		const auto read32 = [&read16] (size_t offset) -> uint32_t {
			return read16 (offset) | (read16 (offset + 2) << 16);
		};
		const uint32_t sectorSize = read16 (11);
		const uint32_t clusterSize = boot[13];
		const uint32_t reserved = read16 (14);
		const uint32_t fats = boot[16];
		const uint32_t rootEntries = read16 (17);
		const uint32_t sectors16 = read16 (19);
		const uint32_t fatSectors16 = read16 (22);
		const uint64_t sectors = sectors16 ? sectors16 : read32 (32);
		const uint64_t fatSectors = fatSectors16 ? fatSectors16 : read32 (36);
		if (sectorSize < 512 || sectorSize > 4096 || (sectorSize & (sectorSize - 1))
			|| clusterSize == 0 || clusterSize > 128 || (clusterSize & (clusterSize - 1))
			|| reserved == 0 || (fats != 1 && fats != 2) || fatSectors == 0
			|| (boot[21] != 0xf0 && boot[21] < 0xf8)
			|| sectors > imageSize / sectorSize)
			return 0;

		const uint64_t firstData = reserved + fats * fatSectors + (rootEntries * 32 + sectorSize - 1) / sectorSize;
		if (firstData >= sectors)
			return 0;
		const uint64_t clusters = (sectors - firstData) / clusterSize;
		const int type = clusters < 4085 ? 12 : clusters < 65525 ? 16 : 32;
		if (clusters == 0 || (clusters + 2) * type > fatSectors * sectorSize * 8)
			return 0;
		if (type == 32)
		{
			const uint32_t rootCluster = read32 (44);
			if (rootEntries != 0 || fatSectors16 != 0 || sectors16 != 0
				|| read16 (42) != 0 || rootCluster < 2 || rootCluster >= clusters + 2
				|| clusters > 0x0fffffee)
				return 0;
		}
		else if (rootEntries == 0 || fatSectors16 == 0)
			return 0;
		return type;
	}
}

#endif
