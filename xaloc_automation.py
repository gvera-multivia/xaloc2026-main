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
        """Inicializa el navegador usando perfil persistente para acceso a certificados"""
        logging.info("🚀 Iniciando navegador con perfil persistente...")
        
        self.playwright = await async_playwright().start()
        
        # Preparar argumentos del navegador
        args = self.config.navegador.args.copy()
        
        # AUTO-SELECCIÓN DE CERTIFICADO
        policy = '{"pattern":"*","filter":{}}'
        args.append(f'--auto-select-certificate-for-urls=[{policy}]')
        
        # Deshabilitar popup de traducción (simplifica navegación por Tab)
        args.append('--lang=ca')  # Catalán, idioma nativo de la web
        args.append('--disable-features=TranslateUI')
        
        # Usar perfil persistente - permite acceso a certificados del sistema
        # y recuerda selecciones previas del usuario
        user_data_dir = str(self.config.navegador.perfil_path.absolute())
        
        logging.info(f"📂 Usando perfil persistente: {user_data_dir}")
        
        # launch_persistent_context combina browser + context en uno
        # Esto es CLAVE para acceder a los certificados del sistema
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel=self.config.navegador.canal,
            headless=self.config.navegador.headless,
            args=args,
            ignore_https_errors=True,
            accept_downloads=True
        )
        
        # El contexto persistente ya tiene una página, o creamos una nueva
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()
            
        self.page.set_default_timeout(self.config.timeouts.general)
        
        # Nota: No usamos storage_state con persistent_context porque
        # el perfil ya mantiene su propio estado de sesión
        
        logging.info("✅ Navegador iniciado con perfil persistente")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cierra el navegador (persistent_context)"""
        if self.context:
            await self.context.close()
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
            self.page = await ejecutar_login(self.page, self.config)
            
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
