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

#ifndef TC_WINDOWS
#include <errno.h>
#endif
#include <algorithm>
#include "EncryptionModeXTS.h"
#include "Volume.h"
#include "VolumeHeader.h"
#include "VolumeLayout.h"
#include "Common/Crypto.h"

namespace VeraCrypt
{
	Volume::Volume ()
		: HiddenVolumeProtectionTriggered (false),
		SystemEncryption (false),
		VolumeDataOffset (0),
		VolumeDataSize (0),
		EncryptedDataSize (0),
		TopWriteOffset (0),
		TotalDataRead (0),
		TotalDataWritten (0),
		Pim (0),
		EncryptionNotCompleted (false)
	{
	}

	Volume::~Volume ()
	{
	}

	void Volume::CheckProtectedRange (uint64 writeHostOffset, uint64 writeLength)
	{
		uint64 writeHostEndOffset = writeHostOffset + writeLength - 1;

		if ((writeHostOffset < ProtectedRangeStart) ? (writeHostEndOffset >= ProtectedRangeStart) : (writeHostOffset <= ProtectedRangeEnd - 1))
		{
			HiddenVolumeProtectionTriggered = true;
			throw VolumeProtected (SRC_POS);
		}
	}

	void Volume::Close ()
	{
		if (VolumeFile.get() == nullptr)
			throw NotInitialized (SRC_POS);

		VolumeFile.reset();
	}

	shared_ptr <EncryptionAlgorithm> Volume::GetEncryptionAlgorithm () const
	{
		if_debug (ValidateState ());
		return EA;
	}

	shared_ptr <EncryptionMode> Volume::GetEncryptionMode () const
	{
		if_debug (ValidateState ());
		return EA->GetMode();
	}

	void Volume::Open (const VolumePath &volumePath, bool preserveTimestamps, shared_ptr <VolumePassword> password, int pim, shared_ptr <Pkcs5Kdf> kdf, shared_ptr <KeyfileList> keyfiles, bool emvSupportEnabled, VolumeProtection::Enum protection, shared_ptr <VolumePassword> protectionPassword, int protectionPim, shared_ptr <Pkcs5Kdf> protectionKdf, shared_ptr <KeyfileList> protectionKeyfiles, bool sharedAccessAllowed, VolumeType::Enum volumeType, bool useBackupHeaders, bool partitionInSystemEncryptionScope)
	{
		make_shared_auto (File, file);

		File::FileOpenFlags flags = (preserveTimestamps ? File::PreserveTimestamps : File::FlagsNone);
#ifdef TC_LINUX
		// An elevated process may be denied access to a volume file that the
		// requesting user can open, e.g. on a GVfs share.
		flags = static_cast <File::FileOpenFlags> (flags | File::AllowRequesterAccess);
#endif

		try
		{
			if (protection == VolumeProtection::ReadOnly)
				file->Open (volumePath, File::OpenRead, File::ShareRead, flags);
			else
				file->Open (volumePath, File::OpenReadWrite, File::ShareNone, flags);
		}
		catch (SystemException &e)
		{
			if (e.GetErrorCode() ==
#ifdef TC_WINDOWS
				ERROR_SHARING_VIOLATION)
#else
				EAGAIN)
#endif
			{
				if (!sharedAccessAllowed)
					throw VolumeHostInUse (SRC_POS);

				file->Open (volumePath, protection == VolumeProtection::ReadOnly ? File::OpenRead : File::OpenReadWrite, File::ShareReadWriteIgnoreLock, flags);
			}
			else
				throw;
		}

		return Open (file, password, pim, kdf, keyfiles, emvSupportEnabled, protection, protectionPassword, protectionPim, protectionKdf,protectionKeyfiles, volumeType, useBackupHeaders, partitionInSystemEncryptionScope);
	}

	void Volume::Open (shared_ptr <File> volumeFile, shared_ptr <VolumePassword> password, int pim, shared_ptr <Pkcs5Kdf> kdf, shared_ptr <KeyfileList> keyfiles, bool emvSupportEnabled, VolumeProtection::Enum protection, shared_ptr <VolumePassword> protectionPassword, int protectionPim, shared_ptr <Pkcs5Kdf> protectionKdf,shared_ptr <KeyfileList> protectionKeyfiles, VolumeType::Enum volumeType, bool useBackupHeaders, bool partitionInSystemEncryptionScope)
	{
		if (!volumeFile)
			throw ParameterIncorrect (SRC_POS);

		Protection = protection;
		VolumeFile = volumeFile;
		SystemEncryption = partitionInSystemEncryptionScope;

		try
		{
			VolumeHostSize = VolumeFile->Length();
			shared_ptr <VolumePassword> passwordKey = Keyfile::ApplyListToPassword (keyfiles, password, emvSupportEnabled);

			bool skipLayoutV1Normal = false;

			// Test volume layouts
			foreach (shared_ptr <VolumeLayout> layout, VolumeLayout::GetAvailableLayouts (volumeType))
			{
				if (skipLayoutV1Normal && typeid (*layout) == typeid (VolumeLayoutV1Normal))
				{
					// Skip VolumeLayoutV1Normal as it shares header location with VolumeLayoutV2Normal
					continue;
				}

				if (useBackupHeaders && !layout->HasBackupHeader())
					continue;

				SecureBuffer headerBuffer (layout->GetHeaderSize());

				if (layout->HasDriveHeader())
				{
					if (!partitionInSystemEncryptionScope)
						continue;

					if (!GetPath().IsDevice())
						throw PartitionDeviceRequired (SRC_POS);

					File driveDevice;
					driveDevice.Open (DevicePath (wstring (GetPath())).ToHostDriveOfPartition());

					int headerOffset = layout->GetHeaderOffset();

					if (headerOffset >= 0)
						driveDevice.SeekAt (headerOffset);
					else
						driveDevice.SeekEnd (headerOffset);

					if (driveDevice.Read (headerBuffer) != layout->GetHeaderSize())
						continue;
				}
				else
				{
					if (partitionInSystemEncryptionScope)
						continue;

					int headerOffset = useBackupHeaders ? layout->GetBackupHeaderOffset() : layout->GetHeaderOffset();

					if (headerOffset >= 0)
						VolumeFile->SeekAt (headerOffset);
					else
						VolumeFile->SeekEnd (headerOffset);

					if (VolumeFile->Read (headerBuffer) != layout->GetHeaderSize())
						continue;
				}

				EncryptionAlgorithmList layoutEncryptionAlgorithms = layout->GetSupportedEncryptionAlgorithms();
				EncryptionModeList layoutEncryptionModes = layout->GetSupportedEncryptionModes();

				if (typeid (*layout) == typeid (VolumeLayoutV2Normal))
				{
					skipLayoutV1Normal = true;

					// Test all algorithms and modes of VolumeLayoutV1Normal as it shares header location with VolumeLayoutV2Normal
					layoutEncryptionAlgorithms = EncryptionAlgorithm::GetAvailableAlgorithms();
					layoutEncryptionModes = EncryptionMode::GetAvailableModes();
				}

				shared_ptr <VolumeHeader> header = layout->GetHeader();

				if (header->Decrypt (headerBuffer, *passwordKey, pim, kdf, layout->GetSupportedKeyDerivationFunctions(), layoutEncryptionAlgorithms, layoutEncryptionModes))
				{
					// Header decrypted

					if (typeid (*layout) == typeid (VolumeLayoutV2Normal) && header->GetRequiredMinProgramVersion() < 0x10b)
					{
						// VolumeLayoutV1Normal has been opened as VolumeLayoutV2Normal
						layout.reset (new VolumeLayoutV1Normal);
						header->SetSize (layout->GetHeaderSize());
						layout->SetHeader (header);
					}

					Pim = pim;
					Type = layout->GetType();
					SectorSize = header->GetSectorSize();

					VolumeDataOffset = layout->GetDataOffset (VolumeHostSize);
					VolumeDataSize = layout->GetDataSize (VolumeHostSize);
					EncryptedDataSize = header->GetEncryptedAreaLength();

					Header = header;
					Layout = layout;
					EA = header->GetEncryptionAlgorithm();
					EncryptionMode &mode = *EA->GetMode();

					if (layout->HasDriveHeader())
					{
						if (header->GetEncryptedAreaLength() != header->GetVolumeDataSize())
						{
							EncryptionNotCompleted = true;
							// we avoid writing data to the partition since it is only partially encrypted
							Protection = VolumeProtection::ReadOnly;
						}

						uint64 partitionStartOffset = VolumeFile->GetPartitionDeviceStartOffset();

						if (partitionStartOffset < header->GetEncryptedAreaStart()
							|| partitionStartOffset >= header->GetEncryptedAreaStart() + header->GetEncryptedAreaLength())
							throw PasswordIncorrect (SRC_POS);

						EncryptedDataSize -= partitionStartOffset - header->GetEncryptedAreaStart();

						mode.SetSectorOffset (partitionStartOffset / ENCRYPTION_DATA_UNIT_SIZE);
					}

					// The data area comes from the decrypted header. If it is not
					// contained in the host, writes could land outside the area the
					// volume was created with. Keep it readable (e.g. a truncated
					// container) but never write to it. Drive-header layouts are
					// validated against the partition above.
					if (!layout->HasDriveHeader() && VolumeHostSize > 0
						&& (VolumeDataOffset > VolumeHostSize || VolumeDataSize > VolumeHostSize - VolumeDataOffset))
					{
						Protection = VolumeProtection::ReadOnly;
					}

					// Volume protection
					if (Protection == VolumeProtection::HiddenVolumeReadOnly)
					{
						if (Type == VolumeType::Hidden)
							throw PasswordIncorrect (SRC_POS);
						else
						{
							try
							{
								Volume protectedVolume;

								protectedVolume.Open (VolumeFile,
									protectionPassword, protectionPim, protectionKdf, protectionKeyfiles,
									emvSupportEnabled,
									VolumeProtection::ReadOnly,
									shared_ptr <VolumePassword> (), 0, shared_ptr <Pkcs5Kdf> (),shared_ptr <KeyfileList> (),
									VolumeType::Hidden,
									useBackupHeaders);

								if (protectedVolume.GetType() != VolumeType::Hidden)
									ParameterIncorrect (SRC_POS);

								ProtectedRangeStart = protectedVolume.VolumeDataOffset;
								ProtectedRangeEnd = protectedVolume.VolumeDataOffset + protectedVolume.VolumeDataSize;
							}
							catch (PasswordException&)
							{
								if (protectionKeyfiles && !protectionKeyfiles->empty())
									throw ProtectionPasswordKeyfilesIncorrect (SRC_POS);
								throw ProtectionPasswordIncorrect (SRC_POS);
							}
						}
					}
					return;
				}
			}

			if (partitionInSystemEncryptionScope)
				throw PasswordOrKeyboardLayoutIncorrect (SRC_POS);

			if (!partitionInSystemEncryptionScope && GetPath().IsDevice())
			{
				// Check if the device contains VeraCrypt Boot Loader
				try
				{
					File driveDevice;
					driveDevice.Open (DevicePath (wstring (GetPath())).ToHostDriveOfPartition());

					Buffer mbr (VolumeFile->GetDeviceSectorSize());
					driveDevice.ReadAt (mbr, 0);

					// Search for the string "VeraCrypt"
					const char* bootSignature = TC_APP_NAME;
					size_t nameLen = strlen (bootSignature);
					for (size_t i = 0; i < mbr.Size() - nameLen; ++i)
					{
						if (memcmp (mbr.Ptr() + i, bootSignature, nameLen) == 0)
							throw PasswordOrMountOptionsIncorrect (SRC_POS);
					}
				}
				catch (PasswordOrMountOptionsIncorrect&) { throw; }
				catch (...) { }
			}

			if (keyfiles && !keyfiles->empty())
				throw PasswordKeyfilesIncorrect (SRC_POS);
			throw PasswordIncorrect (SRC_POS);
		}
		catch (...)
		{
			Close();
			throw;
		}
	}

	size_t Volume::ReadBytes (const BufferPtr &buffer, uint64 byteOffset)
	{
		if (byteOffset >= VolumeDataSize || buffer.Size() == 0)
			return 0;

		const size_t length = static_cast <size_t> (std::min <uint64> (buffer.Size(), VolumeDataSize - byteOffset));
		const size_t sectorOffset = byteOffset % SectorSize;
		if (sectorOffset == 0 && length % SectorSize == 0)
		{
			ReadSectors (buffer.GetRange (0, length), byteOffset);
		}
		else
		{
			// Read complete sectors and copy only the bytes requested by the filesystem.
			size_t alignedLength = sectorOffset + length;
			const size_t remainder = alignedLength % SectorSize;
			if (remainder != 0)
				alignedLength += SectorSize - remainder;

			SecureBuffer aligned (alignedLength);
			ReadSectors (aligned, byteOffset - sectorOffset);
			buffer.GetRange (0, length).CopyFrom (aligned.GetRange (sectorOffset, length));
		}

		return length;
	}

	void Volume::ReadSectors (const BufferPtr &buffer, uint64 byteOffset)
	{
		if_debug (ValidateState ());

		uint64 length = buffer.Size();
		uint64 hostOffset = VolumeDataOffset + byteOffset;
		size_t bufferOffset = 0;

		if (length % SectorSize != 0 || byteOffset % SectorSize != 0)
			throw ParameterIncorrect (SRC_POS);

		if (VolumeFile->ReadAt (buffer, hostOffset) != length)
			throw MissingVolumeData (SRC_POS);

		// first sector can be unencrypted in some cases (e.g. windows repair)
		// detect this case by looking for NTFS header
		uint64 firstBytes = 0;
		if (SystemEncryption && (hostOffset == 0) && length >= sizeof (firstBytes))
			memcpy (&firstBytes, buffer.Get(), sizeof (firstBytes));	// the buffer need not be 8-byte aligned
		if (SystemEncryption && (hostOffset == 0) && (BE64 (firstBytes) == 0xEB52904E54465320ULL))
		{
			bufferOffset = (size_t) SectorSize;
			hostOffset += SectorSize;
			length -= SectorSize;
		}

		if (length)
		{
			if (EncryptionNotCompleted)
			{
				// if encryption is not complete, we decrypt only the encrypted sectors
				if (hostOffset < EncryptedDataSize)
				{
					uint64 encryptedLength = VC_MIN (length, (EncryptedDataSize - hostOffset));

					EA->DecryptSectors (buffer.GetRange (bufferOffset, encryptedLength), hostOffset / SectorSize, encryptedLength / SectorSize, SectorSize);			
				}
			}
			else
				EA->DecryptSectors (buffer.GetRange (bufferOffset, length), hostOffset / SectorSize, length / SectorSize, SectorSize);
		}

		TotalDataRead += length;
	}

	void Volume::ReEncryptHeader (bool backupHeader, const ConstBufferPtr &newSalt, const ConstBufferPtr &newHeaderKey, shared_ptr <Pkcs5Kdf> newPkcs5Kdf)
	{
		if_debug (ValidateState ());

		if (Protection == VolumeProtection::ReadOnly)
			throw VolumeReadOnly (SRC_POS);

		SecureBuffer newHeaderBuffer (Layout->GetHeaderSize());

		Header->EncryptNew (newHeaderBuffer, newSalt, newHeaderKey, newPkcs5Kdf);

		int headerOffset = backupHeader ? Layout->GetBackupHeaderOffset() : Layout->GetHeaderOffset();

		if (headerOffset >= 0)
			VolumeFile->SeekAt (headerOffset);
		else
			VolumeFile->SeekEnd (headerOffset);

		VolumeFile->Write (newHeaderBuffer);
	}

	void Volume::ValidateState () const
	{
		if (VolumeFile.get() == nullptr)
			throw NotInitialized (SRC_POS);
	}

	void Volume::WriteBytes (const ConstBufferPtr &buffer, uint64 byteOffset)
	{
		const size_t length = buffer.Size();
		if (byteOffset > VolumeDataSize || length > VolumeDataSize - byteOffset)
			throw ParameterIncorrect (SRC_POS);
		if (length == 0)
			return;
		if (Protection == VolumeProtection::ReadOnly)
			throw VolumeReadOnly (SRC_POS);
		if (HiddenVolumeProtectionTriggered)
			throw VolumeProtected (SRC_POS);

		const size_t sectorOffset = byteOffset % SectorSize;
		if (sectorOffset == 0 && length % SectorSize == 0)
		{
			WriteSectors (buffer, byteOffset);
			return;
		}

		size_t alignedLength = sectorOffset + length;
		const size_t remainder = alignedLength % SectorSize;
		if (remainder != 0)
			alignedLength += SectorSize - remainder;
		// Validate the whole affected sector span before reading or modifying it.
		const uint64 alignedOffset = byteOffset - sectorOffset;
		if (alignedLength > VolumeDataSize - alignedOffset)
			throw ParameterIncorrect (SRC_POS);
		if (Protection == VolumeProtection::HiddenVolumeReadOnly)
			CheckProtectedRange (VolumeDataOffset + alignedOffset, alignedLength);

		SecureBuffer aligned (alignedLength);
		ReadSectors (aligned, alignedOffset);
		aligned.GetRange (sectorOffset, length).CopyFrom (buffer);
		WriteSectors (aligned, alignedOffset);
	}

	void Volume::WriteSectors (const ConstBufferPtr &buffer, uint64 byteOffset)
	{
		if_debug (ValidateState ());

		uint64 length = buffer.Size();
		uint64 hostOffset = VolumeDataOffset + byteOffset;

		if (length % SectorSize != 0
			|| byteOffset % SectorSize != 0
			|| byteOffset > VolumeDataSize || length > VolumeDataSize - byteOffset)
			throw ParameterIncorrect (SRC_POS);

		if (Protection == VolumeProtection::ReadOnly)
			throw VolumeReadOnly (SRC_POS);

		if (HiddenVolumeProtectionTriggered)
			throw VolumeProtected (SRC_POS);

		if (Protection == VolumeProtection::HiddenVolumeReadOnly)
			CheckProtectedRange (hostOffset, length);

		SecureBuffer encBuf (buffer.Size());
		encBuf.CopyFrom (buffer);

		EA->EncryptSectors (encBuf, hostOffset / SectorSize, length / SectorSize, SectorSize);
		VolumeFile->WriteAt (encBuf, hostOffset);

		TotalDataWritten += length;

		uint64 writeEndOffset = byteOffset + buffer.Size();
		if (writeEndOffset > TopWriteOffset)
			TopWriteOffset = writeEndOffset;
	}
}
