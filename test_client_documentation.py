import unittest
import uuid
import shutil
from pathlib import Path

from core.client_documentation import RequiredClientDocumentsError, select_required_client_documents


class TestClientDocumentation(unittest.TestCase):
    def _make_tmp_dir(self) -> Path:
        root = Path("tmp") / "test_client_docs" / uuid.uuid4().hex
        root.mkdir(parents=True, exist_ok=True)
        return root

    def test_selects_aut_comp_as_principal(self):
        root = self._make_tmp_dir()
        try:
            (root / "AUT_cmp.pdf").write_bytes(b"%PDF-1.4 fake")
            (root / "DNI.pdf").write_bytes(b"%PDF-1.4 fake")

            selected = select_required_client_documents(
                ruta_docu=root,
                is_company=False,
                strict=False,
                merge_if_multiple=False,
            )
            self.assertEqual(len(selected.files_to_upload), 1)
            self.assertTrue(selected.files_to_upload[0].name.lower().endswith("cmp.pdf"))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_missing_terms_raises_in_strict_mode(self):
        root = self._make_tmp_dir()
        try:
            (root / "AUT.pdf").write_bytes(b"%PDF-1.4 fake")
            # Falta DNI y NIE
            with self.assertRaises(RequiredClientDocumentsError):
                select_required_client_documents(
                    ruta_docu=root,
                    is_company=False,
                    strict=True,
                    merge_if_multiple=False,
                )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_collects_all_terms_when_present(self):
        root = self._make_tmp_dir()
        try:
            (root / "AUT.pdf").write_bytes(b"%PDF-1.4 fake")
            (root / "DNI_frontal.pdf").write_bytes(b"%PDF-1.4 fake")
            (root / "NIE.pdf").write_bytes(b"%PDF-1.4 fake")

            selected = select_required_client_documents(
                ruta_docu=root,
                is_company=False,
                strict=True,
                merge_if_multiple=False,
            )
            self.assertEqual(len(selected.files_to_upload), 3)
            self.assertEqual(set(selected.covered_terms), {"AUT", "DNI", "NIE"})
            self.assertEqual(selected.missing_terms, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
