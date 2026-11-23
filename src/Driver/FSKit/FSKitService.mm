#import <Foundation/Foundation.h>
#undef ERR_SUCCESS
#include "FSKitService.h"
#include "VolumeProtocol.h"
#include "Common/Tcdefs.h"
#include "Core/CoreException.h"
#include "Platform/Finally.h"
#include "Platform/Unix/Process.h"
#include <cerrno>
#include <chrono>
#include <fcntl.h>
#include <IOKit/IOBSD.h>
#include <IOKit/IOKitLib.h>
#include <poll.h>
#include <sys/file.h>
#include <sys/mount.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <unistd.h>

namespace VeraCrypt
{
	namespace FSKit
	{
		namespace
		{
			string ResourcePath (const string &mountPoint)
			{
				return mountPoint.substr (0, mountPoint.rfind ('/'));
			}

			string ApplicationGroupDirectory ()
			{
				if (getuid() == 0 || getuid() != geteuid())
					throw ExternalException (SRC_POS, L"FSKit requires an unprivileged macOS login session.");
				@autoreleasepool
				{
					NSString *group = [[NSBundle mainBundle] objectForInfoDictionaryKey:@"LambCryptFSKitIPCGroup"];
					if (![group isKindOfClass:[NSString class]])
						throw ExternalException (SRC_POS, L"Start LambCrypt FSKit from its provisioned app bundle.");
					NSURL *container = [[NSFileManager defaultManager] containerURLForSecurityApplicationGroupIdentifier:group];
					const char *path = [container fileSystemRepresentation];
					if (!path)
						throw ExternalException (SRC_POS, L"Could not open the LambCrypt FSKit app group.");
					return path;
				}
			}

			string WorkerDirectory (const string &groupDirectory, const string &mountPoint)
			{
				const string mountDirectory = ResourcePath (mountPoint);
				return groupDirectory + mountDirectory.substr (mountDirectory.rfind ('/'));
			}

			bool MountTableEntry (const string &mountPoint, fsid_t &identity)
			{
				struct statfs *mounts;
				const int count = getmntinfo (&mounts, MNT_NOWAIT);
				throw_sys_if (count == 0);
				for (int index = 0; index < count; ++index)
				{
					const struct statfs &mount = mounts[index];
					if (mountPoint == mount.f_mntonname)
					{
						identity = mount.f_fsid;
						return true;
					}
				}
				return false;
			}

			bool LookupMedia (CFDictionaryRef match, uint64 &identity)
			{
				io_iterator_t matches = IO_OBJECT_NULL;
				if (!match || IOServiceGetMatchingServices (kIOMainPortDefault, match, &matches) != KERN_SUCCESS)
					return false;
				const io_service_t device = IOIteratorNext (matches);
				IOObjectRelease (matches);
				identity = 0;
				if (!device)
					return true;
				const kern_return_t result = IORegistryEntryGetRegistryEntryID (device, &identity);
				IOObjectRelease (device);
				return result == KERN_SUCCESS && identity != 0;
			}

			uint64 GetMediaIdentity (const DevicePath &device)
			{
				const string path = device;
				if (path.compare (0, 9, "/dev/disk") != 0)
					return 0;
				uint64 identity;
				return LookupMedia (IOBSDNameMatching (kIOMainPortDefault, 0, path.c_str() + 5), identity) ? identity : 0;
			}

			void SendMediaIdentity (int channel, uint64 identity)
			{
				if (channel < 0)
					return;
				const uint8 *bytes = reinterpret_cast <const uint8 *> (&identity);
				for (size_t sent = 0; sent < sizeof (identity); )
				{
					const ssize_t count = write (channel, bytes + sent, sizeof (identity) - sent);
					if (count < 0 && errno == EINTR)
						continue;
					if (count <= 0)
						return;
					sent += static_cast <size_t> (count);
				}
			}

			bool TryLockFile (int fd, int mode)
			{
				int result;
				do { result = flock (fd, mode | LOCK_NB); }
				while (result == -1 && errno == EINTR);
				if (result == 0)
					return true;
				throw_sys_if (errno != EWOULDBLOCK);
				return false;
			}

			int TryReserveMount (const string &groupDirectory, const string &name)
			{
				// Keep the lock local even if the opened volume is on a share.
				const string directory = groupDirectory + "/mount-locks";
				throw_sys_sub_if (mkdir (directory.c_str(), 0700) != 0 && errno != EEXIST, directory);
				const int directoryFd = open (directory.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
				throw_sys_sub_if (directoryFd < 0, directory);
				finally_do_arg (int, directoryFd, { close (finally_arg); });
				struct stat state;
				throw_sys_sub_if (fstat (directoryFd, &state) != 0, directory);
				if (state.st_uid != getuid() || (state.st_mode & (S_IRWXG | S_IRWXO)))
				{
					errno = EPERM;
					throw SystemException (SRC_POS, directory);
				}

				// Leave the inode in place so simultaneous opens always contend on it.
				const string path = directory + "/" + name;
				const int fd = openat (directoryFd, name.c_str(), O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK, 0600);
				throw_sys_sub_if (fd < 0, path);
				bool locked = false;
				finally_do_arg2 (int, fd, bool &, locked, { if (!finally_arg2) close (finally_arg); });
				throw_sys_sub_if (fstat (fd, &state) != 0, path);
				if (!S_ISREG (state.st_mode) || state.st_uid != getuid() || state.st_nlink != 1
					|| (state.st_mode & (S_IRWXG | S_IRWXO)))
				{
					errno = EPERM;
					throw SystemException (SRC_POS, path);
				}
				locked = TryLockFile (fd, LOCK_EX);
				return locked ? fd : -1;
			}

			int ReserveVolume (const string &groupDirectory, int volumeFd)
			{
				struct stat identity;
				throw_sys_if (fstat (volumeFd, &identity) != 0);
				string name;
				if (S_ISBLK (identity.st_mode))
					name = "block-" + std::to_string (static_cast <uint64> (identity.st_rdev));
				else if (S_ISCHR (identity.st_mode))
					name = "character-" + std::to_string (static_cast <uint64> (identity.st_rdev));
				else
					name = "file-" + std::to_string (static_cast <uint64> (identity.st_dev))
						+ "-" + std::to_string (static_cast <uint64> (identity.st_ino));

				const int fd = TryReserveMount (groupDirectory, name);
				if (fd < 0)
					throw VolumeAlreadyMounted (SRC_POS);
				return fd;
			}

			bool IsServiceMountPresent (int directory, const string &mountPoint, const fsid_t &identity)
			{
				fsid_t current;
				if (!MountTableEntry (mountPoint, current))
				{
					// macOS may temporarily omit the mount during unmount.
					// Observe absence again with no local helper in flight.
					if (!TryLockFile (directory, LOCK_SH))
						return true;
					finally_do_arg (int, directory, { (void) flock (finally_arg, LOCK_UN); });
					if (!MountTableEntry (mountPoint, current))
						return false;
				}
				return current.val[0] == identity.val[0] && current.val[1] == identity.val[1];
			}

			void CleanupEjectedMount (const string &mountPoint, const fsid_t &identity)
			{
				const int lock = AcquireUnmountLock (mountPoint);
				finally_do_arg (int, lock, { close (finally_arg); });
				if (!GetAttachedDiskImageDevice (mountPoint).IsEmpty())
					return;
				fsid_t current;
				if (MountTableEntry (mountPoint, current) && current.val[0] == identity.val[0] && current.val[1] == identity.val[1])
					UnmountAuxiliary (mountPoint, false);
			}

			uint64 FindLateMedia (const string &mountPoint, const fsid_t &identity)
			{
				using Clock = std::chrono::steady_clock;
				const auto deadline = Clock::now() + std::chrono::seconds (10);
				while (Clock::now() < deadline)
				{
					try
					{
						fsid_t current;
						if (!MountTableEntry (mountPoint, current) || current.val[0] != identity.val[0] || current.val[1] != identity.val[1])
							return 0;
						const uint64 media = GetMediaIdentity (GetAttachedDiskImageDevice (mountPoint));
						if (media != 0)
							return media;
					}
					catch (const std::exception &) { }
					poll (nullptr, 0, 1000);
				}
				return 0;
			}

			void RunWorker (int listener, int commit, int directory, int volumeReservation, int slotReservation,
				Volume &volume, VolumeInfo &info, const std::array <uint8, 16> &identifier, const string &mountPoint,
				const string &resource)
			{
				Process::DisableCoreDumps();
				const int volumeFd = volume.GetFile()->GetSystemHandle();
				const int limit = getdtablesize();
				for (int fd = 0; fd < limit; ++fd)
					if (fd != listener && fd != commit && fd != directory && fd != volumeFd
						&& fd != volumeReservation && fd != slotReservation)
						close (fd);

				struct pollfd descriptors[] = { {listener, POLLIN, 0}, {commit, POLLIN, 0} };
				const auto closeWorkerDescriptors = [&] {
					for (int fd : {listener, descriptors[1].fd, directory, volumeReservation, slotReservation, volumeFd})
						if (fd >= 0)
							close (fd);
				};
				using Clock = std::chrono::steady_clock;
				Clock::time_point publicationDeadline;
				Clock::time_point nextMediaCheck;
				fsid_t identity = {};
				uint64 media = 0;
				uint64 incomingMedia = 0;
				size_t mediaBytes = 0;
				pid_t helper = -1;
				int mediaReport = -1;
				finally_do_arg (int &, mediaReport, { if (finally_arg >= 0) close (finally_arg); });
				bool observeMount = false;
				bool committed = false;
				bool observeLateMedia = false;
				while (true)
				{
					if (committed)
					{
						try
						{
							if (!IsServiceMountPresent (directory, mountPoint, identity))
								break;
						}
						catch (const SystemException &) { }
					}
					else if (observeMount)
					{
						// Keep serving a late mount until a usable inventory can confirm
						// its absence after the publication deadline.
						try
						{
							committed = MountTableEntry (mountPoint, identity);
							if (!committed && Clock::now() >= publicationDeadline)
								break;
						}
						catch (const SystemException &) { }
					}

					if (helper > 0)
					{
						int status;
						const pid_t finished = waitpid (helper, &status, WNOHANG);
						if (finished > 0 || (finished < 0 && errno != EINTR))
						{
							helper = -1;
							if (mediaReport >= 0)
							{
								if (finished > 0 && WIFEXITED (status) && WEXITSTATUS (status) == 0)
								{
									uint64 reported;
									ssize_t received;
									do { received = read (mediaReport, &reported, sizeof (reported)); }
									while (received < 0 && errno == EINTR);
									if (received == sizeof (reported))
										media = reported;
								}
								close (mediaReport);
								mediaReport = -1;
							}
						}
					}
					// Disk Images queries and unmount run in a helper, with the
					// worker serving the filesystem throughout either operation.
					if (committed && observeLateMedia)
					{
						observeLateMedia = false;
						int report[2];
						if (pipe (report) == 0)
						{
							helper = fork();
							if (helper == 0)
							{
								close (report[0]);
								closeWorkerDescriptors();
								try { SendMediaIdentity (report[1], FindLateMedia (mountPoint, identity)); _exit (0); }
								catch (...) { _exit (1); }
							}
							close (report[1]);
							if (helper > 0)
								mediaReport = report[0];
							else
								close (report[0]);
						}
					}
					if (committed && media != 0 && helper < 0 && Clock::now() >= nextMediaCheck)
					{
						nextMediaCheck = Clock::now() + std::chrono::seconds (1);
						uint64 current;
						if (LookupMedia (IORegistryEntryIDMatching (media), current) && current == 0)
						{
							// Back off if inventory or a competing unmount prevents cleanup.
							nextMediaCheck = Clock::now() + std::chrono::seconds (5);
							helper = fork();
							if (helper == 0)
							{
								closeWorkerDescriptors();
								try { CleanupEjectedMount (mountPoint, identity); _exit (0); }
								catch (...) { _exit (1); }
							}
						}
					}

					const int ready = poll (descriptors, 2, observeMount ? 200 : -1);
					if (ready < 0 && errno == EINTR)
						continue;
					if (ready < 0)
						break;

					if (descriptors[1].revents != 0)
					{
						ssize_t received;
						if (!observeMount)
						{
							char value;
							do { received = read (commit, &value, 1); }
							while (received < 0 && errno == EINTR);
							if (received == 0)
							{
								// Publication may have raced the caller's cancellation.
								try
								{
									if (!MountTableEntry (mountPoint, identity)) break;
									committed = true;
								}
								catch (const SystemException &) { }
								// Stop polling the EOF. Keep our end open so the caller
								// does not see EOF until the worker really exits.
								descriptors[1].fd = -1;
							}
							else if (received != 1 || value != 1)
								break;
							observeMount = true;
							publicationDeadline = Clock::now() + std::chrono::seconds (10);
						}
						else
						{
							// A zero identity requests bounded observation of a late
							// attachment. An incomplete message carries no request.
							uint8 *bytes = reinterpret_cast <uint8 *> (&incomingMedia);
							do { received = read (commit, bytes + mediaBytes, sizeof (incomingMedia) - mediaBytes); }
							while (received < 0 && errno == EINTR);
							if (received > 0)
								mediaBytes += static_cast <size_t> (received);
							if (received <= 0 || mediaBytes == sizeof (incomingMedia))
							{
								if (mediaBytes == sizeof (incomingMedia))
								{
									media = incomingMedia;
									observeLateMedia = media == 0;
								}
								close (commit);
								descriptors[1].fd = -1;
							}
						}
						continue;
					}

					if (descriptors[0].revents & (POLLERR | POLLHUP | POLLNVAL))
						break;
					if ((descriptors[0].revents & POLLIN) == 0)
						continue;
					const int connection = accept (listener, nullptr, nullptr);
					if (connection >= 0)
					{
						ServeRequest (connection, getuid(), volume, info, identifier);
						close (connection);
					}
				}

				try { volume.Close (); }
				catch (...) { }
				close (volumeReservation);
				close (slotReservation);
				close (listener);
				unlink ((resource + "/io").c_str());
				rmdir (resource.c_str());
				RemoveEmptyMountDirectory (mountPoint);
			}
		}

		string CreateMountPoint (const string &prefix)
		{
			char path[] = "/private/tmp/lambcrypt-fskit.XXXXXXXX";
			throw_sys_if (mkdtemp (path) == nullptr);
			const string mount = string (path) + "/" + prefix;
			if (mkdir (mount.c_str(), 0700) != 0)
			{
				const int error = errno;
				rmdir (path);
				errno = error;
				throw SystemException (SRC_POS, mount);
			}
			return mount;
		}

		bool IsAuxiliaryMountPoint (const DirectoryPath &mountPoint)
		{
			static const string prefix = "/private/tmp/lambcrypt-fskit.";
			return string (mountPoint).compare (0, prefix.size(), prefix) == 0;
		}

		shared_ptr <VolumeInfo> ReadVolumeInfo (const DirectoryPath &mountPoint)
		{
			// FSKit can cache the mounted control file across opens, freezing its
			// activity counters. Read the bound worker's live snapshot instead.
			shared_ptr <VolumeInfo> volume = ReadVolumeControl (WorkerDirectory (ApplicationGroupDirectory (), mountPoint) + "/io");
			volume->AuxMountPoint = mountPoint;
			return volume;
		}

		void FlushVolume (const VolumeInfo &volume)
		{
			FlushVolumeControl (WorkerDirectory (ApplicationGroupDirectory (), volume.AuxMountPoint) + "/io", volume);
		}

		void RemoveEmptyMountDirectory (const string &mountPoint)
		{
			rmdir (mountPoint.c_str());
			rmdir (ResourcePath (mountPoint).c_str());
		}

		int TryReserveSlot (VolumeSlotNumber slot)
		{
			return TryReserveMount (ApplicationGroupDirectory (), "slot-" + std::to_string (slot));
		}

		uint64 Mount (const shared_ptr <Volume> &volume, VolumeSlotNumber slot, const string &mountPoint,
			int slotReservation, int &activationChannel)
		{
			const string mountDirectory = ResourcePath (mountPoint);
			const int directory = open (mountDirectory.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
			throw_sys_sub_if (directory < 0, mountDirectory);
			finally_do_arg (int, directory, { close (finally_arg); });
			const string groupDirectory = ApplicationGroupDirectory ();
			const int volumeReservation = ReserveVolume (groupDirectory, volume->GetFile()->GetSystemHandle());
			finally_do_arg (int, volumeReservation, { close (finally_arg); });
			const string resource = WorkerDirectory (groupDirectory, mountPoint);
			const string endpoint = resource + "/io";
			throw_sys_sub_if (mkdir (resource.c_str(), 0700) != 0, resource);
			finally_do_arg (const string *, &resource, { rmdir (finally_arg->c_str()); });
			const int listener = socket (AF_UNIX, SOCK_STREAM, 0);
			throw_sys_if (listener == -1);
			finally_do_arg (int, listener, { close (finally_arg); });
			throw_sys_if (fcntl (listener, F_SETFD, FD_CLOEXEC) == -1);

			// Accepted Unix sockets inherit the send buffer. Give image reads
			// room to make progress and use the system default if tuning fails.
			const int sendBufferSize = 256 * 1024;
			(void) setsockopt (listener, SOL_SOCKET, SO_SNDBUF, &sendBufferSize, sizeof (sendBufferSize));

			const UnixSocketAddress address (endpoint);
			throw_sys_if (::bind (listener, address.Get(), address.Length) != 0);
			bool workerStarted = false;
			try
			{
				throw_sys_if (chmod (endpoint.c_str(), 0600) != 0 || listen (listener, 8) != 0);
				VolumeInfo info;
				info.SlotNumber = slot;
				const VolumeIdentity identity = NewVolumeIdentity ();
				info.SerialInstanceNumber = identity.SerialInstanceNumber;

				int activation[2];
				throw_sys_if (socketpair (AF_UNIX, SOCK_STREAM, 0, activation) != 0);
				finally_do_arg (int *, activation, {
					if (finally_arg[0] >= 0) close (finally_arg[0]);
					if (finally_arg[1] >= 0) close (finally_arg[1]);
				});
				throw_sys_if (fcntl (activation[0], F_SETFD, FD_CLOEXEC) == -1);
				throw_sys_if (fcntl (activation[1], F_SETFD, FD_CLOEXEC) == -1);
				const int noSignal = 1;
				const timeval timeout = { 10, 0 };
				throw_sys_if (setsockopt (activation[1], SOL_SOCKET, SO_NOSIGPIPE, &noSignal, sizeof (noSignal)) != 0);
				throw_sys_if (setsockopt (activation[1], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof (timeout)) != 0);
				const pid_t launcher = fork();
				throw_sys_if (launcher < 0);
				if (launcher == 0)
				{
					close (activation[1]);
					const pid_t worker = fork();
					if (worker != 0)
						_exit (worker < 0 ? 1 : 0);
					if (setsid() == -1)
						_exit (1);
					// The worker inherits both reservations and holds them until volume close.
					RunWorker (listener, activation[0], directory, volumeReservation, slotReservation,
						*volume, info, identity.Identifier, mountPoint, resource);
					_exit (0);
				}

				close (activation[0]);
				activation[0] = -1;
				int status;
				pid_t reaped;
				do { reaped = waitpid (launcher, &status, 0); }
				while (reaped < 0 && errno == EINTR);
				throw_sys_if (reaped != launcher);
				if (!WIFEXITED (status) || WEXITSTATUS (status) != 0)
					throw ExternalException (SRC_POS, L"The FSKit image service did not start.");
				workerStarted = true;
				const char observeMount = 1;
				try
				{
					const char *mountOptions = volume->GetProtectionType() == VolumeProtection::ReadOnly ? "ro,nobrowse" : "nobrowse";
					Process::ExecuteBounded ("/sbin/mount", {"-F", "-t", "lambcryptfs", "-o", mountOptions, resource, mountPoint}, 30000);
				}
				catch (const TimeOut &)
				{
					// Let the worker observe late publication without delaying the caller.
					(void) write (activation[1], &observeMount, 1);
					throw MountServiceCleanupFailed (SRC_POS,
						L"macOS did not confirm auxiliary mount: " + StringConverter::ToWide (mountPoint)
						+ L"\nRecheck the mounted volume list after 10 seconds and dismount any entry for this volume.");
				}
				catch (const ExecutedProcessFailed &error)
				{
					// A failed helper may have published the mount. Keep its service
					// running unless the mount table confirms it is absent.
					fsid_t identity;
					bool canCancel = false;
					try { canCancel = !MountTableEntry (mountPoint, identity); }
					catch (const SystemException &) { }
					bool cleanupConfirmed = false;
					if (canCancel)
					{
						shutdown (activation[1], SHUT_WR);
						char unexpectedReply;
						ssize_t received;
						do { received = recv (activation[1], &unexpectedReply, 1, 0); }
						while (received < 0 && errno == EINTR);
						try { cleanupConfirmed = received == 0 && !MountTableEntry (mountPoint, identity); }
						catch (const SystemException &) { }
					}
					else
						(void) write (activation[1], &observeMount, 1);
					if (!cleanupConfirmed || (unlink (endpoint.c_str()) != 0 && errno != ENOENT))
						throw MountServiceCleanupFailed (SRC_POS,
							L"FSKit startup cleanup could not be confirmed: " + StringConverter::ToWide (mountPoint)
							+ L"\n" + StringConverter::ToWide (error.GetErrorOutput()));
					RemoveEmptyMountDirectory (mountPoint);
					if (error.GetErrorOutput().find (" is disabled!") == string::npos)
						throw;
					throw ExecutedProcessFailed (error.what(), error.GetCommand(), error.GetExitCode(),
						error.GetErrorOutput() + "\nIn System Settings, open Login Items & Extensions, choose By Category, "
						"then enable LambCrypt FSKit under File System Extensions.");
				}
				throw_sys_if (write (activation[1], &observeMount, 1) != 1);
				activationChannel = activation[1];
				activation[1] = -1;
				return identity.SerialInstanceNumber;
			}
			catch (...)
			{
				if (!workerStarted)
					unlink (endpoint.c_str());
				throw;
			}
		}

		void ObserveAttachedMedia (int activationChannel, const DevicePath &device)
		{
			// A zero identity asks the worker to retry by exact image path.
			SendMediaIdentity (activationChannel, GetMediaIdentity (device));
		}

		void ObserveLateAttachedMedia (int activationChannel)
		{
			SendMediaIdentity (activationChannel, 0);
		}

		int AcquireUnmountLock (const DirectoryPath &mountPoint)
		{
			const string parent = ResourcePath (string (mountPoint));
			const int fd = open (parent.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
			throw_sys_sub_if (fd < 0, parent);
			bool locked = false;
			finally_do_arg2 (int, fd, bool &, locked, { if (!finally_arg2) close (finally_arg); });
			locked = TryLockFile (fd, LOCK_EX);
			if (!locked)
				throw MountedVolumeInUse (SRC_POS);
			return fd;
		}

		void UnmountAuxiliary (const DirectoryPath &mountPoint, bool force)
		{
			list <string> args;
			if (force)
				args.push_back ("-f");
			args.push_back ("--");
			args.push_back (mountPoint);
			Process::ExecuteBounded ("/sbin/umount", args, 10000);
		}

		void WaitForServiceExit (const DirectoryPath &mountPoint)
		{
			const string endpoint = WorkerDirectory (ApplicationGroupDirectory (), mountPoint) + "/io";
			struct stat state;
			for (unsigned int attempt = 0; attempt < 100; ++attempt)
			{
				if (lstat (endpoint.c_str(), &state) != 0 && errno == ENOENT)
					return;
				Thread::Sleep (100);
			}
			throw DismountServiceCleanupFailed (SRC_POS, wstring (mountPoint));
		}
	}
}

