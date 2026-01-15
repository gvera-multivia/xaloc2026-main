"""
Orquestador principal de la automatización Xaloc
"""
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import logging
from pathlib import Path
from config import Config, DatosMulta
from flows import ejecutar_login, rellenar_formulario, subir_documento, confirmar_tramite


class XalocAsync:
    """Orquestador de automatización para Xaloc Girona"""
    
    def __init__(self, config: Config):
        self.config = config
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        
        # Configurar logging
        self._setup_logging()
    
    def _setup_logging(self):
        """Configura el sistema de logging"""
        log_file = self.config.dir_logs / "xaloc_automation.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
    
    async def __aenter__(self):
        """Inicializa el navegador con estado de autenticación si existe"""
        logging.info("🚀 Iniciando navegador...")
        
        self.playwright = await async_playwright().start()
        
        # Opciones de lanzamiento
        launch_options = {
            "headless": self.config.navegador.headless,
            "channel": self.config.navegador.canal,
            "args": self.config.navegador.args
        }
        
        self.browser = await self.playwright.chromium.launch(**launch_options)
        
        # Configurar contexto (con o sin estado guardado)
        context_options = {
            "base_url": self.config.url_base,
            # Ignorar errores de certificado si es necesario
            "ignore_https_errors": True
        }
        
        if self.config.auth_state_path.exists():
            logging.info(f"📂 Cargando estado de sesión desde: {self.config.auth_state_path}")
            context_options["storage_state"] = self.config.auth_state_path
        else:
            logging.warning("⚠️ No se encontró archivo de sesión. Se iniciará sin credenciales.")
            
        self.context = await self.browser.new_context(**context_options)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.config.timeouts.general)
        
        logging.info("✅ Navegador iniciado")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cierra el navegador"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logging.info("🔚 Navegador cerrado")
    
    async def ejecutar_flujo_completo(self, datos: DatosMulta) -> str:
        """
        Ejecuta el flujo completo de automatización
        
        Args:
            datos: Datos de la multa a tramitar
            
        Returns:
            Ruta del screenshot final
        """
        try:
            # Fase 1: Login
            logging.info("\n" + "="*50)
            logging.info("FASE 1: AUTENTICACIÓN")
            logging.info("="*50)
            await ejecutar_login(self.page, self.config)
            
            # Fase 2: Formulario
            logging.info("\n" + "="*50)
            logging.info("FASE 2: RELLENADO DE FORMULARIO")
            logging.info("="*50)
            await rellenar_formulario(self.page, datos)
            
            # Fase 3: Documentos
            if datos.archivo_adjunto:
                logging.info("\n" + "="*50)
                logging.info("FASE 3: SUBIDA DE DOCUMENTOS")
                logging.info("="*50)
                await subir_documento(self.page, datos.archivo_adjunto)
            
            # Fase 4: Confirmación
            logging.info("\n" + "="*50)
            logging.info("FASE 4: CONFIRMACIÓN")
            logging.info("="*50)
            screenshot_path = await confirmar_tramite(self.page, self.config.dir_screenshots)
            
            logging.info(f"\n📸 Screenshot guardado en: {screenshot_path}")
            return screenshot_path
            
        except Exception as e:
            # Capturar screenshot de error
            error_screenshot = self.config.dir_screenshots / "error.png"
            await self.page.screenshot(path=error_screenshot)
            logging.error(f"❌ Error capturado: {e}")
            logging.error(f"📸 Screenshot de error: {error_screenshot}")
            raise
