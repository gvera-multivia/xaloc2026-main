# RedSARA site (Playwright)

This site replicates the RedSARA flow in Python + Playwright, following the
same structure used by other `sites/*` modules in this repository.

## Implemented phases

1. Login and navigation to `nuevo-registro`.
2. Certificate handling in Cl@ve gateway when presented.
3. Form step 1 and step 2 completion (interested/representative, organism, texts).
4. Document upload.
5. Terms acceptance, sign-and-register click, and justificante download.

## Notes

- The site is registered in `core/site_registry.py`.
- No Docker activation was performed.
- Destination copy for justificante is optional and only used if `payload["ruta_cliente"]`
  exists and is accessible.

## Local test

```bash
python redsara_task.py --payload-json redsara_payload.sample.json --headless 0
```
