#ifndef TC_HEADER_Driver_FSKit_VolumeProtocol
#define TC_HEADER_Driver_FSKit_VolumeProtocol

#include "Volume/VolumeInfo.h"
#include <array>

namespace VeraCrypt
{
	namespace FSKit
	{
		struct VolumeIdentity
		{
			std::array <uint8, 16> Identifier;
			uint64 SerialInstanceNumber;
		};

		VolumeIdentity NewVolumeIdentity ();

		// Serve one bounded request on a connected local socket. The caller
		// keeps the open volume alive and serializes requests for that volume.
		void ServeRequest (int connection, uid_t owner, Volume &volume, VolumeInfo &info,
			const std::array <uint8, 16> &identifier);
	}
}

#endif
