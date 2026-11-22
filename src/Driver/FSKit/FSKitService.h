#ifndef TC_HEADER_Driver_FSKit_FSKitService
#define TC_HEADER_Driver_FSKit_FSKitService

#include "Volume/VolumeInfo.h"

namespace VeraCrypt
{
	namespace FSKit
	{
		string CreateMountPoint (const string &prefix);
		void RemoveEmptyMountDirectory (const string &mountPoint);
		uint64 Mount (const shared_ptr <Volume> &volume, VolumeSlotNumber slot, const string &mountPoint);
		void WaitForServiceExit (const DirectoryPath &mountPoint);
	}
}

#endif
