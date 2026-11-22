#include "Driver/FSKit/VolumeProtocol.h"
#include "Crypto/cpu.h"
#include "Volume/Pkcs5Kdf.h"
#include <iostream>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

using namespace VeraCrypt;

int main (int argc, char **argv)
{
	if (argc != 4 && (argc != 5 || strcmp (argv[4], "write") != 0))
		return 2;

#if defined(CRYPTOPP_CPUID_AVAILABLE)
	DetectX86Features();
#elif CRYPTOPP_BOOL_ARMV8
	DetectArmFeatures();
#endif

	Volume volume;
	shared_ptr <VolumePassword> password (new VolumePassword (reinterpret_cast <const uint8 *> ("test"), 4));
	volume.Open (VolumePath (argv[1]), false, password, 0, Pkcs5Kdf::GetAlgorithm (L"HMAC-SHA-512"),
		shared_ptr <KeyfileList> (), false, argc == 5 ? VolumeProtection::None : VolumeProtection::ReadOnly);
	password.reset ();

	const int listener = socket (AF_UNIX, SOCK_STREAM, 0);
	sockaddr_un address = {};
	address.sun_len = sizeof (address);
	address.sun_family = AF_UNIX;
	if (listener < 0 || strlcpy (address.sun_path, argv[2], sizeof (address.sun_path)) >= sizeof (address.sun_path)
		|| ::bind (listener, reinterpret_cast <sockaddr *> (&address), sizeof (address)) != 0
		|| chmod (address.sun_path, 0600) != 0 || listen (listener, 8) != 0)
		return 2;

	const FSKit::VolumeIdentity identity = FSKit::NewVolumeIdentity ();
	VolumeInfo info;
	info.SlotNumber = 1;
	info.SerialInstanceNumber = identity.SerialInstanceNumber;
	std::cout << info.SerialInstanceNumber << std::endl;

	const int requests = std::stoi (argv[3]);
	for (int index = 0; index < requests; ++index)
	{
		const int connection = accept (listener, nullptr, nullptr);
		if (connection < 0)
			return 2;
		FSKit::ServeRequest (connection, getuid(), volume, info, identity.Identifier);
		close (connection);
	}

	close (listener);
	volume.Close ();
	unlink (address.sun_path);
}
