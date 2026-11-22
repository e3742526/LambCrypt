#include "VolumeProtocol.h"
#include "Platform/Finally.h"
#include "Platform/MemoryStream.h"
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <fcntl.h>
#include <limits>
#include <poll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/un.h>
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
			using SocketClock = std::chrono::steady_clock;
			const auto WorkerSocketTimeout = std::chrono::seconds (10);

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

			void WaitForSocket (int fd, short events, SocketClock::time_point deadline)
			{
				struct pollfd descriptor = {fd, events, 0};
				while (true)
				{
					const auto remaining = deadline - SocketClock::now();
					if (remaining <= SocketClock::duration::zero())
						throw TimeOut (SRC_POS);
					const int timeout = static_cast <int> (std::chrono::duration_cast <std::chrono::milliseconds> (remaining).count()) + 1;
					const int ready = poll (&descriptor, 1, timeout);
					if (ready > 0)
						return;
					if (ready == 0)
						throw TimeOut (SRC_POS);
					throw_sys_if (errno != EINTR);
				}
			}

			template <typename OperationFunction>
			void TransferSocket (int fd, short events, size_t size, SocketClock::time_point deadline, OperationFunction transfer)
			{
				for (size_t transferred = 0; transferred < size; )
				{
					if (SocketClock::now() >= deadline)
						throw TimeOut (SRC_POS);
					const ssize_t count = transfer (transferred, size - transferred);
					if (count < 0 && errno == EINTR)
						continue;
					if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
					{
						WaitForSocket (fd, events, deadline);
						continue;
					}
					throw_sys_if (count < 0);
					if (count == 0)
						throw ParameterIncorrect (SRC_POS);
					transferred += count;
				}
			}

			void Receive (int fd, uint8 *bytes, size_t size, SocketClock::time_point deadline)
			{
				TransferSocket (fd, POLLIN, size, deadline, [&] (size_t offset, size_t length) {
					return recv (fd, bytes + offset, length, 0);
				});
			}

			void Send (int fd, const uint8 *bytes, size_t size, SocketClock::time_point deadline)
			{
				TransferSocket (fd, POLLOUT, size, deadline, [&] (size_t offset, size_t length) {
					return send (fd, bytes + offset, length, 0);
				});
			}

			void Reply (int fd, int error, const uint8 *data = nullptr, size_t size = 0)
			{
				uint8 header[8];
				StoreLittleEndian (header, 4, error);
				StoreLittleEndian (header + 4, 4, size);
				const auto deadline = SocketClock::now() + WorkerSocketTimeout;
				try
				{
					Send (fd, header, sizeof (header), deadline);
					Send (fd, data, size, deadline);
				}
				catch (const Exception &) { }
			}

			void RequestControl (const string &endpoint, Operation operation, const std::array <uint8, 16> &identifier,
				const BufferPtr &reply, SocketClock::time_point deadline)
			{
				struct stat info;
				throw_sys_if (lstat (endpoint.c_str(), &info) != 0);
				if (!S_ISSOCK (info.st_mode) || info.st_uid != getuid() || (info.st_mode & 0077) != 0)
					throw ParameterIncorrect (SRC_POS);

				sockaddr_un address = {};
				address.sun_family = AF_UNIX;
				address.sun_len = sizeof (address);
				if (strlcpy (address.sun_path, endpoint.c_str(), sizeof (address.sun_path)) >= sizeof (address.sun_path))
					throw ParameterTooLarge (SRC_POS);
				const int fd = socket (AF_UNIX, SOCK_STREAM, 0);
				throw_sys_if (fd < 0);
				finally_do_arg (int, fd, { close (finally_arg); });
				const int noSignal = 1;
				throw_sys_if (fcntl (fd, F_SETFL, O_NONBLOCK) != 0 || fcntl (fd, F_SETFD, FD_CLOEXEC) != 0
					|| setsockopt (fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, sizeof (noSignal)) != 0);
				if (connect (fd, reinterpret_cast <const sockaddr *> (&address), sizeof (address)) != 0)
				{
					throw_sys_if (errno != EINPROGRESS && errno != EINTR);
					WaitForSocket (fd, POLLOUT, deadline);
					int error;
					socklen_t size = sizeof (error);
					throw_sys_if (getsockopt (fd, SOL_SOCKET, SO_ERROR, &error, &size) != 0);
					if (error != 0)
					{
						errno = error;
						throw SystemException (SRC_POS);
					}
				}

				uid_t peer;
				gid_t group;
				throw_sys_if (getpeereid (fd, &peer, &group) != 0);
				if (peer != info.st_uid)
					throw ParameterIncorrect (SRC_POS);

				uint8 request[40] = {};
				StoreLittleEndian (request, 4, Signature);
				StoreLittleEndian (request + 4, 4, operation);
				StoreLittleEndian (request + 16, 4, reply.Size());
				std::copy (identifier.begin(), identifier.end(), request + 24);
				Send (fd, request, sizeof (request), deadline);

				uint8 header[8];
				Receive (fd, header, sizeof (header), deadline);
				const uint64 error = LoadLittleEndian (header, 4);
				if (error != 0)
				{
					errno = error <= static_cast <uint64> (std::numeric_limits <int>::max()) ? static_cast <int> (error) : EIO;
					throw SystemException (SRC_POS);
				}
				if (LoadLittleEndian (header + 4, 4) != reply.Size())
					throw ParameterIncorrect (SRC_POS);
				Receive (fd, reply.Get(), reply.Size(), deadline);
			}

			shared_ptr <VolumeInfo> ReadWorkerControl (const string &endpoint, std::array <uint8, 16> &identifier,
				SocketClock::time_point deadline)
			{
				uint8 metadata[40];
				RequestControl (endpoint, Inspect, identifier, BufferPtr (metadata, sizeof (metadata)), deadline);
				const uint64 size = LoadLittleEndian (metadata + 8, 8);
				if (size == 0 || size > MaximumTransfer)
					throw ParameterIncorrect (SRC_POS);
				std::copy (metadata + 16, metadata + 32, identifier.begin());
				if (std::all_of (identifier.begin(), identifier.end(), [] (uint8 byte) { return byte == 0; }))
					throw ParameterIncorrect (SRC_POS);
				Buffer reply (static_cast <size_t> (size));
				RequestControl (endpoint, ReadControl, identifier, reply, deadline);
				shared_ptr <Stream> stream (new MemoryStream (reply));
				return Serializable::DeserializeNew <VolumeInfo> (stream);
			}
		}

		shared_ptr <VolumeInfo> ReadVolumeControl (const string &endpoint)
		{
			// Use one deadline for both requests so discovery can retain an older
			// snapshot when a worker cannot confirm the current counters.
			const auto deadline = SocketClock::now() + std::chrono::seconds (1);
			std::array <uint8, 16> identifier = {};
			return ReadWorkerControl (endpoint, identifier, deadline);
		}

		void FlushVolumeControl (const string &endpoint, const VolumeInfo &volume)
		{
			// Keep the original generation bound through the flush even if the
			// socket is replaced after reading its control record.
			const auto deadline = SocketClock::now() + WorkerSocketTimeout;
			std::array <uint8, 16> identifier = {};
			const auto current = ReadWorkerControl (endpoint, identifier, deadline);
			if (current->SerialInstanceNumber != volume.SerialInstanceNumber || current->SlotNumber != volume.SlotNumber
				|| current->Path != volume.Path)
				throw ParameterIncorrect (SRC_POS);
			RequestControl (endpoint, FlushImage, identifier, BufferPtr (), deadline);
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

			const int noSignal = 1;
			// Darwin can block in a stream send even with MSG_DONTWAIT.
			if (fcntl (connection, F_SETFL, O_NONBLOCK) != 0
				|| setsockopt (connection, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, sizeof (noSignal)) != 0)
				return;

			// An incomplete write must not reset the header's deadline or
			// keep this worker from accepting the volume's next request.
			const auto deadline = SocketClock::now() + WorkerSocketTimeout;
			auto receiveRequest = [connection, deadline] (uint8 *bytes, size_t size) {
				try { Receive (connection, bytes, size, deadline); }
				catch (const Exception &) { return false; }
				return true;
			};
			uint8 request[40];
			if (!receiveRequest (request, sizeof (request)))
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
			const bool stale = !initialInspect && !std::equal (identifier.begin(), identifier.end(), expected);
			if (stale && operation != WriteImage)
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
						if (!receiveRequest (data.Ptr(), length))
							return;
					}
					// The client sends the entire body before reading the reply.
					// Closing early can hide ESTALE behind a socket send error.
					if (stale)
						Reply (connection, ESTALE);
					else if (volume.GetProtectionType() == VolumeProtection::ReadOnly)
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
