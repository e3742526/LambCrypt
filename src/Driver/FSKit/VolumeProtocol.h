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
		shared_ptr <VolumeInfo> ReadVolumeControl (const string &endpoint);
		void FlushVolumeControl (const string &endpoint, const VolumeInfo &volume);

		// Serve one request with separate deadlines for receiving it and
		// sending the reply. The caller keeps the volume alive and serializes
		// its operations.
		void ServeRequest (int connection, uid_t owner, Volume &volume, VolumeInfo &info,
			const std::array <uint8, 16> &identifier);
	}
}

#endif
