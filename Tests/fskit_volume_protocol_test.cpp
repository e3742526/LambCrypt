#include "Driver/FSKit/VolumeProtocol.h"
#include "Crypto/cpu.h"
#include "Volume/Pkcs5Kdf.h"
#include <algorithm>
#include <errno.h>
#include <iostream>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

using namespace VeraCrypt;

enum class WriteFault { None, Interrupt, Short, Zero, ShortThenFull, Full };
static WriteFault nextWriteFault = WriteFault::None;
static bool interruptNextRead = false;
static int nextSyncError = 0;

extern "C" int TestFileSync (int fd)
{
	if (nextSyncError != 0)
	{
		errno = nextSyncError;
		nextSyncError = 0;
		return -1;
	}
	return fsync (fd);
}

extern "C" ssize_t TestPositionedRead (int fd, void *data, size_t length, off_t offset)
{
	if (interruptNextRead)
	{
		interruptNextRead = false;
		errno = EINTR;
		return -1;
	}
	return pread (fd, data, length, offset);
}

extern "C" ssize_t TestPositionedWrite (int fd, const void *data, size_t length, off_t offset)
{
	switch (nextWriteFault)
	{
	case WriteFault::Interrupt:
		nextWriteFault = WriteFault::Short;
		errno = EINTR;
		return -1;
	case WriteFault::Zero:
		errno = EACCES;
		return 0;
	case WriteFault::Full:
		errno = ENOSPC;
		return -1;
	case WriteFault::Short:
	case WriteFault::ShortThenFull:
		nextWriteFault = nextWriteFault == WriteFault::ShortThenFull ? WriteFault::Full : WriteFault::None;
		length /= 2;
		break;
	case WriteFault::None:
		break;
	}
	return pwrite (fd, data, length, offset);
}

int main (int argc, char **argv)
{
	if (argc == 2 && string (argv[1]) == "--check-buffer-erase")
	{
		SecureBuffer buffer;
		buffer.Erase();
		for (size_t count : {1, 31, 128 * 1024 + 1, 1024 * 1024})
		{
			buffer.Allocate (count);
			std::fill_n (buffer.Ptr(), count, 0xa5);
			buffer.Erase();
			if (std::any_of (buffer.Ptr(), buffer.Ptr() + count, [] (uint8 byte) { return byte != 0; }))
				return 1;
		}
		return 0;
	}
	if (argc == 6 && string (argv[1]) == "--flush")
	{
		try
		{
			VolumeInfo target;
			target.SerialInstanceNumber = std::stoull (argv[3]);
			target.Path = VolumePath (argv[4]);
			target.SlotNumber = std::stoul (argv[5]);
			FSKit::FlushVolumeControl (argv[2], target);
			return 0;
		}
		catch (const SystemException &error) { return error.GetErrorCode() == ESTALE ? 4 : 1; }
		catch (const ParameterIncorrect &) { return 5; }
		catch (...) { return 1; }
	}
	if (argc == 3 && string (argv[1]) == "--control")
	{
		try
		{
			const auto info = FSKit::ReadVolumeControl (argv[2]);
			std::cout << info->SerialInstanceNumber << ' ' << info->TotalDataRead << '\n';
			return 0;
		}
		catch (const TimeOut &) { return 3; }
		catch (const SystemException &error) { return error.GetErrorCode() == ESTALE ? 4 : 1; }
		catch (...) { return 1; }
	}
	if (argc != 4 && argc != 5)
		return 2;
	const string mode = argc == 5 ? argv[4] : "";
	const bool readOnly = argc == 4 || mode == "read-interrupted";
	if (!readOnly)
	{
		if (mode == "write-interrupted") nextWriteFault = WriteFault::Interrupt;
		else if (mode == "write-zero") nextWriteFault = WriteFault::Zero;
		else if (mode == "write-full") nextWriteFault = WriteFault::ShortThenFull;
		else if (mode == "sync-interrupted") nextSyncError = EINTR;
		else if (mode == "sync-error") nextSyncError = EIO;
		else if (mode != "write") return 2;
	}

#if defined(CRYPTOPP_CPUID_AVAILABLE)
	DetectX86Features();
#elif CRYPTOPP_BOOL_ARMV8
	DetectArmFeatures();
#endif

	Volume volume;
	shared_ptr <VolumePassword> password (new VolumePassword (reinterpret_cast <const uint8 *> ("test"), 4));
	volume.Open (VolumePath (argv[1]), false, password, 0, Pkcs5Kdf::GetAlgorithm (L"HMAC-SHA-512"),
		shared_ptr <KeyfileList> (), false, readOnly ? VolumeProtection::ReadOnly : VolumeProtection::None);
	password.reset ();
	interruptNextRead = mode == "read-interrupted";

	const int listener = socket (AF_UNIX, SOCK_STREAM, 0);
	const FSKit::UnixSocketAddress address (argv[2]);
	if (listener < 0 || ::bind (listener, address.Get(), address.Length) != 0
		|| chmod (argv[2], 0600) != 0 || listen (listener, 8) != 0)
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
	unlink (argv[2]);
}
