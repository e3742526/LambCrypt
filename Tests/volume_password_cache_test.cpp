#include "Crypto/cpu.h"
#include "Volume/Pkcs5Kdf.h"
#include "Volume/Volume.h"
#include "Volume/VolumePasswordCache.h"
#include <atomic>
#include <iostream>
#include <thread>

using namespace VeraCrypt;

int main (int argc, char **argv)
{
	if (argc != 2)
		return 2;

	const uint8 fixture[] = { 't', 'e', 's', 't' };
	const VolumePassword password (fixture, sizeof (fixture));
	std::atomic<bool> start (false);
	bool valid = true;

	// A mount thread can store a password while the GUI timer reads the cache.
	std::thread mount ([&] () {
		while (!start.load())
			std::this_thread::yield();
		for (int iteration = 0; iteration < 1000; ++iteration)
			VolumePasswordCache::Store (password);
	});
	start.store (true);
	for (int iteration = 0; iteration < 1000; ++iteration)
	{
		VolumePasswordCache::IsEmpty();
		const CachedPasswordList cached = VolumePasswordCache::GetPasswords();
		if (cached.size() > 1 || (!cached.empty() && *cached.front() != password))
			valid = false;
		VolumePasswordCache::Clear();
	}
	mount.join();

	VolumePasswordCache::Store (password);
	const CachedPasswordList cached = VolumePasswordCache::GetPasswords();
	VolumePasswordCache::Clear();
	if (!valid || cached.size() != 1 || *cached.front() != password
		|| !VolumePasswordCache::IsEmpty() || !VolumePasswordCache::GetPasswords().empty())
	{
		std::cerr << "Volume password cache snapshot or wipe failed\n";
		return 1;
	}

#if defined(CRYPTOPP_CPUID_AVAILABLE)
	DetectX86Features();
#elif CRYPTOPP_BOOL_ARMV8
	DetectArmFeatures();
#endif
	Volume volume;
	volume.Open (VolumePath (argv[1]), false, cached.front(), 0, Pkcs5Kdf::GetAlgorithm (L"HMAC-SHA-512"),
		shared_ptr <KeyfileList> (), false, VolumeProtection::ReadOnly);
	volume.Close();
	std::cout << "PASS: concurrent cache access, cache wipe, and VeraCrypt fixture opened using caller-owned snapshot\n";
}
