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
#include "LanguageStrings.h"
#include "Xml.h"

namespace VeraCrypt
{
	LanguageStrings::LanguageStrings ()
	{
	}

	LanguageStrings::~LanguageStrings ()
	{
	}

	wxString LanguageStrings::operator[] (const string &key) const
	{
		if (Map.count (key) > 0)
			return wxString (Map.find (key)->second);
		// return "LambCrypt" as it is
		if (key == "LambCrypt")
			return L"LambCrypt";

		return wxString (L"?") + StringConverter::ToWide (key) + L"?";
	}

	wstring LanguageStrings::Get (const string &key) const
	{
		return wstring (LangString[key]);
	}

	static wstring DecodeCatalogueEscapes (const wstring &text)
	{
		wstring result;
		result.reserve (text.size());
		for (size_t i = 0; i < text.size(); ++i)
		{
			wchar_t character = text[i];
			if (character == L'\\' && i + 1 < text.size())
			{
				// Consume escapes once. A literal backslash before 'n' stays literal.
				switch (text[i + 1])
				{
				case L'\\': ++i; break;
				case L'n': character = L'\n'; ++i; break;
				case L't': character = L'\t'; ++i; break;
				}
			}
			result += character;
		}
		return result;
	}

	void LanguageStrings::Init ()
	{
		static const uint8 LanguageXml[] =
		{
#			include "Common/Language.xml.h"
			, 0
		};
		XmlParser catalogue (wxString::FromUTF8 (reinterpret_cast<const char*> (LanguageXml)));
		foreach (XmlNode node, catalogue.GetNodes (L"entry"))
		{
			if (node.Attributes[L"lang"] != L"en")
				continue;

			Map[StringConverter::ToSingle (wstring (node.Attributes[L"key"]))] = DecodeCatalogueEscapes (wstring (node.InnerText));
		}
	}

	LanguageStrings LangString;
}
