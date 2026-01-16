# Madrid Ayuntamiento - Quick Reference

## 🚀 Quick Start

```bash
# Run Madrid automation (headless)
python main.py --site madrid

# Run with visible browser (for debugging)
python main.py --site madrid --headless false
```

## 📋 Implementation Status

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1: Navigation** | ✅ Complete | All 11 steps from landing to form |
| **Phase 2: Form Filling** | 🔜 Future | Awaiting form HTML capture |
| **Phase 3: Document Upload** | 🔜 Future | If required by form |
| **Phase 4: Submission** | 🔜 Future | Final confirmation |

## 🗺️ Navigation Steps

1. ✅ Click "Tramitar en línea" → Opens `#verTodas` section
2. ✅ Click "Registro Electrónico" → Navigate to `servpub.madrid.es`
3. ✅ Click first "Continuar" → Submit form
4. ✅ Click "Iniciar tramitación" → Go to login
5. ✅ Click "DNIe / Certificado" → Select certificate login
6. ✅ Handle Windows certificate popup → Auto-accept with thread
7. ✅ Click post-auth "Continuar" → Proceed after login
8. ✅ Select "Tramitar nueva solicitud" → Choose new procedure
9. ✅ Select "Persona o Entidad interesada" + Continuar → Choose role
10. ✅ Conditional: Handle "Nuevo trámite" if exists → Clear partial submission
11. ✅ Verify form arrival → Confirm we reached the form

## 📁 File Structure

```
sites/madrid/
├── __init__.py          # Package exports
├── config.py            # All selectors and configuration
├── data_models.py       # MadridFormData, MadridTarget
├── controller.py        # Site registration (site_id="madrid")
├── automation.py        # MadridAutomation orchestrator
└── flows/
    ├── __init__.py
    └── navegacion.py    # 11-step navigation implementation
```

## 🔑 Key Selectors

| Step | Selector | Notes |
|------|----------|-------|
| 1 | `#tramitarClick` | Anchor link to `#verTodas` |
| 2 | `a[href^='https://servpub.madrid.es/WFORS_WBWFORS/servlet']` | External navigation |
| 3 | `input#btn1[type='submit'][value='Continuar']` | Type='submit' |
| 4 | `#btnConAuth` | May trigger loading overlay |
| 5 | `a.login-sede-opt-link:has-text('DNIe / Certificado')` | Text-based selector |
| 7 | `#btnContinuar` | Post-authentication |
| 8 | `#checkboxNuevoTramite` | Triggers `cargarOpciones()` |
| 9a | `#checkboxInteresado` | Role selection |
| 9b | `input#btn1[type='button'][value='Continuar']` | Type='button' (not submit!) |
| 10 | `#btnNuevoTramite` | Conditional - may not exist |

## ⚙️ Configuration Highlights

```python
# From sites/madrid/config.py
url_base = "https://sede.madrid.es/portal/site/tramites/..."
default_timeout = 30000  # 30 seconds
navigation_timeout = 60000  # 60 seconds (for certificate)
stealth_disable_webdriver = True  # For certificate popup
```

## 🎯 Wait Strategies

- ✅ **Use**: `domcontentloaded` for navigation
- ✅ **Use**: Element visibility/attachment waits
- ✅ **Use**: Short timeouts (5s) for conditional checks
- ✅ **Use**: Extended timeouts (60s) for certificate auth
- ❌ **Avoid**: `networkidle` (unreliable with constant requests)

## 🔐 Certificate Handling

```python
from utils.windows_popup import auto_accept_certificate_popup

# Launch background thread
popup_thread = threading.Thread(
    target=auto_accept_certificate_popup,
    args=(2,),  # Wait 2 seconds before pressing Enter
    daemon=True
)
popup_thread.start()

# Click certificate login (triggers popup)
await page.click(config.certificado_login_selector)

# Wait for auth to complete
await page.wait_for_selector(config.continuar_post_auth_selector, ...)
```

## 🐛 Debugging

### View logs
All steps are logged with detailed information:
```
PASO 1: Navegando a página base...
  → URL cargada: https://...
  → Click en botón 'Tramitar en línea' (#tramitarClick)
  → Bloque de tramitación visible (#verTodas)
```

### Error screenshots
Automatically captured on failure:
- Location: `screenshots/madrid_error.png`
- Full page screenshot with error context

### Success screenshots
Captured on completion:
- Location: `screenshots/madrid_navegacion_completa.png`
- Shows final form state

## 🔄 Conditional Logic (Step 10)

```python
try:
    # Try to find "Nuevo trámite" button (short timeout)
    await page.wait_for_selector(
        config.boton_nuevo_tramite_condicional,
        state="visible",
        timeout=5000  # Only 5 seconds
    )
    # Found it - click to clear partial submission
    await page.click(config.boton_nuevo_tramite_condicional)
except PlaywrightTimeoutError:
    # Not found - already on new procedure path
    pass
```

## 📚 Related Documentation

- **Specification**: [madrid-guide.md](file:///c:/Users/Guillem%20Vera/Desktop/Proyectos/xaloc2026-main/explore-html/madrid-guide.md)
- **Implementation Plan**: [implementation_plan.md](file:///C:/Users/Guillem%20Vera/.gemini/antigravity/brain/123be3aa-494b-4739-9b24-830f739148c0/implementation_plan.md)
- **Full Walkthrough**: [walkthrough.md](file:///C:/Users/Guillem%20Vera/.gemini/antigravity/brain/123be3aa-494b-4739-9b24-830f739148c0/walkthrough.md)
- **Task Checklist**: [task.md](file:///C:/Users/Guillem%20Vera/.gemini/antigravity/brain/123be3aa-494b-4739-9b24-830f739148c0/task.md)

## 🎓 Next Steps

1. **Test Navigation**: Run with `--headless false` to observe behavior
2. **Capture Form HTML**: Save form page HTML to `explore-html/`
3. **Implement Form Filling**: Create `flows/formulario.py`
4. **Add Document Upload**: If required by form
5. **Implement Submission**: Final confirmation handling

## ✅ Verification Checklist

- [x] All Python files compile without syntax errors
- [x] Site registered in `core/site_registry.py`
- [x] All 11 steps implemented with logging
- [x] Certificate popup handling integrated
- [x] Conditional logic for partial submissions
- [x] Error handling with screenshots
- [x] Comprehensive documentation
- [ ] **Manual test with real Madrid site** (pending)
- [ ] Form HTML captured (pending)
- [ ] Form filling implemented (pending)

---

**Status**: ✅ Ready for testing  
**Last Updated**: 2026-01-16  
**Implementation**: Complete (Navigation Phase)
