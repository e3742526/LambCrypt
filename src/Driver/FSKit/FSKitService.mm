#import <Foundation/Foundation.h>
#undef ERR_SUCCESS
#include "FSKitService.h"
#include "VolumeProtocol.h"
#include "Common/Tcdefs.h"
#include "Core/CoreException.h"
#include "Platform/Finally.h"
#include "Platform/Unix/Process.h"
#include <cerrno>
#include <fcntl.h>
#include <poll.h>
#include <sys/mount.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/un.h>
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

			string WorkerDirectory (const string &mountPoint)
			{
				@autoreleasepool
				{
					NSString *group = [[NSBundle mainBundle] objectForInfoDictionaryKey:@"LambCryptFSKitIPCGroup"];
					if (![group isKindOfClass:[NSString class]])
						throw ExternalException (SRC_POS, L"Start LambCrypt FSKit from its provisioned app bundle.");
					NSURL *container = [[NSFileManager defaultManager] containerURLForSecurityApplicationGroupIdentifier:group];
					const char *path = [container fileSystemRepresentation];
					if (!path)
						throw ExternalException (SRC_POS, L"Could not open the LambCrypt FSKit app group.");
					const string mountDirectory = ResourcePath (mountPoint);
					return string (path) + mountDirectory.substr (mountDirectory.rfind ('/'));
				}
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

			void RunWorker (int listener, int commit, Volume &volume, VolumeInfo &info,
				const std::array <uint8, 16> &identifier, const string &mountPoint, const string &resource)
			{
				Process::DisableCoreDumps();
				const int volumeFd = volume.GetFile()->GetSystemHandle();
				const int limit = getdtablesize();
				for (int fd = 0; fd < limit; ++fd)
					if (fd != listener && fd != commit && fd != volumeFd)
						close (fd);

				struct pollfd descriptors[] = { {listener, POLLIN, 0}, {commit, POLLIN, 0} };
				fsid_t identity = {};
				bool committed = false;
				while (true)
				{
					if (committed)
					{
						try
						{
							fsid_t current;
							if (!MountTableEntry (mountPoint, current)
								|| current.val[0] != identity.val[0] || current.val[1] != identity.val[1])
								break;
						}
						catch (const SystemException &) { }
					}

					const int ready = poll (descriptors, 2, committed ? 200 : -1);
					if (ready < 0 && errno == EINTR)
						continue;
					if (ready < 0)
						break;

					if (descriptors[1].revents != 0)
					{
						char value;
						if (read (commit, &value, 1) != 1 || value != 1)
							break;
						try
						{
							if (!MountTableEntry (mountPoint, identity))
								break;
						}
						catch (const SystemException &) { break; }
						close (commit);
						descriptors[1].fd = -1;
						committed = true;
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
				close (listener);
				unlink ((resource + "/io").c_str());
				rmdir (resource.c_str());
				RemoveEmptyMountDirectory (mountPoint);
			}
		}

		string CreateMountPoint (const string &prefix)
		{
			if (getuid() == 0 || getuid() != geteuid())
				throw ExternalException (SRC_POS, L"FSKit requires an unprivileged macOS login session.");

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

		void RemoveEmptyMountDirectory (const string &mountPoint)
		{
			rmdir (mountPoint.c_str());
			rmdir (ResourcePath (mountPoint).c_str());
		}

		void Mount (const shared_ptr <Volume> &volume, VolumeSlotNumber slot, const string &mountPoint)
		{
			const string resource = WorkerDirectory (mountPoint);
			const string endpoint = resource + "/io";
			throw_sys_sub_if (mkdir (resource.c_str(), 0700) != 0, resource);
			finally_do_arg (const string *, &resource, { rmdir (finally_arg->c_str()); });
			const int listener = socket (AF_UNIX, SOCK_STREAM, 0);
			throw_sys_if (listener == -1);
			finally_do_arg (int, listener, { close (finally_arg); });
			throw_sys_if (fcntl (listener, F_SETFD, FD_CLOEXEC) == -1);

			sockaddr_un address = {};
			address.sun_len = sizeof (address);
			address.sun_family = AF_UNIX;
			if (strlcpy (address.sun_path, endpoint.c_str(), sizeof (address.sun_path)) >= sizeof (address.sun_path))
				throw ParameterTooLarge (SRC_POS);
			throw_sys_if (::bind (listener, reinterpret_cast <sockaddr *> (&address), sizeof (address)) != 0);
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
					close (finally_arg[1]);
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
					RunWorker (listener, activation[0], *volume, info, identity.Identifier, mountPoint, resource);
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
				try
				{
					const char *mountOptions = volume->GetProtectionType() == VolumeProtection::ReadOnly ? "ro,nobrowse" : "nobrowse";
					Process::Execute ("/sbin/mount", {"-F", "-t", "lambcryptfs", "-o", mountOptions, resource, mountPoint}, 30000);
				}
				catch (const ExecutedProcessFailed &error)
				{
					// Tell the worker to abort and wait for it to close its
					// endpoint before returning the mount error to the client.
					shutdown (activation[1], SHUT_WR);
					char unexpectedReply;
					ssize_t received;
					do { received = recv (activation[1], &unexpectedReply, 1, 0); }
					while (received < 0 && errno == EINTR);
					if (received == 0)
					{
						fsid_t identity;
						if (!MountTableEntry (mountPoint, identity))
						{
							unlink (endpoint.c_str());
							RemoveEmptyMountDirectory (mountPoint);
						}
					}
					if (error.GetErrorOutput().find (" is disabled!") == string::npos)
						throw;
					throw ExecutedProcessFailed (error.what(), error.GetCommand(), error.GetExitCode(),
						error.GetErrorOutput() + "\nIn System Settings, open Login Items & Extensions, choose By Category, "
						"then enable LambCrypt FSKit under File System Extensions.");
				}
				const char ready = 1;
				throw_sys_if (write (activation[1], &ready, 1) != 1);
			}
			catch (...)
			{
				if (!workerStarted)
					unlink (endpoint.c_str());
				throw;
			}
		}

		void WaitForServiceExit (const DirectoryPath &mountPoint)
		{
			const string endpoint = WorkerDirectory (string (mountPoint)) + "/io";
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

