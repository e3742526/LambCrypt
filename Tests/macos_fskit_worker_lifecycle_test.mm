/*
 Copyright (c) 2026 LambCrypt contributors
 Governed by the Apache License 2.0, the full text of which is contained in
 the file License.txt included in LambCrypt binary and source code
 distribution packages.
*/

#import <Foundation/Foundation.h>
#import <FSKit/FSClient.h>
#undef ERR_SUCCESS
#include "Driver/FSKit/FSKitService.h"
#include "Crypto/cpu.h"
#include "Volume/Pkcs5Kdf.h"
#include <fcntl.h>
#include <iostream>
#include <sys/mount.h>
#include <unistd.h>

namespace
{
	std::string FixtureMountPoint;
	std::string EvidenceDirectory;

	void Record (const char *event)
	{
		const int fd = open ((EvidenceDirectory + "/" + event).c_str(), O_WRONLY | O_CREAT | O_CLOEXEC, 0600);
		if (fd >= 0)
			close (fd);
	}

	int ObserveFixtureMount (struct statfs **table, int)
	{
		static struct statfs entry = {};
		*table = &entry;
		entry.f_mntonname[0] = '\0';
		if (access ((EvidenceDirectory + "/auxiliary-present").c_str(), F_OK) == 0)
		{
			strlcpy (entry.f_mntonname, FixtureMountPoint.c_str(), sizeof (entry.f_mntonname));
			Record ("auxiliary-observed");
		}
		// getmntinfo returns at least one filesystem on a running Mac.
		return 1;
	}
}

namespace VeraCrypt
{
	namespace FSKit
	{
		bool ObserveRealDiskImageInventory (const DirectoryPath &mountPoint)
		{
			const bool absent = IsDiskImageAbsentAfterAuxiliaryUnmount (mountPoint);
			Record (absent ? "image-absent" : "image-attached");
			return absent;
		}
	}
}

// Inject only the worker's mount-table observation. Keep the real worker,
// protocol, reservations and Disk Images queries in this test executable.
#define getmntinfo ObserveFixtureMount
#define IsDiskImageAbsentAfterAuxiliaryUnmount ObserveRealDiskImageInventory
#include "Driver/FSKit/FSKitService.mm"
#undef IsDiskImageAbsentAfterAuxiliaryUnmount
#undef getmntinfo

using namespace VeraCrypt;

int main (int argc, char **argv)
{
	if (argc == 3 && string (argv[1]) == "--media-id")
	{
		const uint64 media = FSKit::GetMediaIdentity (argv[2]);
		std::cout << media << '\n';
		return media == 0 ? 1 : 0;
	}
	if (argc != 6)
		return 2;
	try
	{
#if CRYPTOPP_BOOL_ARMV8
		DetectArmFeatures();
#endif
		EvidenceDirectory = argv[1];
		FixtureMountPoint = EvidenceDirectory + "/aux";
		const string resource = EvidenceDirectory + "/socket";
		const string endpoint = resource + "/io";
		const string group = argv[2];
		const unsigned int slot = std::stoul (argv[3]);
		const int activation = std::stoi (argv[4]);

		Volume volume;
		auto password = make_shared <VolumePassword> (reinterpret_cast <const uint8 *> (argv[5]), strlen (argv[5]));
		volume.Open (VolumePath (EvidenceDirectory + "/volume.hc"), false, password, 1,
			Pkcs5Kdf::GetAlgorithm (L"HMAC-SHA-512"), shared_ptr <KeyfileList> (), false, VolumeProtection::ReadOnly);
		password.reset();
		const int volumeReservation = FSKit::ReserveVolume (group, volume.GetFile()->GetSystemHandle());
		const int slotReservation = FSKit::TryReserveMount (group, "slot-" + std::to_string (slot));
		const int directory = open (EvidenceDirectory.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
		const int listener = socket (AF_UNIX, SOCK_STREAM, 0);
		const FSKit::UnixSocketAddress address (endpoint);
		if (slotReservation < 0 || directory < 0 || listener < 0
			|| ::bind (listener, address.Get(), address.Length) != 0
			|| chmod (endpoint.c_str(), 0600) != 0 || listen (listener, 8) != 0)
			return 1;
		Record ("socket-ready");

		VolumeInfo info;
		info.SlotNumber = slot;
		const auto identity = FSKit::NewVolumeIdentity();
		info.SerialInstanceNumber = identity.SerialInstanceNumber;
		FSKit::RunWorker (listener, activation, directory, volumeReservation, slotReservation, volume, info,
			identity.Identifier, FixtureMountPoint, resource);
	}
	catch (const std::exception &error)
	{
		std::cerr << error.what() << '\n';
		return 1;
	}
}
