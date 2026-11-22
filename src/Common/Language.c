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
static char *HeaderResource[2] = {NULL, NULL};
static DWORD HeaderResourceSize[2] = {0, 0};

static char *MapEnglishLanguageResource ()
{
	DWORD size;
	const BYTE *resource = MapResource (L"Xml", IDR_LANGUAGE, &size);

	free (LanguageFileBuffer);
	LanguageFileBuffer = NULL;
	if (resource)
	{
		LanguageFileBuffer = malloc (size + 1);
		if (LanguageFileBuffer)
		{
			memcpy (LanguageFileBuffer, resource, size);
			LanguageFileBuffer[size] = 0;
		}
	}

	return LanguageFileBuffer;
}

BOOL LoadLanguageFile (BOOL bForceSilent)
{
	DWORD size;
	char *res, *xml, *header, *headerPtr;
	char attr[32768], key[128];
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
	ClearDictionaryPool ();

	res = MapEnglishLanguageResource ();
	if (!res || !XmlFindElement (res, "localization"))
		return FALSE;

	// Create font dictionary
	xml = res;
	while (xml = XmlFindElement (xml, "font"))
	{
		XmlGetAttributeText (xml, "lang", attr, sizeof (attr));
		if (strcmp (attr, "en") == 0)
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
		xml = res;
		while (xml = XmlFindElement (xml, xmlElements[i]))
		{
			void *pkey;
			void *text;

			XmlGetAttributeText (xml, "lang", attr, sizeof (attr));
			if (strcmp (attr, "en") == 0)
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

	LocalizationSerialNo++;

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

const char *GetPreferredLangId ()
{
	return "en";
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
