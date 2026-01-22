import asyncio
from pathlib import Path
from core.validation import ValidationEngine, DocumentDownloader, DiscrepancyReporter

async def main():
    print("=== TEST DE VALIDACIÓN ===")
    
    # Payload con errores
    payload_bad = {
        "idRecurso": "848198",
        "expediente": "848198",
        "nif": "12345678Z", # Error letra
        "name": "",         # Error obligatorio
        "address_street": "Gran Via 44",
        "address_number": "", # Error dirección sucia
        "address_zip": "2801", # Error CP (cortos)
        "user_email": "usuario-error", # Error email
        "address_province": "MADRID",
        "address_city": "GIRONA", # Warning ciudad en provincia incorrecta
    }
    
    validator = ValidationEngine(site_id="madrid")
    result = validator.validate(payload_bad)
    
    print(f"¿Es válido? {result.is_valid}")
    print("Errores encontrados:")
    for err in result.errors:
        print(f" - [{err.field}] ({err.severity}): {err.message}")
    
    print("\nWarnings encontrados:")
    for warn in result.warnings:
        print(f" - [{warn.field}] ({warn.severity}): {warn.message}")
        
    if not result.is_valid:
        print("\nGenerando reporte HTML...")
        reporter = DiscrepancyReporter()
        report_path = reporter.generate_html(payload_bad, result.errors, result.warnings, "TEST-FAIL")
        print(f"Reporte generado en: {report_path.absolute()}")
        # reporter.open_in_browser(report_path) # Comentado para no abrir navegador en test auto

    print("\n=== TEST DE DESCARGA (SIMULADO) ===")
    # Nota: No probamos descarga real para evitar depender de red o URL activa si no es necesaria ahora
    downloader = DocumentDownloader(
        url_template="http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf/{idRecurso}",
        download_dir=Path("tmp/test_downloads")
    )
    url = downloader.build_url("848198")
    print(f"URL construida: {url}")
    
    # Probamos descarga de un PDF real si es posible, o simplemente validamos la lógica
    # res = await downloader.download("848198")
    # print(f"Resultado descarga: {res.success}, Error: {res.error}")

if __name__ == "__main__":
    asyncio.run(main())
