#ifndef TC_HEADER_Driver_FSKit_VolumeProtocol
#define TC_HEADER_Driver_FSKit_VolumeProtocol

#include "Volume/VolumeInfo.h"
#include <array>
#include <sys/socket.h>

namespace VeraCrypt
{
	namespace FSKit
	{
		// Darwin accepts a variable-length local address up to SOCK_MAXADDRLEN.
		struct UnixSocketAddress
		{
			explicit UnixSocketAddress (const string &path);

			const sockaddr *Get () const { return reinterpret_cast <const sockaddr *> (this); }
			uint8_t Length;
			sa_family_t Family;
			char Path[SOCK_MAXADDRLEN - 2];
		};

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
