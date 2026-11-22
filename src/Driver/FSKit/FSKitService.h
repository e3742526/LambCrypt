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
		int TryReserveSlot (VolumeSlotNumber slot);
		uint64 Mount (const shared_ptr <Volume> &volume, VolumeSlotNumber slot, const string &mountPoint,
			int slotReservation, int &activationChannel);
		void ObserveAttachedMedia (int activationChannel, const DevicePath &device);
		void ObserveLateAttachedMedia (int activationChannel);
		DevicePath GetAttachedDiskImageDevice (const DirectoryPath &mountPoint);
		int AcquireUnmountLock (const DirectoryPath &mountPoint);
		void UnmountAuxiliary (const DirectoryPath &mountPoint, bool force);
		void WaitForServiceExit (const DirectoryPath &mountPoint);
	}
}

#endif
