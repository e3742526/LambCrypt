/*
 Copyright (c) 2026 LambCrypt contributors
 Governed by the Apache License 2.0, the full text of which is contained in
 the file License.txt included in LambCrypt binary and source code
 distribution packages.
*/

#ifndef TC_HEADER_Driver_FSKit_FSKitService
#define TC_HEADER_Driver_FSKit_FSKitService

#include "Volume/VolumeInfo.h"

namespace VeraCrypt
{
	namespace FSKit
	{
		string CreateMountPoint (const string &prefix);
		bool IsAuxiliaryMountPoint (const DirectoryPath &mountPoint);
		shared_ptr <VolumeInfo> ReadVolumeInfo (const DirectoryPath &mountPoint);
		void FlushVolume (const VolumeInfo &volume);
		void RemoveEmptyMountDirectory (const string &mountPoint);
		string GetKernelFatMountPoint (const string &mountPoint);
		int TryReserveSlot (VolumeSlotNumber slot);
		uint64 Mount (const shared_ptr <Volume> &volume, VolumeSlotNumber slot, const string &mountPoint,
			int slotReservation, int &activationChannel);
		void BeginDiskImageAttachment (int activationChannel);
		void ObserveAttachedMedia (int activationChannel, const DevicePath &device);
		void ObserveLateAttachedMedia (int activationChannel);
		DevicePath GetAttachedDiskImageDevice (const DirectoryPath &mountPoint);
		bool IsDiskImageAbsentAfterAuxiliaryUnmount (const DirectoryPath &mountPoint);
		uint64 GetMediaIdentity (const DevicePath &device);
		int AcquireUnmountLock (const DirectoryPath &mountPoint);
		void UnmountAuxiliary (const DirectoryPath &mountPoint, bool force);
		void WaitForServiceExit (const DirectoryPath &mountPoint);
	}
}

#endif
