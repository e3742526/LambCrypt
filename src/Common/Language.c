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

#include "Language.h"
#include "Dlgcode.h"
#include "Dictionary.h"
#include "Tcdefs.h"
#include "Xml.h"

#include "../Common/Resource.h"

#ifdef TCMOUNT
#include "../Mount/Resource.h"
#endif

#ifdef VOLFORMAT
#include "../Format/Resource.h"
#endif

#ifdef SETUP
#include "../Setup/Resource.h"
#endif

#include <Strsafe.h>

BOOL LocalizationActive;
int LocalizationSerialNo;

wchar_t UnknownString[1024]  = {0};
static char *LanguageFileBuffer = NULL;
static char PreferredLangId[6] = {0};
static char *LanguageResource = NULL;
static DWORD LanguageResourceSize = 0;
static char *HeaderResource[2] = {NULL, NULL};
static DWORD HeaderResourceSize[2] = {0, 0};
static char ActiveLangPackVersion[6] = {0};
static int LanguageResourceId = 0;

static char *MapFirstLanguageFile ()
{
	if (LanguageFileBuffer != NULL)
	{
		free (LanguageFileBuffer);
		LanguageFileBuffer = NULL;
	}

	LanguageResourceId = 0;

	if (LanguageResource == NULL)
	{
		DWORD size;
		LanguageResource = MapResource (L"Xml", IDR_LANGUAGE, &size);
		if (LanguageResource)
			LanguageResourceSize = size;
	}

	if (LanguageResource)
	{
		LanguageFileBuffer = malloc(LanguageResourceSize + 1);
		if (LanguageFileBuffer)
		{
			memcpy (LanguageFileBuffer, LanguageResource, LanguageResourceSize);
			LanguageFileBuffer[LanguageResourceSize] = 0;
		}
	}

	return LanguageFileBuffer;
}

static char *MapNextLanguageFile (int resourceid)
{
	/* free memory here to avoid leaks */
	if (LanguageFileBuffer != NULL)
	{
		free (LanguageFileBuffer);
		LanguageFileBuffer = NULL;
	}

	if (resourceid != 0 && LanguageResourceId != resourceid)
	{
		DWORD size;

		LanguageResourceId = resourceid;

		LanguageResource = MapResource (L"Languages", LanguageResourceId, &size);
		if (LanguageResource)
			LanguageResourceSize = size;

		if (LanguageResource)
		{
			LanguageFileBuffer = malloc(LanguageResourceSize + 1);
			if (LanguageFileBuffer)
			{
				memcpy (LanguageFileBuffer, LanguageResource, LanguageResourceSize);
				LanguageFileBuffer[LanguageResourceSize] = 0;
			}
		}
	}

	return LanguageFileBuffer;
}


static BOOL LoadLanguageData (int resourceid, BOOL bForceSetPreferredLanguage, BOOL bForceSilent)
{
	DWORD size;
	BYTE *res;
	char *xml, *header, *headerPtr;
	char langId[6] = "en", attr[32768], key[128];
	BOOL defaultLangParsed = FALSE, langFound = FALSE;
	BOOL incompatibleLangFound = FALSE;
	char requiredVersion[128], incompatibleVersion[128] = {0};
	WCHAR wattr[32768];
	int i, intKey, len;

	char *xmlElements[] = {"entry", 0};

#ifdef TCMOUNT
	int headers[] = { IDR_COMMON_RSRC_HEADER, IDR_MOUNT_RSRC_HEADER, 0 };
#endif

#ifdef VOLFORMAT
	int headers[] = { IDR_COMMON_RSRC_HEADER, IDR_FORMAT_RSRC_HEADER, 0 };
#endif

#ifdef SETUP
	int headers[] = { IDR_COMMON_RSRC_HEADER, IDR_SETUP_RSRC_HEADER, 0 };
#endif

#ifdef VCSDK_DLL
	int headers[] = { 0 };
#endif

	LocalizationActive = FALSE;
	ActiveLangPackVersion[0] = 0;
	ClearDictionaryPool ();
	LanguageResource = NULL;

	// Parse all available language files until preferred language is found
	for (res = MapFirstLanguageFile (); res != NULL; res = MapNextLanguageFile (resourceid))
	{
		xml = (char *) res;
		xml = XmlFindElement (xml, "localization");
		if (!xml)
			continue;

		XmlGetAttributeText (xml, "prog-version", requiredVersion, sizeof (requiredVersion));

		// Search language id in language file
		if (defaultLangParsed)
		{
			while (xml = XmlFindElement (xml, "language"))
			{
				XmlGetAttributeText (xml, "langid", attr, sizeof (attr));
				if (resourceid != 0 || strcmp (attr, langId) == 0)
				{
					// Unrelated old translations must not produce a dialog. Keep
					// looking in case another file contains a compatible copy.
					if (strcmp (requiredVersion, VERSION_STRING) && strcmp (requiredVersion, "DEBUG"))
					{
						incompatibleLangFound = TRUE;
						StringCbCopyA (incompatibleVersion, sizeof (incompatibleVersion), requiredVersion);
						break;
					}
					if (resourceid != 0)
						StringCbCopyA (langId, sizeof (langId), attr);
					XmlGetAttributeText (xml++, "version", ActiveLangPackVersion, sizeof (ActiveLangPackVersion));
					langFound = TRUE;
					break;
				}
				xml++;
			}

			if (!langFound) continue;
		}

		// Create font dictionary
		xml = (char *) res;
		while (xml = XmlFindElement (xml, "font"))
		{
			XmlGetAttributeText (xml, "lang", attr, sizeof (attr));
			if (!defaultLangParsed
				|| strcmp (attr, langId) == 0)
			{
				Font font;
				memset (&font, 0, sizeof (font));

				XmlGetAttributeText (xml, "face", attr, sizeof (attr));

				len = MultiByteToWideChar (CP_UTF8, 0, attr, -1, wattr, sizeof (wattr) / sizeof(wattr[0]));
				font.FaceName = AddPoolData ((void *) wattr, len * 2);

				XmlGetAttributeText (xml, "size", attr, sizeof (attr));
				sscanf (attr, "%d", &font.Size);

				StringCbCopyA (attr, sizeof(attr), "font_");
				XmlGetAttributeText (xml, "class", attr + 5, sizeof (attr) - 5);
				AddDictionaryEntry (
					AddPoolData ((void *) attr, strlen (attr) + 1), 0,
					AddPoolData ((void *) &font, sizeof(font)));
			}

			xml++;
		}

		// Create string and control dictionaries
		for (i = 0; xmlElements[i] != 0; i++)
		{
			xml = (char *) res;
			while (xml = XmlFindElement (xml, xmlElements[i]))
			{
				void *pkey;
				void *text;

				XmlGetAttributeText (xml, "lang", attr, sizeof (attr));
				if (!defaultLangParsed
					|| strcmp (attr, langId) == 0)
				{
					if (XmlGetAttributeText (xml, "key", attr, sizeof (attr)))
					{
						pkey = AddPoolData (attr, strlen (attr) + 1);
						if (pkey == NULL) return FALSE;

						XmlGetNodeText (xml, attr, sizeof (attr));

						// Parse \ escape sequences
						{
							char *in = attr, *out = attr;
							while (*in)
							{
								if (*in == '\\')
								{
									in++;
									switch (*in++)
									{
									case '\\': *out++ = '\\'; break;
									case 't': *out++ = '\t'; break;
									case 'n': *out++ = 13; *out++ = 10; break;
									default:
										if (!bForceSilent)
											MessageBoxA (0, pkey, "VeraCrypt: Unknown '\\' escape sequence in string", MB_ICONERROR);
										return FALSE;
									}
								}
								else
									*out++ = *in++;
							}
							*out = 0;
						}

						// UTF8 => wide char
						len = MultiByteToWideChar (CP_UTF8, 0, attr, -1, wattr, sizeof (wattr) / sizeof(wattr[0]));
						if (len == 0)
						{
							if (!bForceSilent)
								MessageBoxA (0, pkey, "VeraCrypt: Error while decoding UTF-8 string", MB_ICONERROR);
							return FALSE;
						}

						// Add to dictionary
						text = AddPoolData ((void *) wattr, len * 2);
						if (text == NULL) return FALSE;

						AddDictionaryEntry ((char *)pkey, 0, text);
					}
				}

				xml++;
			}
		}

		if (langFound)
			break;

		if (!defaultLangParsed)
		{
			defaultLangParsed = TRUE;
			if ((resourceid == 0) && (langId[0] == 0 || strcmp (langId, "en") == 0))
				break;
		}
	}

	LocalizationActive = langFound && strcmp (langId, "en") != 0;
	LocalizationSerialNo++;
	if (!langFound && incompatibleLangFound && !bForceSilent)
	{
		wchar_t message[2048];
		StringCbPrintfW (message, sizeof (message), L"The selected language pack is for VeraCrypt %hs and is incompatible with VeraCrypt %hs. VeraCrypt will use English.\n\nInstall a compatible language pack in the Languages folder next to VeraCrypt.exe, or select English in Settings > Language.\n\nIf this followed a failed upgrade, run the new VeraCrypt installer again to complete the installation.",
			incompatibleVersion[0] ? incompatibleVersion : "(unknown version)", VERSION_STRING);
		MessageBoxW (NULL, message, L"VeraCrypt", MB_ICONWARNING);
	}

	if (bForceSetPreferredLanguage)
		StringCbCopyA (PreferredLangId, sizeof (PreferredLangId), langId);

	// Create control ID dictionary

	// Default controls
	AddDictionaryEntry (NULL, 1, GetString ("IDOK"));
	AddDictionaryEntry (NULL, 2, GetString ("IDCANCEL"));
	AddDictionaryEntry (NULL, 8, GetString ("IDCLOSE"));
	AddDictionaryEntry (NULL, 9, GetString ("IDHELP"));

	for (i = 0; headers[i] != 0; i++)
	{
		if (HeaderResource[i] == NULL)
		{
			HeaderResource[i] = MapResource (L"Header", headers[i], &size);
			if (HeaderResource[i])
				HeaderResourceSize[i] = size;
		}

		headerPtr = NULL;
		if (HeaderResource[i])
		{
			headerPtr = (char*) malloc (HeaderResourceSize[i] + 1);
			if (headerPtr)
			{
				memcpy (headerPtr, HeaderResource[i], HeaderResourceSize[i]);
				headerPtr [HeaderResourceSize[i]] = 0;
			}
		}

		header = headerPtr;
		if (header == NULL) return FALSE;
		header--;

		do
		{
			header++;
			if (sscanf (header, "#define %127s %d", key, &intKey) == 2)
			{
				WCHAR *str = GetString (key);

				if (str != UnknownString)
					AddDictionaryEntry (NULL, intKey, str);
			}

		} while ((header = strchr (header, '\n')) != NULL);

		free (headerPtr);
	}

	return TRUE;
}

BOOL LoadLanguageFile ()
{
	return LoadLanguageData (0, FALSE, FALSE);
}

BOOL LoadLanguageFromResource (int resourceid, BOOL bSetPreferredLanguage, BOOL bForceSilent)
{
	return LoadLanguageData (resourceid, bSetPreferredLanguage, bForceSilent);
}

// lParam = 1: auto mode
BOOL CALLBACK LanguageDlgProc (HWND hwndDlg, UINT msg, WPARAM wParam, LPARAM lParam)
{
	WORD lw = LOWORD (wParam);
	WORD hw = HIWORD (wParam);

	switch (msg)
	{
	case WM_INITDIALOG:
		{
			char *xml;
			char attr[2048], lastLangId[10];
			WCHAR wattr[2048];
			int len;
			int langCount = 0;
			BOOL defaultLangFound = FALSE;

			LocalizeDialog (hwndDlg, "IDD_LANGUAGE");
			ToHyperlink (hwndDlg, IDC_GET_LANG_PACKS);

			for (xml = MapFirstLanguageFile (); xml != NULL; xml = MapNextLanguageFile (0))
			{
				while (xml = XmlFindElement (xml, "language"))
				{
					XmlGetAttributeText (xml, "name", attr, sizeof (attr));
					len = MultiByteToWideChar (CP_UTF8, 0, attr, -1, wattr, sizeof (wattr) / sizeof(wattr[0]));

					if (len != 0
						&& (!defaultLangFound || wcscmp (wattr, L"English") != 0))
					{
						int i = (int) SendDlgItemMessageW (hwndDlg, IDC_LANGLIST, LB_ADDSTRING, 0, (LPARAM)wattr);
						if (i >= 0)
						{
							int id;

							// Encode language id in LPARAM
							XmlGetAttributeText (xml, "langid", attr, sizeof (attr));
							switch (strlen (attr))
							{
							case 2: id = attr[0] | attr[1] << 8; break;
							case 5: id = attr[0] | attr[1] << 8 | attr[3] << 16 | attr[4] << 24; break;
							default: continue;
							}

							if (!defaultLangFound)
								defaultLangFound = TRUE;

							SendDlgItemMessage (hwndDlg, IDC_LANGLIST, LB_SETITEMDATA, i, (LPARAM) id);

							if (strcmp (attr, PreferredLangId) == 0)
							{
								char credits [10000];
								WCHAR wcredits [10000];
								WCHAR wversion [20];
								wchar_t szVers [200];
								int nLen;

								SendDlgItemMessage (hwndDlg, IDC_LANGLIST, LB_SETCURSEL, i, 0);

								// Language pack version
								if (!ActiveLangPackVersion[0] || memcmp (ActiveLangPackVersion, "0.0.0", 5) == 0)
								{
									StringCbPrintfW (szVers, sizeof(szVers), GetString("LANG_PACK_VERSION"), L"--");
								}
								else
								{
									nLen = MultiByteToWideChar (CP_UTF8, 0, ActiveLangPackVersion, -1, wversion, sizeof (wversion) / sizeof(wversion[0]));
									if (nLen != 0)
										StringCbPrintfW (szVers, sizeof(szVers),GetString("LANG_PACK_VERSION"), wversion);
								}
								SetWindowTextW (GetDlgItem (hwndDlg, IDC_LANGPACK_VERSION), szVers);

								// Translator credits
								XmlGetAttributeText (xml, "translators", credits, sizeof (credits));
								nLen = MultiByteToWideChar (CP_UTF8, 0, credits, -1, wcredits, sizeof (wcredits) / sizeof(wcredits[0]));
								if (nLen != 0)
								{
									SetWindowTextW (GetDlgItem (hwndDlg, IDC_LANGPACK_CREDITS), wcredits);
								}
							}

							StringCbCopyA (lastLangId, sizeof(lastLangId),attr);
							langCount++;
						}
					}

					xml++;
				}
			}

			if (lParam == 1)
			{
				// Auto mode
				if (langCount < 2)
					EndDialog (hwndDlg, IDCANCEL);

				if (langCount == 2)
					StringCbCopyA (PreferredLangId, sizeof(PreferredLangId), lastLangId);

				EndDialog (hwndDlg, IDOK);
			}

			return 1;
		}

	case WM_DESTROY:
		DetachProtectionFromCurrentThread();
		break;

	case WM_COMMAND:

		if (lw == IDOK || hw == LBN_DBLCLK)
		{
			int i = (int) SendDlgItemMessage (hwndDlg, IDC_LANGLIST, LB_GETCURSEL, 0, 0);

			if (i >= 0)
			{
				int id = (int) SendDlgItemMessage (hwndDlg, IDC_LANGLIST, LB_GETITEMDATA, i, 0);

				if (id != LB_ERR)
				{
					char l[6];

					// Decode language id from LPARAM
					l[0] = (char) id;
					l[1] = (char) (id >> 8);
					l[2] = 0;

					if ((id & 0xffff0000) != 0)
					{
						l[2] = '-';
						l[3] = (char) (id >> 16);
						l[4] = id >> 24;
						l[5] = 0;
					}

					if (SendDlgItemMessage (hwndDlg, IDC_LANGLIST, LB_GETCOUNT, 0, 0) > 1)
						StringCbCopyA (PreferredLangId, sizeof(PreferredLangId), l);
				}
			}

			EndDialog (hwndDlg, IDOK);
			return 1;
		}

		if (lw == IDCANCEL)
		{
			EndDialog (hwndDlg, lw);
			return 1;
		}

		if (lw == IDC_GET_LANG_PACKS)
		{
			char tmpstr [256];

			if (strlen (ActiveLangPackVersion) > 0 && strlen (GetPreferredLangId()) > 0)
				StringCbPrintfA (tmpstr, sizeof(tmpstr), "&langpackversion=%s&lang=%s", ActiveLangPackVersion, GetPreferredLangId());
			else
				tmpstr[0] = 0;

			Applink ("localizations");

			return 1;
		}
		return 0;
	}

	return 0;
}


char *GetPreferredLangId ()
{
	return PreferredLangId;
}


void SetPreferredLangId (char *langId)
{
	if (strlen(langId) < sizeof(PreferredLangId))
		StringCbCopyA (PreferredLangId, sizeof(PreferredLangId), langId);
}


char *GetActiveLangPackVersion ()
{
	return ActiveLangPackVersion;
}


wchar_t *GetString (const char *stringId)
{
	WCHAR *str = (WCHAR *) GetDictionaryValue (stringId);
	if (str != NULL) return str;

	StringCbPrintfW (UnknownString, sizeof(UnknownString), UNKNOWN_STRING_ID L"%hs" UNKNOWN_STRING_ID, stringId);
	return UnknownString;
}


Font *GetFont (char *fontType)
{
	return (Font *) GetDictionaryValue (fontType);

}
