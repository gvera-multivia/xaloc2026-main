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
            # AUT (comp/cmp) + (DNI o NIE)
            self.assertEqual(len(selected.files_to_upload), 2)
            names = {p.name.lower() for p in selected.files_to_upload}
            self.assertIn("aut_cmp.pdf", names)
            self.assertIn("dni.pdf", names)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_missing_terms_raises_in_strict_mode(self):
        root = self._make_tmp_dir()
        try:
            (root / "AUT.pdf").write_bytes(b"%PDF-1.4 fake")
            # Falta DNI o NIE
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
            # Regla: AUT + (DNI o NIE) → se suben 2 archivos.
            self.assertEqual(len(selected.files_to_upload), 2)
            self.assertIn("AUT", set(selected.covered_terms))
            self.assertTrue(set(selected.covered_terms) & {"DNI", "NIE"})
            self.assertEqual(selected.missing_terms, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_prefers_split_docs_over_combined(self):
        root = self._make_tmp_dir()
        try:
            # "AUTDNI" combinado + ficheros separados
            (root / "AUTDNI.pdf").write_bytes(b"%PDF-1.4 fake")
            (root / "AUTORIZACION.pdf").write_bytes(b"%PDF-1.4 fake")
            (root / "DNI 1-7-31.pdf").write_bytes(b"%PDF-1.4 fake")

            selected = select_required_client_documents(
                ruta_docu=root,
                is_company=False,
                strict=True,
                merge_if_multiple=False,
            )
            names = {p.name.lower() for p in selected.files_to_upload}
            self.assertIn("autorizacion.pdf", names)
            self.assertIn("dni 1-7-31.pdf", names)
            self.assertNotIn("autdni.pdf", names)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
