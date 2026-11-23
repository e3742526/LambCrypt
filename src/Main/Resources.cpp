/* Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md. */
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

#include "System.h"
#include "Platform/Platform.h"
#include "Resources.h"

#ifdef TC_WINDOWS
#include "Main/resource.h"
#endif

namespace VeraCrypt
{

#ifdef TC_WINDOWS
	static ConstBufferPtr GetWindowsResource (const wchar_t *resourceType, const wchar_t *resourceName)
	{
		HGLOBAL hResL;
		HRSRC hRes;

		hRes = FindResource (NULL, resourceName, resourceType);
		throw_sys_if (!hRes);
		hResL = LoadResource (NULL, hRes);
		throw_sys_if (!hResL);

		const uint8 *resPtr = (const uint8 *) LockResource (hResL);
		throw_sys_if (!resPtr);

		return ConstBufferPtr (resPtr, SizeofResource (NULL, hRes));
	}
#endif // TC_WINDOWS

	string Resources::GetLegalNotices ()
	{
#ifdef TC_WINDOWS
		ConstBufferPtr res = GetWindowsResource (L"TEXT", L"IDR_LICENSE");
		Buffer strBuf (res.Size() + 1);
		strBuf.Zero();
		strBuf.CopyFrom (res);
		return string (reinterpret_cast <char *> (strBuf.Ptr()));
#else
		static uint8 License[] =
		{
#			include "License.txt.h"
			, 0
		};

		return string ((const char*) License);
#endif
	}


#ifndef TC_NO_GUI

	wxBitmap Resources::GetDriveIconBitmap ()
	{
#ifdef TC_WINDOWS
		return wxBitmap (L"IDB_DRIVE_ICON", wxBITMAP_TYPE_BMP_RESOURCE).ConvertToImage().Resize (wxSize (16, 12), wxPoint (0, 0));
#else
		static const uint8 DriveIcon[] =
		{
#			include "Mount/Drive_icon_96dpi.bmp.h"
		};

		wxMemoryInputStream stream (DriveIcon, sizeof (DriveIcon));
		return wxBitmap (wxImage (stream).Resize (wxSize (16, 12), wxPoint (0, 0)));
#endif
	}

	wxBitmap Resources::GetDriveIconMaskBitmap ()
	{
#ifdef TC_WINDOWS
		wxImage image = wxBitmap (L"IDB_DRIVE_ICON_MASK", wxBITMAP_TYPE_BMP_RESOURCE).ConvertToImage().Resize (wxSize (16, 12), wxPoint (0, 0));
		return wxBitmap (image.ConvertToMono (0, 0, 0), 1);
#else
		static const uint8 DriveIconMask[] =
		{
#			include "Mount/Drive_icon_mask_96dpi.bmp.h"
		};

		wxMemoryInputStream stream (DriveIconMask, sizeof (DriveIconMask));
		wxImage image (stream);
		image.Resize (wxSize (16, 12), wxPoint (0, 0));

#	if defined  __WXGTK__ || defined TC_MACOSX
		return wxBitmap (image.ConvertToMono (0, 0, 0), 1);
#	else
		return wxBitmap (image);
#	endif
#endif
	}


	wxBitmap Resources::GetLogoBitmap ()
	{
#ifdef TC_WINDOWS
		return wxBitmap (L"IDB_LOGO", wxBITMAP_TYPE_BMP_RESOURCE);
#else
		static const uint8 Logo[] =
		{
#			include "Mount/Logo_96dpi.bmp.h"
		};

		wxMemoryInputStream stream (Logo, sizeof (Logo));
		return wxBitmap (wxImage (stream));
#endif
	}

	wxBitmap Resources::GetTextualLogoBitmap ()
	{
#ifdef TC_WINDOWS
		return wxBitmap (L"IDB_TEXTUAL_LOGO", wxBITMAP_TYPE_BMP_RESOURCE);
#else
		static const uint8 Logo[] =
		{
#			include "Common/Textual_logo_96dpi.bmp.h"
		};

		wxMemoryInputStream stream (Logo, sizeof (Logo));
		return wxBitmap (wxImage (stream));
#endif
	}

	wxIcon Resources::GetVeraCryptIcon ()
	{
#ifdef TC_WINDOWS
		return wxIcon (L"IDI_TRUECRYPT_ICON", wxBITMAP_TYPE_ICO_RESOURCE, 16, 16);
#else
#		include "Resources/Icons/LambCrypt-256x256.xpm"
		return wxIcon (LambCryptIcon256x256);
#endif
	}

	wxBitmap Resources::GetVolumeCreationWizardBitmap (int height)
	{
#ifdef TC_WINDOWS
		return wxBitmap (L"IDB_VOLUME_WIZARD_BITMAP", wxBITMAP_TYPE_BMP_RESOURCE);
#else
		static const uint8 VolumeWizardIcon[] =
		{
#			include "Format/VeraCrypt_Wizard.bmp.h"
		};

		wxMemoryInputStream stream (VolumeWizardIcon, sizeof (VolumeWizardIcon));

		wxImage image (stream);
		if (height != -1)
		{
			double scaleFactor = double (height) / double (image.GetHeight());
			image.Rescale (int (image.GetWidth() * scaleFactor), int (image.GetHeight() * scaleFactor), wxIMAGE_QUALITY_HIGH);
		}

		return wxBitmap (image);
#endif
	}

#endif // !TC_NO_GUI

}
