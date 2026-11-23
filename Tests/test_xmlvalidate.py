#!/usr/bin/env python3
# Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.
"""Exercise the XML validator and the English-only CI policy with Python 3."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / ".github/workflows/validate_translation_formats.py"
COMMON = Path("src/Common/Language.xml")


class XmlValidatorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="vc-xml-validation-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "LambCrypt test"
        self.common = self.root / COMMON
        self.common.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / COMMON, self.common)

    def write_language(self, relative_path, *, missing=(), lang="en", text=None):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        catalogue = ET.parse(ROOT / COMMON)
        localization = catalogue.getroot().find("localization")
        localization.find("language").set("langid", lang)
        for entry in localization.findall("entry"):
            entry.set("lang", lang)
            if entry.get("key") in missing:
                localization.remove(entry)
            elif entry.get("key") == "IDCANCEL" and text is not None:
                entry.text = text
        catalogue.write(path, encoding="utf-8", xml_declaration=True)
        return path

    def run_validator(self, *options):
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *options, str(self.root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )

    def assert_overall_failure(self, result):
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_complete_fixture_catalogues_and_english_fallbacks_pass(self):
        self.write_language("Translations/Language.ar.xml")
        self.write_language("Translations/Language.nl.xml", lang="nl")

        result = self.run_validator()

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Format validation passed: 3 catalogues", result.stdout)

    def test_reports_every_missing_key_and_continues_to_later_files(self):
        arabic = self.write_language("Translations/Language.ar.xml", missing=("IDCANCEL", "IDC_DONATE"))
        french = self.write_language("Translations/Language.fr.xml", missing=("IDC_DONATE",))
        dutch = self.write_language("Translations/Language.nl.xml", lang="nl")

        result = self.run_validator()

        self.assert_overall_failure(result)
        for path, key in ((arabic, "IDCANCEL"), (arabic, "IDC_DONATE"), (french, "IDC_DONATE")):
            self.assertIn(f"{path}: {key}: missing catalogue entry", result.stdout)
        self.assertNotIn(str(dutch), result.stdout)

    def test_malformed_xml_reports_parser_error_and_continues(self):
        arabic = self.write_language("Translations/Language.ar.xml")
        arabic.write_text(
            arabic.read_text(encoding="utf-8").replace("</VeraCrypt>", "</Broken>"),
            encoding="utf-8",
        )
        dutch = self.write_language("Translations/Language.nl.xml", missing=("IDC_DONATE",), lang="nl")

        result = self.run_validator()

        self.assert_overall_failure(result)
        self.assertIn(f"{arabic}: mismatched tag", result.stdout)
        self.assertIn(f"{dutch}: IDC_DONATE: missing catalogue entry", result.stdout)

    def test_invalid_escape_reports_error_and_continues(self):
        arabic = self.write_language("Translations/Language.ar.xml", text=r"Invalid\q")
        dutch = self.write_language("Translations/Language.nl.xml", missing=("IDC_DONATE",), lang="nl")

        result = self.run_validator()

        self.assert_overall_failure(result)
        self.assertIn(f"{arabic}: IDCANCEL: invalid backslash escape", result.stdout)
        self.assertIn(f"{dutch}: IDC_DONATE: missing catalogue entry", result.stdout)

    def test_ci_rejects_external_catalogue_even_with_complete_entries(self):
        original = self.run_validator("--english-only")
        self.assertEqual(original.returncode, 0, original.stdout)
        external = self.write_language("Translations/Language.fr.xml", lang="fr")

        result = self.run_validator("--english-only")
        self.assert_overall_failure(result)
        self.assertIn(f"{external}: external language catalogues are disabled", result.stdout)

    def test_ci_rejects_non_english_builtin_declaration_font_and_entry(self):
        original = self.common.read_text(encoding="utf-8")
        for modifier in ('<language langid="fr"', '<font lang="fr"', '<entry lang="fr"'):
            with self.subTest(modifier=modifier):
                self.common.write_text(original.replace(modifier.replace('"fr"', '"en"'), modifier, 1),
                                       encoding="utf-8")
                result = self.run_validator("--english-only")
                self.assert_overall_failure(result)
                self.assertIn("in the built-in catalogue", result.stdout)

    def test_ci_matches_windows_loader_escapes(self):
        self.write_language(COMMON, text=r"Line\nTab\tC:\\temp")
        valid = self.run_validator("--english-only")
        self.assertEqual(valid.returncode, 0, valid.stdout)

        for text in (r"Invalid\r", r'Invalid\"', "Trailing\\"):
            with self.subTest(text=text):
                self.write_language(COMMON, text=text)
                result = self.run_validator("--english-only")
                self.assert_overall_failure(result)
                self.assertIn("IDCANCEL: invalid backslash escape", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
