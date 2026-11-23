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

#include <algorithm>
#include <fstream>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <vector>
#include <CoreFoundation/CoreFoundation.h>
#include <sys/param.h>
#include <sys/ucred.h>
#include <sys/mount.h>
#include <sys/sysctl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <uuid/uuid.h>
#include "CoreMacOSX.h"
#include "Driver/Fuse/FuseService.h"
#ifdef VC_MACOSX_FSKIT
#include "FatBootSector.h"
#include "Driver/FSKit/FSKitService.h"
#endif
#include "Core/Unix/CoreServiceProxy.h"
#include "Platform/FileStream.h"
#include "Platform/MemoryStream.h"
#include "Platform/Serializable.h"
#include "Platform/SystemLog.h"

namespace VeraCrypt
{
	// RAII wrapper so CFRelease is never forgotten on early returns / exceptions.
	class CFHolder
	{
	public:
		explicit CFHolder (CFTypeRef ref = nullptr) : Ref (ref) { }
		~CFHolder () { if (Ref) CFRelease (Ref); }
		CFTypeRef Get () const { return Ref; }
	private:
		CFHolder (const CFHolder &);
		CFHolder &operator= (const CFHolder &);
		CFTypeRef Ref;
	};

	static string CFStringToStdString (CFStringRef cfStr)
	{
		if (!cfStr)
			return string();

		CFIndex length = CFStringGetLength (cfStr);
		CFIndex maxSize = CFStringGetMaximumSizeForEncoding (length, kCFStringEncodingUTF8) + 1;
		if (maxSize <= 0)
			return string();

		vector <char> buffer ((size_t) maxSize);
		if (!CFStringGetCString (cfStr, &buffer[0], maxSize, kCFStringEncodingUTF8))
			return string();

		return string (&buffer[0]);
	}

	// Fetch a string value from a CFDictionary by (C-string) key; empty if absent
	// or not a string.
	static string CFDictionaryGetStdString (CFDictionaryRef dict, const char *key)
	{
		if (!dict)
			return string();

		CFHolder cfKey (CFStringCreateWithCString (kCFAllocatorDefault, key, kCFStringEncodingUTF8));
		if (!cfKey.Get())
			return string();

		CFTypeRef value = CFDictionaryGetValue (dict, cfKey.Get());	// borrowed reference
		if (!value || CFGetTypeID (value) != CFStringGetTypeID())
			return string();

		return CFStringToStdString ((CFStringRef) value);
	}

	// Parse an hdiutil -plist (XML) document into a CFPropertyList. Returns nullptr
	// on failure; the caller owns the result and must CFRelease it.
	static CFPropertyListRef ParsePropertyList (const string &xml)
	{
		if (xml.empty())
			return nullptr;

		CFHolder data (CFDataCreate (kCFAllocatorDefault, (const UInt8 *) xml.data(), (CFIndex) xml.size()));
		if (!data.Get())
			return nullptr;

		return CFPropertyListCreateWithData (kCFAllocatorDefault, (CFDataRef) data.Get(), kCFPropertyListImmutable, nullptr, nullptr);
	}

	static string CanonicalizeDiskImagePath (const string &path)
	{
		char *canonicalPath = realpath (path.c_str(), NULL);
		throw_sys_sub_if (canonicalPath == NULL, path);
		finally_do_arg (char *, canonicalPath, { free (finally_arg); });
		return canonicalPath;
	}

	// Walk a "system-entities" array (from hdiutil attach/info). Prefer the entity
	// that carries a mount-point; otherwise fall back to the first dev-entry.
	static bool ExtractDeviceAndMountPointFromEntities (CFArrayRef entities, DevicePath &device, DirectoryPath &mountPoint)
	{
		if (!entities || CFGetTypeID (entities) != CFArrayGetTypeID())
			return false;

		string firstDevice;
		string mountedDevice;
		string mountedPath;

		CFIndex count = CFArrayGetCount (entities);
		for (CFIndex i = 0; i < count; ++i)
		{
			CFTypeRef entry = CFArrayGetValueAtIndex (entities, i);	// borrowed reference
			if (!entry || CFGetTypeID (entry) != CFDictionaryGetTypeID())
				continue;

			CFDictionaryRef entryDict = (CFDictionaryRef) entry;

			string devEntry = StringConverter::Trim (CFDictionaryGetStdString (entryDict, "dev-entry"));
			if (devEntry.empty())
				continue;

			if (firstDevice.empty())
				firstDevice = devEntry;

			string currentMountPoint = CFDictionaryGetStdString (entryDict, "mount-point");
			if (!currentMountPoint.empty())
			{
				mountedDevice = devEntry;
				mountedPath = currentMountPoint;
				break;
			}
		}

		if (!mountedDevice.empty())
		{
			device = mountedDevice;
			mountPoint = mountedPath;
			return true;
		}

		if (!firstDevice.empty())
		{
			device = firstDevice;
			return true;
		}

		return false;
	}

	// Parse "hdiutil attach -plist" output (top-level dict with "system-entities").
	static bool ExtractDiskImageDeviceAndMountPoint (const string &attachXml, DevicePath &device, DirectoryPath &mountPoint,
		bool requireSingleEntity = false)
	{
		CFHolder plist (ParsePropertyList (attachXml));
		if (!plist.Get() || CFGetTypeID (plist.Get()) != CFDictionaryGetTypeID())
			return false;

		CFTypeRef entities = CFDictionaryGetValue ((CFDictionaryRef) plist.Get(), CFSTR ("system-entities"));	// borrowed
		if (!entities || CFGetTypeID (entities) != CFArrayGetTypeID())
			return false;
		if (requireSingleEntity && CFArrayGetCount ((CFArrayRef) entities) != 1)
			return false;

		return ExtractDeviceAndMountPointFromEntities ((CFArrayRef) entities, device, mountPoint);
	}

	static string GetDiskImageInventory ()
	{
		list <string> args;
		args.push_back ("info");
		args.push_back ("-plist");
		return Process::ExecuteBounded ("/usr/bin/hdiutil", args, 2000);
	}

	static bool FindDiskImageInfoByImagePath (const string &xml, const string &imagePath, DevicePath &device, DirectoryPath &mountPoint,
		bool imagePathIsCanonical = false, bool requireCompleteInventory = false)
	{
		CFHolder plist (ParsePropertyList (xml));
		if (!plist.Get() || CFGetTypeID (plist.Get()) != CFDictionaryGetTypeID())
			throw ParameterIncorrect (SRC_POS);
		CFTypeRef images = CFDictionaryGetValue ((CFDictionaryRef) plist.Get(), CFSTR ("images"));
		if (!images || CFGetTypeID (images) != CFArrayGetTypeID())
			throw ParameterIncorrect (SRC_POS);
		CFArrayRef imageArray = (CFArrayRef) images;
		const CFIndex imageCount = CFArrayGetCount (imageArray);
		// An empty inventory proves absence without accessing the backing filesystem.
		if (imageCount == 0)
			return false;

		const string canonicalImagePath = imagePathIsCanonical ? imagePath : CanonicalizeDiskImagePath (imagePath);
		size_t imageSeparator = canonicalImagePath.find_last_of ('/');
		if (imageSeparator == string::npos || imageSeparator == 0)
			throw ParameterIncorrect (SRC_POS);
		size_t auxiliarySeparator = canonicalImagePath.find_last_of ('/', imageSeparator - 1);
		if (auxiliarySeparator == string::npos)
			throw ParameterIncorrect (SRC_POS);
		const string imageSuffix = canonicalImagePath.substr (auxiliarySeparator);

		bool uncertain = false;
		DevicePath matchedDevice;
		DirectoryPath matchedMount;
		for (CFIndex i = 0; i < imageCount; ++i)
		{
			CFTypeRef image = CFArrayGetValueAtIndex (imageArray, i);
			if (!image || CFGetTypeID (image) != CFDictionaryGetTypeID())
			{
				uncertain = true;
				continue;
			}
			CFDictionaryRef imageDict = (CFDictionaryRef) image;
			string currentImagePath = CFDictionaryGetStdString (imageDict, "image-path");
			if (currentImagePath.empty())
			{
				uncertain = true;
				continue;
			}
			if (currentImagePath != canonicalImagePath)
			{
				// Resolve only plausible aliases, such as an older TMPDIR spelling.
				if (currentImagePath[0] != '/' || currentImagePath.size() < imageSuffix.size()
					|| currentImagePath.compare (currentImagePath.size() - imageSuffix.size(), imageSuffix.size(), imageSuffix) != 0)
					continue;
				try
				{
					if (CanonicalizeDiskImagePath (currentImagePath) != canonicalImagePath) continue;
				}
				catch (const exception &)
				{
					uncertain = true;
					continue;
				}
			}

			CFTypeRef entities = CFDictionaryGetValue (imageDict, CFSTR ("system-entities"));
			DevicePath currentDevice;
			DirectoryPath currentMount;
			if (!entities || CFGetTypeID (entities) != CFArrayGetTypeID()
				|| !ExtractDeviceAndMountPointFromEntities ((CFArrayRef) entities, currentDevice, currentMount))
				throw ParameterIncorrect (SRC_POS);
			// Detach acts on the selected device. Conflicting records cannot
			// establish which attachment is safe to use.
			if (!matchedDevice.IsEmpty() && (currentDevice != matchedDevice || currentMount != matchedMount))
				throw ExternalException (SRC_POS, L"macOS reported conflicting attachments for the LambCrypt disk image.");
			matchedDevice = currentDevice;
			matchedMount = currentMount;
		}
		// Discovery can display a known match from a partial inventory.
		// Detach needs enough evidence to rule out another matching record.
		if (uncertain && (requireCompleteInventory || matchedDevice.IsEmpty()))
			throw ParameterIncorrect (SRC_POS);
		if (!matchedDevice.IsEmpty())
		{
			device = matchedDevice;
			mountPoint = matchedMount;
			return true;
		}
		return false;
	}

	CoreMacOSX::CoreMacOSX ()
	{
	}

	CoreMacOSX::~CoreMacOSX ()
	{
	}

#ifdef VC_MACOSX_FSKIT
	DevicePath FSKit::GetAttachedDiskImageDevice (const DirectoryPath &mountPoint)
	{
		DevicePath device;
		DirectoryPath innerMount;
		FindDiskImageInfoByImagePath (GetDiskImageInventory(),
			string (mountPoint) + FuseService::GetVolumeImagePath(), device, innerMount, false, true);
		return device;
	}

	bool FSKit::IsDiskImageAbsentAfterAuxiliaryUnmount (const DirectoryPath &mountPoint)
	{
		// The worker was given the canonical auxiliary path at startup. The
		// image file may no longer resolve after the auxiliary mount disappears.
		DevicePath device;
		DirectoryPath innerMount;
		return !FindDiskImageInfoByImagePath (GetDiskImageInventory(),
			string (mountPoint) + FuseService::GetVolumeImagePath(), device, innerMount, true);
	}

	static void ConfirmDiskImageMedia (const DirectoryPath &auxiliary, const DevicePath &device, uint64 expectedMedia)
	{
		try
		{
			if (expectedMedia != 0 && FSKit::GetAttachedDiskImageDevice (auxiliary) == device
				&& FSKit::GetMediaIdentity (device) == expectedMedia)
				return;
		}
		catch (const exception &error) { SystemLog::WriteException (error); }

		throw MountServiceCleanupFailed (SRC_POS, L"macOS could not confirm the identity of the attached disk image: "
			+ wstring (auxiliary));
	}
#endif

	shared_ptr <VolumeInfo> CoreMacOSX::ValidateMountedVolume (shared_ptr <VolumeInfo> volume) const
	{
		if (!volume || volume->AuxMountPoint.IsEmpty()) throw ParameterIncorrect (SRC_POS);
		MountedFilesystemList before = GetMountedFilesystems (DevicePath(), volume->AuxMountPoint);
		if (before.size() != 1) throw MountServiceUnavailable (SRC_POS, wstring (volume->AuxMountPoint));
		shared_ptr <VolumeInfo> current = ReadAuxiliaryVolumeInfo (volume->AuxMountPoint);
		MountedFilesystemList after = GetMountedFilesystems (DevicePath(), volume->AuxMountPoint);
		if (after.size() != 1 || before.front()->MountId[0] != after.front()->MountId[0]
			|| before.front()->MountId[1] != after.front()->MountId[1]
			|| current->SerialInstanceNumber != volume->SerialInstanceNumber
			|| current->SlotNumber != volume->SlotNumber || current->Path != volume->Path)
			throw MountServiceUnavailable (SRC_POS, wstring (volume->AuxMountPoint));
		return current;
	}

	shared_ptr <VolumeInfo> CoreMacOSX::DismountVolume (shared_ptr <VolumeInfo> mountedVolume, bool ignoreOpenFiles, bool syncVolumeInfo)
	{
		if (!mountedVolume || mountedVolume->AuxMountPoint.IsEmpty())
			throw ParameterIncorrect (SRC_POS);
#ifdef VC_MACOSX_FSKIT
		const bool fskitMount = FSKit::IsAuxiliaryMountPoint (mountedVolume->AuxMountPoint);
#endif
#ifdef VC_MACOSX_FUSET
		// Validate the mount and check the service protocol before detaching
		// the disk image. Retain its identity independently of SMB metadata.
		const FuseService::DismountRequest dismountRequest = FuseService::PrepareDismount (mountedVolume->AuxMountPoint,
			mountedVolume->SerialInstanceNumber, mountedVolume->SlotNumber, ignoreOpenFiles);
#else
		mountedVolume = ValidateMountedVolume (mountedVolume);
#endif

#ifdef VC_MACOSX_FSKIT
		// Hold the same lock from disk-image discovery through auxiliary
		// unmount so a competing LambCrypt request cannot reuse the BSD disk.
		int unmountLock = fskitMount ? FSKit::AcquireUnmountLock (mountedVolume->AuxMountPoint) : -1;
		finally_do_arg (int &, unmountLock, { if (finally_arg >= 0) close (finally_arg); });
#endif
		// Resolve ownership immediately before detach, including retries after a
		// busy auxiliary unmount or an external eject. BSD disk numbers are reused.
#ifdef VC_MACOSX_FUSET
		if (FuseService::IsDismountMountPresent (dismountRequest))
		{
#endif
		UpdateMountedVolumeInfo (mountedVolume);
#ifdef VC_MACOSX_FSKIT
		const uint64 attachedMedia = fskitMount && !mountedVolume->VirtualDevice.IsEmpty()
			? FSKit::GetMediaIdentity (mountedVolume->VirtualDevice) : 0;
#endif
#ifndef VC_MACOSX_FUSET
		ValidateMountedVolume (mountedVolume);
#endif

		const bool hasDevice = !mountedVolume->VirtualDevice.IsEmpty();
		const bool hasBlockDevice = hasDevice && mountedVolume->VirtualDevice.IsBlockDevice();
#ifdef VC_MACOSX_FSKIT
		// An attached image with an unusable device still owns its backing mount.
		// Only confirmed absence permits skipping detach for an FSKit volume.
		if (fskitMount && hasDevice && !hasBlockDevice)
			throw DismountServiceCleanupFailed (SRC_POS,
				L"macOS did not confirm a block device for the attached disk image: " + wstring (mountedVolume->VirtualDevice));
#endif
		if (hasBlockDevice
#ifdef VC_MACOSX_FUSET
			&& FuseService::IsDismountMountPresent (dismountRequest)
#endif
			)
		{
			list <string> args;
			args.push_back ("detach");
			args.push_back (mountedVolume->VirtualDevice);

			if (ignoreOpenFiles)
				args.push_back ("-force");

			try
			{
#ifdef VC_MACOSX_FSKIT
				if (fskitMount)
				{
					try { ConfirmDiskImageMedia (mountedVolume->AuxMountPoint, mountedVolume->VirtualDevice, attachedMedia); }
					catch (const MountServiceCleanupFailed &)
					{
						throw DismountServiceCleanupFailed (SRC_POS, L"macOS could not confirm the identity of the disk image to detach: "
							+ wstring (mountedVolume->AuxMountPoint));
					}
					Process::ExecuteBounded ("/usr/bin/hdiutil", args, 30000);
				}
				else
#endif
				Process::Execute ("/usr/bin/hdiutil", args);
			}
#ifdef VC_MACOSX_FSKIT
			catch (const TimeOut &)
			{
				// The OS can still be detaching the image. Keep its backing
				// mount alive and report that teardown could not be confirmed.
				throw DismountServiceCleanupFailed (SRC_POS,
					L"macOS did not confirm disk image detach: " + wstring (mountedVolume->VirtualDevice));
			}
#endif
			catch (ExecutedProcessFailed &e)
			{
				if (!ignoreOpenFiles)
				{
					string err = e.GetErrorOutput();

					if (e.GetExitCode() == EBUSY || err.find ("couldn't unmount") != string::npos
						|| err.find ("busy") != string::npos
						|| err.find ("49153") != string::npos)
					{
						throw MountedVolumeInUse (SRC_POS);
					}
				}

				throw;
			}
#ifdef VC_MACOSX_FSKIT
			if (fskitMount)
			{
				// A successful detach only covers the selected device. Confirm
				// the backing image is no longer attached before unmounting it.
				DevicePath remainingDevice;
				try { remainingDevice = FSKit::GetAttachedDiskImageDevice (mountedVolume->AuxMountPoint); }
				catch (const exception &error)
				{
					throw DismountServiceCleanupFailed (SRC_POS, L"macOS did not confirm disk image detach: "
						+ StringConverter::ToExceptionString (error));
				}
				if (!remainingDevice.IsEmpty())
					throw DismountServiceCleanupFailed (SRC_POS, L"macOS did not confirm disk image detach: still attached at "
						+ wstring (remainingDevice));
			}
#endif
		}

		const bool refreshVolume = syncVolumeInfo || mountedVolume->Protection == VolumeProtection::HiddenVolumeReadOnly;
#ifdef VC_MACOSX_FSKIT
		if (fskitMount && (refreshVolume || mountedVolume->Protection != VolumeProtection::ReadOnly))
		{
			// Disk Images has released its writer. Verify that the encrypted
			// file is synced before removing its worker.
			try { FSKit::FlushVolume (*mountedVolume); }
			catch (const exception &error)
			{
				throw DismountServiceCleanupFailed (SRC_POS, L"Could not flush the FSKit volume: "
					+ StringConverter::ToExceptionString (error));
			}
		}
		else
#endif
		if (refreshVolume)
			sync();

		if (refreshVolume)
		{
			// Refresh only the captured service. Other users' auxiliary mounts
			// must not interrupt teardown after the disk image has been detached.
			mountedVolume = ValidateMountedVolume (mountedVolume);
		}

#ifdef VC_MACOSX_FUSET
		}
		// The service unmounts SMB while its FUSE loop can still answer requests.
		if (!dismountRequest.LegacyService)
		{
			try
			{
				if (FuseService::IsDismountMountPresent (dismountRequest))
					FuseService::RequestDismount (dismountRequest);
				FuseService::WaitForDismount (dismountRequest.ProcessId, mountedVolume->AuxMountPoint, mountedVolume->SlotNumber, 10000, dismountRequest.ProcessStartTime);
			}
			catch (DismountServiceCleanupFailed &) { throw; }
			catch (exception &e)
			{
				// Without SMB, the volume can no longer be discovered or retried.
				// Report the unconfirmed service exit with the original details.
				if (FuseService::IsDismountMountPresent (dismountRequest))
					throw;
				throw DismountServiceCleanupFailed (SRC_POS, StringConverter::ToExceptionString (e));
			}
		}
		else
			FuseService::DismountLegacy (dismountRequest);
#else
		list <string> args;
#ifdef VC_MACOSX_FSKIT
		const bool forceAuxiliaryUnmount = fskitMount && ignoreOpenFiles;
#endif
		args.push_back ("--");
		args.push_back (mountedVolume->AuxMountPoint);

		for (int t = 0; true; t++)
		{
#ifdef VC_MACOSX_FSKIT
			// Recheck ownership after detaching the disk image and between
			// auxiliary unmount attempts, even for an ordinary dismount.
			if (fskitMount)
				ValidateMountedVolume (mountedVolume);
#endif
			try
			{
#ifdef VC_MACOSX_FSKIT
				if (fskitMount)
					FSKit::UnmountAuxiliary (mountedVolume->AuxMountPoint, forceAuxiliaryUnmount);
				else
#endif
				Process::Execute ("/sbin/umount", args);
				break;
			}
#ifdef VC_MACOSX_FSKIT
			catch (const TimeOut &)
			{
				throw DismountServiceCleanupFailed (SRC_POS,
					L"macOS did not confirm auxiliary unmount: " + wstring (mountedVolume->AuxMountPoint));
			}
#endif
			catch (ExecutedProcessFailed&)
			{
				if (t > 10)
					throw;
				Thread::Sleep (200);
			}
		}
#endif

		// Current services remove their original directory. Older development
		// services may leave it behind; rmdir only removes an empty directory
		// and cannot follow a replacement symlink or remove a mounted filesystem.
		if (rmdir (string (mountedVolume->AuxMountPoint).c_str()) == 0)
		{
#ifdef VC_MACOSX_FUSET
			FuseService::RemoveAuxMountParent (mountedVolume->AuxMountPoint);
#endif
		}

#ifdef VC_MACOSX_FSKIT
		if (fskitMount)
		{
			// The worker needs the lock to verify its mount is gone and exit.
			close (unmountLock);
			unmountLock = -1;
			FSKit::WaitForServiceExit (mountedVolume->AuxMountPoint);
		}
#endif
		return mountedVolume;
	}

	static void ClearDiskImageInfo (shared_ptr <VolumeInfo> volume)
	{
		volume->VirtualDevice = DevicePath();
		volume->MountPoint = DirectoryPath();
		volume->Discovery = VolumeInfo::DiscoveryUnknown;
	}

	void CoreMacOSX::UpdateMountedVolumesInfo (VolumeInfoList &volumes) const
	{
		foreach (shared_ptr <VolumeInfo> volume, volumes)
			ClearDiskImageInfo (volume);
		if (volumes.empty()) return;
		try
		{
			// One inventory per enumeration, regardless of the volume count.
			const string inventory = GetDiskImageInventory();
			foreach (shared_ptr <VolumeInfo> volume, volumes)
			{
				try { UpdateMountedVolumeInfo (volume, inventory); }
				catch (exception &e) { SystemLog::WriteException (e); }
			}
		}
		catch (exception &e) { SystemLog::WriteException (e); }
	}

	void CoreMacOSX::UpdateMountedVolumeInfo (shared_ptr <VolumeInfo> volume) const
	{
		if (!volume) return;
		ClearDiskImageInfo (volume);
		try { UpdateMountedVolumeInfo (volume, GetDiskImageInventory()); }
		catch (exception &e)
		{
			throw VolumeDiscoveryFailed (SRC_POS, StringConverter::ToExceptionString (e));
		}
	}

	void CoreMacOSX::UpdateMountedVolumeInfo (shared_ptr <VolumeInfo> volume, const string &inventory) const
	{
		ClearDiskImageInfo (volume);
		if (volume->AuxMountPoint.IsEmpty()) throw ParameterIncorrect (SRC_POS);
		DevicePath device;
		DirectoryPath mountPoint;
		if (!FindDiskImageInfoByImagePath (inventory, string (volume->AuxMountPoint) + FuseService::GetVolumeImagePath(), device, mountPoint))
		{
			volume->Discovery = VolumeInfo::ImageAbsent;
			return;
		}
		volume->VirtualDevice = device;
		volume->MountPoint = mountPoint;
		volume->Discovery = VolumeInfo::ImageAttached;
		if (volume->MountPoint.IsEmpty())
		{
			try
			{
				MountedFilesystemList filesystems = GetMountedFilesystems (device);
				if (!filesystems.empty()) volume->MountPoint = filesystems.front()->MountPoint;
			}
			catch (...) { }
		}
	}

	// Strict /dev/diskN or /dev/rdiskN (optionally sN) device-node check so a value
	// can be embedded safely in a generated shell command.
	static bool IsPlainDiskDevicePath (const string &path)
	{
		size_t index;
		if (path.compare (0, 10, "/dev/rdisk") == 0)
			index = 10;
		else if (path.compare (0, 9, "/dev/disk") == 0)
			index = 9;
		else
			return false;

		size_t digitsStart = index;
		while (index < path.size() && path[index] >= '0' && path[index] <= '9')
			++index;
		if (index == digitsStart)
			return false;

		if (index == path.size())
			return true;

		if (path[index++] != 's')
			return false;

		size_t sliceStart = index;
		while (index < path.size() && path[index] >= '0' && path[index] <= '9')
			++index;

		return index > sliceStart && index == path.size();
	}

	static int64_t GetDiskMediaRegistryId (const string &bsdName)
	{
		const string inventory = Process::ExecuteBounded ("/usr/sbin/ioreg", {"-a", "-r", "-c", "IOMedia", "-d", "1"}, 2000);
		CFHolder plist (ParsePropertyList (inventory));
		if (!plist.Get() || CFGetTypeID (plist.Get()) != CFArrayGetTypeID())
			throw ParameterIncorrect (SRC_POS);

		CFArrayRef entries = (CFArrayRef) plist.Get();
		int64_t identity = 0;
		for (CFIndex index = 0; index < CFArrayGetCount (entries); ++index)
		{
			CFTypeRef entry = CFArrayGetValueAtIndex (entries, index);
			if (!entry || CFGetTypeID (entry) != CFDictionaryGetTypeID()
				|| CFDictionaryGetStdString ((CFDictionaryRef) entry, "BSD Name") != bsdName)
				continue;
			CFTypeRef value = CFDictionaryGetValue ((CFDictionaryRef) entry, CFSTR ("IORegistryEntryID"));
			if (identity != 0 || !value || CFGetTypeID (value) != CFNumberGetTypeID()
				|| !CFNumberGetValue ((CFNumberRef) value, kCFNumberSInt64Type, &identity) || identity <= 0)
				throw ParameterIncorrect (SRC_POS);
		}
		if (identity == 0)
			throw MountServiceUnavailable (SRC_POS, StringConverter::ToWide (bsdName));
		return identity;
	}

	static string BuildFilesystemCheckScript (bool repair, const string &device, const string &bsdName,
		int64_t mediaId, const string &bootSession)
	{
		const string verb = repair ? "repairVolume" : "verifyVolume";
		// The device and boot session were validated by the caller. The ID
		// distinguishes attachments that macOS gives the same disk number.
		return string ("#!/bin/sh\n")
			+ "trap 'rm -f \"$0\"' EXIT\n"
			+ "expected_boot='" + bootSession + "'\n"
			+ "expected_media='" + std::to_string (mediaId) + "'\n"
			+ "expected_device='" + bsdName + "'\n"
			+ R"SH(
same_media() {
    boot=$(/usr/sbin/sysctl -n kern.bootsessionuuid) || return 1
    [ "$boot" = "$expected_boot" ] || return 1
    inventory=$(/usr/sbin/ioreg -a -r -c IOMedia -d 1) || return 1
    index=0
    while identity=$(printf '%s' "$inventory" | /usr/bin/plutil -extract "$index.IORegistryEntryID" raw -expect integer -o - - 2>/dev/null); do
        if [ "$identity" = "$expected_media" ]; then
            name=$(printf '%s' "$inventory" | /usr/bin/plutil -extract "$index.BSD Name" raw -expect string -o - -) || return 1
            [ "$name" = "$expected_device" ]
            return $?
        fi
        index=$((index + 1))
    done
    return 1
}

if same_media; then
)SH"
			+ "    /usr/sbin/diskutil " + verb + " '" + device + "'\n"
			+ R"SH(    status=$?
else
    echo 'The selected volume is no longer confirmed. Select it again in LambCrypt.'
    status=1
fi
echo
echo 'Press Enter to close this window.'
read dummy
exit "$status"
)SH";
	}

	void CoreMacOSX::CheckFilesystem (shared_ptr <VolumeInfo> mountedVolume, bool repair) const
	{
		mountedVolume = ValidateMountedVolume (mountedVolume);
		UpdateMountedVolumeInfo (mountedVolume);
		ValidateMountedVolume (mountedVolume);
		// Honor the check-vs-repair distinction by running diskutil on the VeraCrypt
		// virtual device (diskutil unmounts the inner filesystem itself as needed).
		// The Core layer has no GUI, so results are shown in a Terminal window via a
		// temporary .command script. Falls back to launching Disk Utility.app.
		if (mountedVolume && !mountedVolume->VirtualDevice.IsEmpty())
		{
			const string device = mountedVolume->VirtualDevice;

			if (IsPlainDiskDevicePath (device))
			{
				const string bsdName = device.substr (device.find ("disk"));
				const int64_t mediaId = GetDiskMediaRegistryId (bsdName);
				// Confirm the media still belongs to the selected backing image
				// after obtaining its registry identity.
				UpdateMountedVolumeInfo (mountedVolume);
				ValidateMountedVolume (mountedVolume);
				if (string (mountedVolume->VirtualDevice) != device)
					throw MountServiceUnavailable (SRC_POS, wstring (mountedVolume->AuxMountPoint));
				const string bootSession = StringConverter::Trim (Process::ExecuteBounded ("/usr/sbin/sysctl",
					{"-n", "kern.bootsessionuuid"}, 2000));
				uuid_t parsedSession;
				if (bootSession.size() != 36 || uuid_parse (bootSession.c_str(), parsedSession) != 0)
					throw ParameterIncorrect (SRC_POS);

				try
				{
					// Create the script securely: a predictable name in the
					// world-writable /tmp invites a symlink/race attack (the file is
					// later executed, and this path can run elevated). Use the
					// per-user temp directory (owned, 0700) and mkstemps(), which
					// creates the file atomically with O_EXCL while keeping the
					// ".command" suffix that makes /usr/bin/open launch Terminal.
					string tempDir;
					{
						char dirBuf[MAXPATHLEN];
						size_t n = confstr (_CS_DARWIN_USER_TEMP_DIR, dirBuf, sizeof (dirBuf));
						if (n > 0 && n <= sizeof (dirBuf))
							tempDir = dirBuf;
						else if (const char *t = getenv ("TMPDIR"))
							tempDir = t;
						else
							tempDir = "/tmp/";
					}
					if (tempDir.empty() || tempDir[tempDir.size() - 1] != '/')
						tempDir += '/';

					const char suffix[] = ".command";
					string templ = tempDir + "LambCrypt-fsck-XXXXXXXX" + suffix;
					vector <char> templBuf (templ.begin(), templ.end());
					templBuf.push_back ('\0');

					int fd = mkstemps (&templBuf[0], static_cast <int> (sizeof (suffix) - 1));
					if (fd == -1)
						throw ParameterIncorrect (SRC_POS);

					const string scriptPath (&templBuf[0]);

					try
					{
						const string contents = BuildFilesystemCheckScript (repair, device, bsdName, mediaId, bootSession);

						size_t off = 0;
						while (off < contents.size())
						{
							ssize_t written = write (fd, contents.data() + off, contents.size() - off);
							if (written < 0)
							{
								if (errno == EINTR)
									continue;
								throw ParameterIncorrect (SRC_POS);
							}
							off += static_cast <size_t> (written);
						}

						// fchmod on the fd (not the path) keeps this race-free.
						if (fchmod (fd, 0700) != 0)
							throw ParameterIncorrect (SRC_POS);

						if (close (fd) != 0)	// surfaces deferred write errors
							throw ParameterIncorrect (SRC_POS);
						fd = -1;
					}
					catch (...)
					{
						if (fd != -1)
							close (fd);
						unlink (scriptPath.c_str());
						throw;
					}

					try
					{
						list <string> openArgs;
						openArgs.push_back (scriptPath);
						Process::Execute ("/usr/bin/open", openArgs);
					}
					catch (...)
					{
						// open failed before Terminal could take ownership of the
						// script (the EXIT trap never runs), so remove it here
						// rather than leaking it into the temp directory.
						unlink (scriptPath.c_str());
						throw;
					}
					return;
				}
				catch (...)
				{
					// Fall back to Disk Utility below.
				}
			}
		}

		list <string> args;
		struct stat sb;

		if (stat("/Applications/Utilities/Disk Utility.app", &sb) == 0)
			args.push_back ("/Applications/Utilities/Disk Utility.app");
		else
			args.push_back ("/System/Applications/Utilities/Disk Utility.app");

		Process::Execute ("/usr/bin/open", args);
	}

#ifndef VC_MACOSX_FSKIT
	static bool AuxiliaryControlFileHasVirtualDevice (const DirectoryPath &auxMountPoint, const DevicePath &virtualDev, int retryCount = 50)
	{
		for (int t = 0; t < retryCount; ++t)
		{
			try
			{
				shared_ptr <File> controlFile (new File);
				controlFile->Open (string (auxMountPoint) + FuseService::GetControlPath());

				FileStream controlFileReader (controlFile);
				string controlFileData = controlFileReader.ReadToEnd();
				if (controlFileData.empty() || controlFileData.size() > 1024 * 1024)
					throw ParameterIncorrect (SRC_POS);

				shared_ptr <Stream> controlFileStream (new MemoryStream (ConstBufferPtr ((const uint8 *) controlFileData.data(), controlFileData.size())));
				shared_ptr <VolumeInfo> mountedVol = Serializable::DeserializeNew <VolumeInfo> (controlFileStream);
				if (mountedVol && string (mountedVol->VirtualDevice) == string (virtualDev))
					return true;
			}
			catch (...) { }

			Thread::Sleep (100);
		}

		return false;
	}
#endif

	DevicePath CoreMacOSX::MountAuxVolumeImage (const DirectoryPath &auxMountPoint, const MountOptions &options,
		Volume *volume, bool useDefaultMountPoint) const
	{
#if !defined(VC_MACOSX_FUSET) && !defined(VC_MACOSX_FSKIT)
		// Check FUSE version
		char fuseVersionString[MAXHOSTNAMELEN + 1] = { 0 };
		size_t fuseVersionStringLength = MAXHOSTNAMELEN;
		int status;

		if ((status = sysctlbyname ("osxfuse.version.number", fuseVersionString, &fuseVersionStringLength, NULL, 0)) != 0)
		{
			fuseVersionStringLength = MAXHOSTNAMELEN;
			if ((status = sysctlbyname ("vfs.generic.osxfuse.version.number", fuseVersionString, &fuseVersionStringLength, NULL, 0)) != 0)
			{
				fuseVersionStringLength = MAXHOSTNAMELEN;
				if ((status = sysctlbyname ("vfs.generic.macfuse.version.number", fuseVersionString, &fuseVersionStringLength, NULL, 0)) != 0)
				{
					throw HigherFuseVersionRequired (SRC_POS);
				}
			}
		}

		// look for OSXFuse dynamic library
		struct stat sb;
		if (0 != stat("/usr/local/lib/libosxfuse_i64.2.dylib", &sb) && 0 != stat("/usr/local/lib/libfuse.dylib", &sb))
		{
			throw HigherFuseVersionRequired (SRC_POS);
		}

		vector <string> fuseVersion = StringConverter::Split (string (fuseVersionString), ".");
		if (fuseVersion.size() < 2)
			throw HigherFuseVersionRequired (SRC_POS);

		uint32 fuseVersionMajor = StringConverter::ToUInt32 (fuseVersion[0]);
		uint32 fuseVersionMinor = StringConverter::ToUInt32 (fuseVersion[1]);

		if (fuseVersionMajor < 2 || (fuseVersionMajor == 2 && fuseVersionMinor < 5))
			throw HigherFuseVersionRequired (SRC_POS);
#endif
		// Mount volume image
		string volImage = string (auxMountPoint) + FuseService::GetVolumeImagePath();

		list <string> args;
		args.push_back ("attach");
		args.push_back (volImage);
		args.push_back ("-plist");
		args.push_back ("-noautofsck");
		args.push_back ("-imagekey");
		args.push_back ("diskimage-class=CRawDiskImage");

		bool kernelFat = false;
#ifdef VC_MACOSX_FSKIT
		if (!options.NoFilesystem && volume)
		{
			SecureBuffer bootSector (volume->GetSectorSize());
			volume->ReadSectors (bootSector, 0);
			kernelFat = GetFatBootSectorType (bootSector.Ptr(), bootSector.Size(), volume->GetSize()) != 0;
		}

		// Default FAT directories need to be writable by the unprivileged
		// mounting user. Use a sibling of the auxiliary mount in its private
		// parent. The worker removes it after confirmed teardown.
		DirectoryPath kernelMountPoint;
		const int mountLock = kernelFat ? FSKit::AcquireUnmountLock (auxMountPoint) : -1;
		finally_do_arg (int, mountLock, { if (finally_arg >= 0) close (finally_arg); });
		if (kernelFat)
		{
			if (useDefaultMountPoint)
			{
				const string path = FSKit::GetKernelFatMountPoint (auxMountPoint);
				throw_sys_sub_if (mkdir (path.c_str(), 0700) != 0, path);
				kernelMountPoint = path;
			}
			else
			{
				if (!options.MountPoint || options.MountPoint->IsEmpty())
					throw ParameterIncorrect (SRC_POS);
				kernelMountPoint = CanonicalizeDiskImagePath (*options.MountPoint);
				ValidateMountPoint (kernelMountPoint);
				if (!GetMountedFilesystems (DevicePath(), kernelMountPoint).empty())
					throw MountedVolumeInUse (SRC_POS);
			}
		}
#endif

		if (!kernelFat && !options.NoFilesystem && options.MountPoint && !options.MountPoint->IsEmpty())
		{
			args.push_back ("-mount");
			args.push_back ("required");

			// Let the system specify mount point except when the user specified a non-default one
			if (string (*options.MountPoint).find (GetDefaultMountPointPrefix()) != 0)
			{
				args.push_back ("-mountpoint");
				args.push_back (*options.MountPoint);
			}
		}
		else
			args.push_back ("-nomount");

		if (options.Protection == VolumeProtection::ReadOnly)
			args.push_back ("-readonly");

		string xml;
#ifdef VC_MACOSX_FSKIT
		bool completionUnconfirmed = false;
#endif

		while (true)
		{
			try
			{
#ifdef VC_MACOSX_FSKIT
				xml = Process::ExecuteBounded ("/usr/bin/hdiutil", args, 30000, completionUnconfirmed);
#else
				xml = Process::Execute ("/usr/bin/hdiutil", args);
#endif
				break;
			}
			catch (ExecutedProcessFailed &e)
			{
#ifdef VC_MACOSX_FSKIT
				if (completionUnconfirmed)
					break;
#endif
				auto option = std::find (args.begin(), args.end(), "-noautofsck");
				if (option != args.end() && e.GetErrorOutput().find ("noautofsck") != string::npos)
				{
					args.erase (option);
					continue;
				}

				throw;
			}
#ifdef VC_MACOSX_FSKIT
			catch (...)
			{
				if (!completionUnconfirmed)
					throw;
				break;
			}
#endif
		}
#ifdef VC_MACOSX_FSKIT
		if (completionUnconfirmed)
		{
			// Disk Images can still publish after the child stops reporting.
			throw MountServiceCleanupFailed (SRC_POS,
				L"macOS did not confirm disk image attach: " + wstring (auxMountPoint) + L"/volume.dmg"
				L"\nThe worker retains this image until its attachment status can be confirmed."
				L"\nCheck Disk Images inventory for this exact path before retrying.");
		}
#endif

		DevicePath virtualDev;
		DirectoryPath mountPoint;
		if (!ExtractDiskImageDeviceAndMountPoint (xml, virtualDev, mountPoint, kernelFat)
			|| virtualDev.IsEmpty())
			throw ParameterIncorrect (SRC_POS);

#ifdef VC_MACOSX_FSKIT
		if (kernelFat)
		{
			const string device = virtualDev;
			if (!mountPoint.IsEmpty() || !IsPlainDiskDevicePath (device) || device.compare (0, 9, "/dev/disk") != 0
				|| device.find ('s', 9) != string::npos || !virtualDev.IsBlockDevice())
				throw ParameterIncorrect (SRC_POS);

			const uint64 media = FSKit::GetMediaIdentity (virtualDev);
			ConfirmDiskImageMedia (auxMountPoint, virtualDev, media);
			// Keep the raw device open so its BSD slot stays assigned while
			// mount_msdos resolves the corresponding block device by name.
			const string rawDevice = "/dev/r" + device.substr (5);
			const int mediaFd = open (rawDevice.c_str(), O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC);
			throw_sys_sub_if (mediaFd < 0, rawDevice);
			finally_do_arg (int, mediaFd, { close (finally_arg); });
			ConfirmDiskImageMedia (auxMountPoint, virtualDev, media);
			const bool readOnly = options.Protection == VolumeProtection::ReadOnly;
			try
			{
				Process::ExecuteBounded ("/sbin/mount_msdos",
					{"-o", readOnly ? "ro,nosuid,nodev" : "nosuid,nodev", virtualDev, kernelMountPoint}, 15000);
			}
			catch (const TimeOut &)
			{
				throw MountServiceCleanupFailed (SRC_POS, L"macOS did not confirm the kernel FAT mount: " + wstring (kernelMountPoint));
			}
			catch (const ExecutedProcessFailed &)
			{
				// Rollback may detach only if the failed command still refers
				// to this attachment.
				ConfirmDiskImageMedia (auxMountPoint, virtualDev, media);
				throw;
			}

			ConfirmDiskImageMedia (auxMountPoint, virtualDev, media);
			const MountedFilesystemList mounts = GetMountedFilesystems (virtualDev, kernelMountPoint);
			if (mounts.size() != 1 || mounts.front()->Type != "msdos"
				|| (mounts.front()->ExtendedFlags & MNT_EXT_FSKIT)
				|| bool (mounts.front()->Flags & MNT_RDONLY) != readOnly)
				throw ExternalException (SRC_POS, L"macOS did not report the expected kernel FAT mount and access mode.");
		}
#endif

#ifndef VC_MACOSX_FSKIT
		try
		{
			FuseService::SendAuxDeviceInfo (auxMountPoint, virtualDev);
#ifndef VC_MACOSX_FUSET
			if (!AuxiliaryControlFileHasVirtualDevice (auxMountPoint, virtualDev))
			{
				stringstream logMessage;
				logMessage << "LambCrypt auxiliary mount did not report hdiutil device after mount: "
					<< string (auxMountPoint) << FuseService::GetControlPath()
					<< ", expected " << string (virtualDev);
				SystemLog::WriteError (logMessage.str());

				throw TimeOut (SRC_POS);
			}
#endif
		}
		catch (...)
		{
			try
			{
				list <string> args;
				args.push_back ("detach");
				args.push_back (virtualDev);
				args.push_back ("-force");

				Process::Execute ("/usr/bin/hdiutil", args);
			}
			catch (ExecutedProcessFailed&) { }
			throw;
		}

#ifdef VC_MACOSX_FUSET
		if (!AuxiliaryControlFileHasVirtualDevice (auxMountPoint, virtualDev, 10))
		{
			stringstream logMessage;
			logMessage << "LambCrypt auxiliary mount did not report hdiutil device after mount: "
				<< string (auxMountPoint) << FuseService::GetControlPath()
				<< ", expected " << string (virtualDev)
				<< "; continuing with hdiutil device";
			SystemLog::WriteError (logMessage.str());
		}
#endif
#endif

		return virtualDev;
	}

	unique_ptr <CoreBase> Core (new CoreServiceProxy <CoreMacOSX>);
	unique_ptr <CoreBase> CoreDirect (new CoreMacOSX);
}
