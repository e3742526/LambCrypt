#include "VolumeProtocol.h"
#include "Platform/MemoryStream.h"
#include <algorithm>
#include <cerrno>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#include <uuid/uuid.h>

namespace VeraCrypt
{
	namespace FSKit
	{
		namespace
		{
			const uint32 Signature = 0x3346434c;
			const uint32 MaximumTransfer = 1024 * 1024;
			enum Operation : uint32 { Inspect = 1, ReadImage, ReadControl, WriteImage, FlushImage };

			uint64 LoadLittleEndian (const uint8 *bytes, size_t size)
			{
				uint64 value = 0;
				for (size_t index = 0; index < size; ++index)
					value |= static_cast <uint64> (bytes[index]) << (index * 8);
				return value;
			}

			void StoreLittleEndian (uint8 *bytes, size_t size, uint64 value)
			{
				for (size_t index = 0; index < size; ++index)
					bytes[index] = static_cast <uint8> (value >> (index * 8));
			}

			bool Receive (int fd, uint8 *bytes, size_t size)
			{
				while (size != 0)
				{
					const ssize_t received = recv (fd, bytes, size, 0);
					if (received < 0 && errno == EINTR)
						continue;
					if (received <= 0)
						return false;
					bytes += received;
					size -= received;
				}
				return true;
			}

			bool Send (int fd, const uint8 *bytes, size_t size)
			{
				while (size != 0)
				{
					const ssize_t sent = send (fd, bytes, size, 0);
					if (sent < 0 && errno == EINTR)
						continue;
					if (sent <= 0)
						return false;
					bytes += sent;
					size -= sent;
				}
				return true;
			}

			void Reply (int fd, int error, const uint8 *data = nullptr, size_t size = 0)
			{
				uint8 header[8];
				StoreLittleEndian (header, 4, error);
				StoreLittleEndian (header + 4, 4, size);
				if (Send (fd, header, sizeof (header)))
					Send (fd, data, size);
			}
		}

		VolumeIdentity NewVolumeIdentity ()
		{
			struct timeval now;
			throw_sys_if (gettimeofday (&now, nullptr) != 0);
			VolumeIdentity identity;
			uuid_generate (identity.Identifier.data());
			// VolumeInfo sorts mounts by this field. Use the same time units as FUSE.
			identity.SerialInstanceNumber = static_cast <uint64> (now.tv_sec) * 1000000ULL + now.tv_usec;
			return identity;
		}

		void ServeRequest (int connection, uid_t owner, Volume &volume, VolumeInfo &info,
			const std::array <uint8, 16> &identifier)
		{
			uid_t peer;
			gid_t group;
			if (getpeereid (connection, &peer, &group) != 0 || peer != owner)
				return;

			const timeval timeout = { 10, 0 };
			const int noSignal = 1;
			if (setsockopt (connection, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof (timeout)) != 0
				|| setsockopt (connection, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof (timeout)) != 0
				|| setsockopt (connection, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, sizeof (noSignal)) != 0)
				return;

			uint8 request[40];
			if (!Receive (connection, request, sizeof (request)))
				return;

			const uint64 operation = LoadLittleEndian (request + 4, 4);
			const uint64 offset = LoadLittleEndian (request + 8, 8);
			const size_t length = LoadLittleEndian (request + 16, 4);
			if (LoadLittleEndian (request, 4) != Signature || LoadLittleEndian (request + 20, 4) != 0
				|| length > MaximumTransfer || operation < Inspect || operation > FlushImage
				|| (operation == Inspect && (offset != 0 || length != 40))
				|| (operation == FlushImage && (offset != 0 || length != 0)))
			{
				Reply (connection, EINVAL);
				return;
			}

			const uint8 *expected = request + 24;
			const bool initialInspect = operation == Inspect
				&& std::all_of (expected, expected + identifier.size(), [] (uint8 byte) { return byte == 0; });
			if (!initialInspect && !std::equal (identifier.begin(), identifier.end(), expected))
			{
				Reply (connection, ESTALE);
				return;
			}

			try
			{
				if (operation == ReadImage)
				{
					if (length == 0 || offset >= volume.GetSize())
					{
						Reply (connection, 0);
						return;
					}
					SecureBuffer data (length);
					const size_t available = volume.ReadBytes (data, offset);
					Reply (connection, 0, data.Ptr(), available);
					return;
				}
				if (operation == WriteImage)
				{
					SecureBuffer data;
					if (length != 0)
					{
						data.Allocate (length);
						if (!Receive (connection, data.Ptr(), length))
							return;
					}
					if (volume.GetProtectionType() == VolumeProtection::ReadOnly)
						Reply (connection, EROFS);
					else if (offset > volume.GetSize() || length > volume.GetSize() - offset)
						Reply (connection, ENOSPC);
					else
					{
						volume.WriteBytes (data, offset);
						Reply (connection, 0);
					}
					return;
				}
				if (operation == FlushImage)
				{
					if (volume.GetProtectionType() != VolumeProtection::ReadOnly)
						volume.GetFile()->Flush();
					Reply (connection, 0);
					return;
				}

				shared_ptr <MemoryStream> stream (new MemoryStream);
				info.Set (volume);
				info.Serialize (stream);
				const ConstBufferPtr control = *stream;
				if (control.Size() > MaximumTransfer)
				{
					Reply (connection, EOVERFLOW);
					return;
				}

				if (operation == Inspect)
				{
					uint8 metadata[40];
					StoreLittleEndian (metadata, 8, volume.GetSize());
					StoreLittleEndian (metadata + 8, 8, control.Size());
					std::copy (identifier.begin(), identifier.end(), metadata + 16);
					StoreLittleEndian (metadata + 32, 8, volume.GetProtectionType() == VolumeProtection::ReadOnly);
					Reply (connection, 0, metadata, sizeof (metadata));
				}
				else if (offset < control.Size())
					Reply (connection, 0, control.Get() + offset, std::min <uint64> (length, control.Size() - offset));
				else
					Reply (connection, 0);
			}
			catch (const VolumeReadOnly &)
			{
				Reply (connection, EROFS);
			}
			catch (const VolumeProtected &)
			{
				Reply (connection, EPERM);
			}
			catch (const SystemException &error)
			{
				Reply (connection, error.GetErrorCode() > 0 ? error.GetErrorCode() : EIO);
			}
			catch (...)
			{
				Reply (connection, EIO);
			}
		}
	}
}
