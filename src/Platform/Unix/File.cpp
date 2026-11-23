/*
 Derived from source code of TrueCrypt 7.1a, which is
 Copyright (c) 2008-2012 TrueCrypt Developers Association and which is governed
 by the TrueCrypt License 3.0.

 Modifications and additions to the original source code (contained in this file)
 and all other portions of this file are Copyright (c) 2013-2026 AM Crypto
 and are governed by the Apache License 2.0 the full text of which is
 contained in the file License.txt included in VeraCrypt binary and source
 code distribution packages.
*/

#include <errno.h>
#include <fcntl.h>
#include <limits>
#include <stdlib.h>
#include <unistd.h>
#include <utime.h>

#ifdef TC_LINUX
#include <sys/mount.h>
#endif

#ifdef TC_BSD
#include <sys/disk.h>
#endif

#ifdef TC_OPENBSD
#include <sys/ioctl.h>
#include <sys/dkio.h>
#include <sys/disklabel.h>
#endif

#ifdef TC_SOLARIS
#include <stropts.h>
#include <sys/dkio.h>
#endif

#include <sys/file.h>
#include <sys/types.h>
#include <sys/stat.h>

#ifdef TC_FREEBSD
#include <sys/sysctl.h>
#endif

#include "Platform/File.h"
#include "Platform/TextReader.h"

namespace VeraCrypt
{
#if 0
#	define TC_TRACE_FILE_OPERATIONS

	static void TraceFileOperation (int fileHandle, FilePath filePath, bool write, uint64 length, int64 position = -1)
	{
		string path = filePath;
		if (path.empty() || path.find ("veracrypt_aux_mnt") != string::npos)
			return;

		stringstream s;
		s << path << ": " << (write ? "W " : "R ") << (position == -1 ? lseek (fileHandle, 0, SEEK_CUR) : position) << " (" << length << ")";
		SystemLog::WriteError (s.str());
	}
#endif

	void File::Close ()
	{
		if_debug (ValidateState());

		if (!SharedHandle)
		{
			close (FileHandle);
			FileIsOpen = false;

#ifdef TC_LINUX
			if (RequesterBacked)
			{
				// Root may be denied changing this file's attributes: restore them with the
				// requester's credentials, unless another process serves the file.
				RequesterBacked = false;
				if ((mFileOpenFlags & File::PreserveTimestamps) && !ReleaseOnly)
				{
					try
					{
						RestoreTimestampsAsRequester();
					}
					catch (...) { }
				}
				return;
			}
#endif

			if ((mFileOpenFlags & File::PreserveTimestamps) && Path.IsFile())
			{
				struct utimbuf u;
				u.actime = AccTime;
				u.modtime = ModTime;

				try
				{
					throw_sys_sub_if (utime (string (Path).c_str(), &u) == -1, wstring (Path));
				}
				catch (...) // Suppress errors to allow using read-only files
				{
#ifdef DEBUG
					throw;
#endif
				}
			}
		}
	}

	void File::Delete ()
	{
		Close();
		Path.Delete();
	}


	static void WriteAllToDescriptor (int fd, const uint8 *data, size_t remaining, const wstring &path)
	{
		while (remaining != 0)
		{
			const ssize_t count = write (fd, data, remaining);
			if (count < 0)
			{
				const int error = errno;
				if (error == EINTR)
					continue;
				throw SystemException (SRC_POS, path, error);
			}
			if (count == 0)
				throw SystemException (SRC_POS, path, EIO);

			// A short write has already written this prefix.
			data += count;
			remaining -= static_cast <size_t> (count);
		}
	}

	static void SyncDescriptor (int fd, bool stableStorage, const wstring &path)
	{
#ifdef TC_MACOSX
		// On macOS, fsync() can leave the data in the drive's volatile write cache.
		// Some filesystems, such as SMB, reject F_FULLFSYNC; fsync() is the best they offer.
		if (stableStorage && fcntl (fd, F_FULLFSYNC) == 0)
			return;
#else
		(void) stableStorage;
#endif
		while (fsync (fd) != 0)
		{
			const int error = errno;
			if (error != EINTR)
				throw SystemException (SRC_POS, path, error);
		}
	}

	// Makes a new or renamed directory entry durable. Directories that cannot be
	// opened or synced (for example on some network filesystems) are skipped.
	static void SyncParentDirectory (const string &path)
	{
		const string::size_type slash = path.find_last_of ('/');
		const string directory = (slash == string::npos) ? string (".") : (slash == 0 ? string ("/") : path.substr (0, slash));

		int flags = O_RDONLY;
#ifdef O_DIRECTORY
		flags |= O_DIRECTORY;
#endif
#ifdef O_CLOEXEC
		flags |= O_CLOEXEC;
#endif
		const int fd = open (directory.c_str(), flags);
		if (fd == -1)
			return;

		int result;
		do
		{
			result = fsync (fd);
		} while (result != 0 && errno == EINTR);

		const int error = errno;
		close (fd);

		if (result != 0 && error != EINVAL && error != ENOTSUP && error != EROFS && error != EBADF)
			throw SystemException (SRC_POS, StringConverter::ToWide (directory), error);
	}

	void File::Flush () const
	{
		if_debug (ValidateState());
		SyncDescriptor (FileHandle, false, wstring (Path));
	}

	void File::FlushToStableStorage () const
	{
		if_debug (ValidateState());
		SyncDescriptor (FileHandle, true, wstring (Path));
	}

	void File::WriteDurably (const FilePath &path, const ConstBufferPtr &data, bool replaceExisting)
	{
		const string target = path;

		if (!replaceExisting)
		{
			File file;
			file.Open (path, CreateNewWrite);

			try
			{
				file.Write (data);
				file.FlushToStableStorage();
				file.Close();
			}
			catch (...)
			{
				// This call created the file (O_EXCL), so it removes only its own partial output.
				if (file.IsOpen())
					file.Close();
				unlink (target.c_str());
				throw;
			}

			SyncParentDirectory (target);
			return;
		}

		struct stat existing;
		if (lstat (target.c_str(), &existing) == 0)
		{
			// Replacing a symlink, device or directory entry would not write where the caller expects.
			if (!S_ISREG (existing.st_mode))
				throw SystemException (SRC_POS, wstring (path), S_ISDIR (existing.st_mode) ? EISDIR : EEXIST);
		}
		else
		{
			const int error = errno;
			if (error != ENOENT)
				throw SystemException (SRC_POS, wstring (path), error);
		}

		// The temporary file shares the target's directory, so rename() replaces it atomically.
		const string::size_type slash = target.find_last_of ('/');
		const string directoryPrefix = (slash == string::npos) ? string() : target.substr (0, slash + 1);
		string baseName = (slash == string::npos) ? target : target.substr (slash + 1);
		if (baseName.size() > 200)
			baseName = "tmp";

		string tempPath = directoryPrefix + "." + baseName + ".XXXXXX";
		int fd = mkstemp (&tempPath[0]);
		throw_sys_sub_if (fd == -1, wstring (path));

		try
		{
			const int fdFlags = fcntl (fd, F_GETFD);
			if (fdFlags != -1)
				fcntl (fd, F_SETFD, fdFlags | FD_CLOEXEC);

			WriteAllToDescriptor (fd, data.Get(), data.Size(), wstring (path));
			SyncDescriptor (fd, true, wstring (path));

			const int closeResult = close (fd);
			fd = -1;
			throw_sys_sub_if (closeResult == -1, wstring (path));

			throw_sys_sub_if (rename (tempPath.c_str(), target.c_str()) == -1, wstring (path));
		}
		catch (...)
		{
			if (fd != -1)
				close (fd);
			unlink (tempPath.c_str());
			throw;
		}

		SyncParentDirectory (target);
	}

	uint32 File::GetDeviceSectorSize () const
	{
		if (Path.IsDevice())
		{
#ifdef TC_LINUX
			int blockSize;
			throw_sys_sub_if (ioctl (FileHandle, BLKSSZGET, &blockSize) == -1, wstring (Path));
			return blockSize;

#elif defined (TC_MACOSX)
			uint32 blockSize;
			throw_sys_sub_if (ioctl (FileHandle, DKIOCGETBLOCKSIZE, &blockSize) == -1, wstring (Path));
			return blockSize;

#elif defined (TC_FREEBSD)
			u_int sectorSize;
			throw_sys_sub_if (ioctl (FileHandle, DIOCGSECTORSIZE, &sectorSize) == -1, wstring (Path));
			return (uint32) sectorSize;

#elif defined (TC_OPENBSD)
			struct disklabel dl;
			throw_sys_sub_if (ioctl (FileHandle, DIOCGDINFO, &dl) == -1, wstring (Path));

			if (dl.d_secsize == 0)
				throw ParameterIncorrect (SRC_POS);

			return (uint32) dl.d_secsize;

#elif defined (TC_SOLARIS)
			struct dk_minfo mediaInfo;
			throw_sys_sub_if (ioctl (FileHandle, DKIOCGMEDIAINFO, &mediaInfo) == -1, wstring (Path));
			return mediaInfo.dki_lbsize;

#else
#	error GetDeviceSectorSize()
#endif
		}
		else
			throw ParameterIncorrect (SRC_POS);
	}

	uint64 File::GetPartitionDeviceStartOffset () const
	{
#ifdef TC_LINUX

		// HDIO_GETGEO ioctl is limited by the size of long
		TextReader tr ("/sys/block/" + string (Path.ToHostDriveOfPartition().ToBaseName()) + "/" + string (Path.ToBaseName()) + "/start");

		string line;
		tr.ReadLine (line);
		return StringConverter::ToUInt64 (line) * GetDeviceSectorSize();

#elif defined (TC_MACOSX)

#ifndef DKIOCGETBASE
#	define DKIOCGETBASE _IOR('d', 73, uint64)
#endif
		uint64 offset;
		throw_sys_sub_if (ioctl (FileHandle, DKIOCGETBASE, &offset) == -1, wstring (Path));
		return offset;

#elif defined (TC_FREEBSD)
		// Get the kernel GEOM configuration
		size_t sysctlDataLen, mibLen;
		int mib[4];
		mibLen = 4;
		throw_sys_sub_if (sysctlnametomib ("kern.geom.conftxt", mib, &mibLen), wstring (Path));
		throw_sys_sub_if (sysctl (mib, mibLen, NULL, &sysctlDataLen, NULL, 0), wstring (Path));
		vector<char> conftxt(sysctlDataLen);
		throw_sys_sub_if (sysctl (mib, mibLen, (void *)conftxt.data(), &sysctlDataLen, NULL, 0), wstring (Path));

		// Find the slice/partition data
		string conftxtStr (conftxt.begin(), conftxt.end());
		size_t confLoc = conftxtStr.find (Path.ToBaseName());
		throw_sys_sub_if (confLoc == string::npos, wstring (Path));

		// Skip to the ninth column
		for (int i = 0; i < 6;i++) {
			confLoc = conftxtStr.find (" ", confLoc + 1);
			throw_sys_sub_if (confLoc == string::npos, wstring (Path));
		}
		confLoc++;
		size_t end = conftxtStr.find (" ", confLoc);
		throw_sys_sub_if (end == string::npos, wstring (Path));
		return StringConverter::ToUInt64 (conftxtStr.substr (confLoc, end - confLoc));

#elif defined (TC_SOLARIS)

		struct extpart_info partInfo;
		throw_sys_sub_if (ioctl (FileHandle, DKIOCEXTPARTINFO, &partInfo) == -1, wstring (Path));
		return partInfo.p_start * GetDeviceSectorSize();

#else
		throw NotImplemented (SRC_POS);
#endif
	}

	uint64 File::Length () const
	{
		if_debug (ValidateState());

		// BSD does not support seeking to the end of a device
#ifdef TC_BSD
		if (Path.IsBlockDevice() || Path.IsCharacterDevice())
		{
#	ifdef TC_MACOSX
			uint32 blockSize;
			uint64 blockCount;
			throw_sys_sub_if (ioctl (FileHandle, DKIOCGETBLOCKSIZE, &blockSize) == -1, wstring (Path));
			throw_sys_sub_if (ioctl (FileHandle, DKIOCGETBLOCKCOUNT, &blockCount) == -1, wstring (Path));
			return blockCount * blockSize;
#	elif TC_OPENBSD
			struct disklabel dl;
			struct stat statData;
			throw_sys_sub_if (ioctl (FileHandle, DIOCGDINFO, &dl) == -1, wstring (Path));
			throw_sys_sub_if (fstat (FileHandle, &statData) == -1, wstring (Path));

			if (dl.d_secsize == 0)
				throw ParameterIncorrect (SRC_POS);

			uint64 sectors;
			int partition = DISKPART (statData.st_rdev);
			if (partition == RAW_PART)
			{
				sectors = DL_GETDSIZE (&dl);
			}
			else
			{
				if (partition < 0 || partition >= dl.d_npartitions)
					throw ParameterIncorrect (SRC_POS);

				sectors = DL_GETPSIZE (&dl.d_partitions[partition]);
			}

			if (sectors > ((uint64) -1) / dl.d_secsize)
				throw ParameterIncorrect (SRC_POS);

			return sectors * dl.d_secsize;
#	else
			uint64 mediaSize;
			throw_sys_sub_if (ioctl (FileHandle, DIOCGMEDIASIZE, &mediaSize) == -1, wstring (Path));
			return mediaSize;
#	endif
		}
#endif
#ifdef TC_LINUX
		// On Linux, try to use BLKGETSIZE64 for devices
		if (Path.IsDevice())
		{
			uint64 mediaSize;
			if (ioctl (FileHandle, BLKGETSIZE64, &mediaSize) != -1)
			{
				return mediaSize;
			}
		}
#endif
		off_t current = lseek (FileHandle, 0, SEEK_CUR);
		throw_sys_sub_if (current == -1, wstring (Path));
		SeekEnd (0);
		uint64 length = lseek (FileHandle, 0, SEEK_CUR);
		SeekAt (current);
		return length;
	}

#ifdef TC_LINUX
	void File::GetIdentity (struct stat &info) const
	{
		if (RequesterBacked)
		{
			memset (&info, 0, sizeof (info));
			info.st_mode = S_IFREG;
			info.st_dev = static_cast <dev_t> (RequesterDevice);
			info.st_ino = static_cast <ino_t> (RequesterInode);
		}
		else
			throw_sys_sub_if (fstat (FileHandle, &info) != 0, wstring (Path));
	}
#endif

	void File::Open (const FilePath &path, FileOpenMode mode, FileShareMode shareMode, FileOpenFlags flags)
	{
#ifdef TC_LINUX
		int sysFlags = O_LARGEFILE;
#else
		int sysFlags = 0;
#endif
#ifdef O_CLOEXEC
		sysFlags |= O_CLOEXEC;
#endif

		switch (mode)
		{
		case CreateReadWrite:
			sysFlags |= O_CREAT | O_TRUNC | O_RDWR;
			break;

		case CreateWrite:
			sysFlags |= O_CREAT | O_TRUNC | O_WRONLY;
			break;

		case CreateNewWrite:
			sysFlags |= O_CREAT | O_EXCL | O_WRONLY;
			break;

		case OpenRead:
			sysFlags |= O_RDONLY;
			break;

		case OpenWrite:
			sysFlags |= O_WRONLY;
			break;

		case OpenReadWrite:
			sysFlags |= O_RDWR;
			break;

		default:
			throw ParameterIncorrect (SRC_POS);
		}

		if ((flags & File::PreserveTimestamps) && path.IsFile())
		{
			struct stat statData;
			throw_sys_sub_if (stat (string (path).c_str(), &statData) == -1, wstring (path));
			AccTime = statData.st_atime;
			ModTime = statData.st_mtime;
		}

		FileHandle = open (string (path).c_str(), sysFlags, S_IRUSR | S_IWUSR);
#ifdef TC_LINUX
		if (FileHandle == -1 && (errno == EACCES || errno == EPERM) && (flags & File::AllowRequesterAccess)
			&& (mode == OpenRead || mode == OpenWrite || mode == OpenReadWrite))
		{
			int rootError = errno;
			if (OpenAsRequester (path, sysFlags))
			{
				Path = path;
				mFileOpenFlags = flags;
				FileIsOpen = true;
				return;
			}

			errno = rootError;
		}
#endif
		throw_sys_sub_if (FileHandle == -1, wstring (path));

#ifdef TC_LINUX
		if (mode != OpenRead)
		{
			// Some block devices accept writable opens even when write protected.
			// Report EROFS so the volume mount can retry with read only protection.
			struct stat statData;
			int readOnly = 0;
			if (fstat (FileHandle, &statData) == 0 && S_ISBLK (statData.st_mode)
				&& ioctl (FileHandle, BLKROGET, &readOnly) == 0 && readOnly)
			{
				close (FileHandle);
				FileHandle = -1;
				errno = EROFS;
				throw SystemException (SRC_POS, wstring (path));
			}
		}
#endif

#if 0 // File locking is disabled to avoid remote filesystem locking issues
		try
		{
			struct flock fl;
			memset (&fl, 0, sizeof (fl));
			fl.l_whence = SEEK_SET;
			fl.l_start = 0;
			fl.l_len = 0;

			switch (shareMode)
			{
			case ShareNone:
				fl.l_type = F_WRLCK;
				if (fcntl (FileHandle, F_SETLK, &fl) == -1)
					throw_sys_sub_if (errno == EAGAIN || errno == EACCES, wstring (path));
				break;

			case ShareRead:
				fl.l_type = F_RDLCK;
				if (fcntl (FileHandle, F_SETLK, &fl) == -1)
					throw_sys_sub_if (errno == EAGAIN || errno == EACCES, wstring (path));
				break;

			case ShareReadWrite:
				fl.l_type = (mode == OpenRead ? F_RDLCK : F_WRLCK);
				if (fcntl (FileHandle, F_GETLK, &fl) != -1 && fl.l_type != F_UNLCK)
				{
					errno = EAGAIN;
					throw SystemException (SRC_POS, wstring (path));
				}
				break;

			case ShareReadWriteIgnoreLock:
				break;

			default:
				throw ParameterIncorrect (SRC_POS);
			}
		}
		catch (...)
		{
			close (FileHandle);
			throw;
		}
#endif // 0

		Path = path;
		mFileOpenFlags = flags;
		FileIsOpen = true;
	}

	uint64 File::Read (const BufferPtr &buffer) const
	{
		if_debug (ValidateState());

#ifdef TC_TRACE_FILE_OPERATIONS
		TraceFileOperation (FileHandle, Path, false, buffer.Size());
#endif
		ssize_t bytesRead = read (FileHandle, buffer, buffer.Size());
		throw_sys_sub_if (bytesRead == -1, wstring (Path));

		return bytesRead;
	}

	uint64 File::ReadAt (const BufferPtr &buffer, uint64 position) const
	{
		if_debug (ValidateState());

#ifdef TC_TRACE_FILE_OPERATIONS
		TraceFileOperation (FileHandle, Path, false, buffer.Size(), position);
#endif
		// An interrupted pread transferred no bytes. Retry at the same offset
		// while preserving a successful short read or EOF for the caller.
		while (true)
		{
			const ssize_t bytesRead = pread (FileHandle, buffer, buffer.Size(), position);
			if (bytesRead >= 0)
				return bytesRead;
			const int error = errno;
			if (error != EINTR)
				throw SystemException (SRC_POS, wstring (Path), error);
		}
	}

	void File::SeekAt (uint64 position) const
	{
		if_debug (ValidateState());
		throw_sys_sub_if (lseek (FileHandle, position, SEEK_SET) == -1, wstring (Path));
	}

	void File::SeekEnd (int offset) const
	{
		if_debug (ValidateState());

		// BSD does not support seeking to the end of a device
#ifdef TC_BSD
		if (Path.IsBlockDevice() || Path.IsCharacterDevice())
		{
			SeekAt (Length() + offset);
			return;
		}
#endif

		throw_sys_sub_if (lseek (FileHandle, offset, SEEK_END) == -1, wstring (Path));
	}

	void File::SetCloseOnExec () const
	{
		if_debug (ValidateState());
		int flags = fcntl (FileHandle, F_GETFD);
		throw_sys_sub_if (flags == -1, wstring (Path));
		throw_sys_sub_if (fcntl (FileHandle, F_SETFD, flags | FD_CLOEXEC) == -1, wstring (Path));
	}

	void File::SetLength (uint64 length) const
	{
		if_debug (ValidateState());
		throw_sys_sub_if (ftruncate (FileHandle, length) == -1, wstring (Path));
	}

	void File::Write (const ConstBufferPtr &buffer) const
	{
		if_debug (ValidateState());

#ifdef TC_TRACE_FILE_OPERATIONS
		TraceFileOperation (FileHandle, Path, true, buffer.Size());
#endif
		WriteAllToDescriptor (FileHandle, buffer.Get(), buffer.Size(), wstring (Path));
	}

	void File::WriteAt (const ConstBufferPtr &buffer, uint64 position) const
	{
		if_debug (ValidateState());

#ifdef TC_TRACE_FILE_OPERATIONS
		TraceFileOperation (FileHandle, Path, true, buffer.Size(), position);
#endif
		const uint64 maximumOffset = static_cast <uint64> (std::numeric_limits <off_t>::max());
		size_t remaining = buffer.Size();
		if (position > maximumOffset || remaining > maximumOffset - position)
			throw SystemException (SRC_POS, wstring (Path), EOVERFLOW);

		const uint8 *data = buffer.Get();
		do
		{
			const ssize_t count = pwrite (FileHandle, data, remaining, static_cast <off_t> (position));
			if (count < 0)
			{
				const int error = errno;
				if (error == EINTR)
					continue;
				throw SystemException (SRC_POS, wstring (Path), error);
			}
			if (count == 0)
			{
				if (remaining != 0)
					throw SystemException (SRC_POS, wstring (Path), EIO);
				return;
			}

			// A short write has already written this prefix.
			data += count;
			remaining -= static_cast <size_t> (count);
			position += static_cast <uint64> (count);
		} while (remaining != 0);
	}
}
