from pathlib import Path

from sites.diputacio_bcn.flows import documentos


def test_existing_file_maps_server_doc_to_linux_mount(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    mount_root = tmp_path / "mnt" / "clientes"
    expected = mount_root / "A-C" / "CLIENTE DEMO" / "AUT.pdf"
    expected.parent.mkdir(parents=True, exist_ok=True)
    expected.write_bytes(b"pdf")

    monkeypatch.setattr(documentos, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(documentos, "resolve_client_docs_base_path", lambda: str(mount_root))

    raw = r"\\SERVER-DOC\clientes\A-C\CLIENTE DEMO\AUT.pdf"
    assert documentos._existing_file(raw) == str(expected.resolve())


def test_existing_file_maps_windows_repo_path_to_runtime_repo(tmp_path, monkeypatch):
    repo_root = tmp_path / "xaloc2026-main"
    target = repo_root / "tmp" / "diputacio" / "tramite.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"pdf")

    monkeypatch.setattr(documentos, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(documentos, "resolve_client_docs_base_path", lambda: str(tmp_path / "mnt" / "clientes"))

    raw = r"C:\Users\tester\Desktop\Proyectos\xaloc2026-main\tmp\diputacio\tramite.pdf"
    assert documentos._existing_file(raw) == str(target.resolve())


def test_collect_upload_paths_deduplicates_same_required_document(tmp_path, monkeypatch):
    repo_root = tmp_path / "xaloc2026-main"
    doc = repo_root / "tmp" / "downloads" / "RECURSO exp - Z259470971.pdf"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_bytes(b"pdf")

    monkeypatch.setattr(documentos, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(documentos, "resolve_client_docs_base_path", lambda: str(tmp_path / "mnt" / "clientes"))

    class _Datos:
        doc_acreditativa = str(doc)
        doc_tramite = str(doc)
        archivos_adjuntos = []

    paths = documentos._collect_upload_paths(_Datos())

    assert paths == [str(doc.resolve())]
