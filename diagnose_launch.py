import asyncio
import json
from playwright.async_api import async_playwright
from pathlib import Path

# Args exactly as seen in the logs, but omitting those Playwright manages
COMPLEX_ARGS = [
    "--allow-pre-commit-input",
    "--auto-select-certificate-for-urls=[{\"pattern\":\"https://[*.]madrid.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"35059210B MARIA TERESA MORENTE (R: B62798210)\"}}},{\"pattern\":\"https://[*.]xalocgirona.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"35059210B MARIA TERESA MORENTE (R: B62798210)\"}}},{\"pattern\":\"https://[*.]base.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"35059210B MARIA TERESA MORENTE (R: B62798210)\"}}},{\"pattern\":\"https://[*.]baseonline.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"35059210B MARIA TERESA MORENTE (R: B62798210)\"}}},{\"pattern\":\"https://[*.]aoc.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"35059210B MARIA TERESA MORENTE (R: B62798210)\"}}},{\"pattern\":\"https://[*.]clave.gob.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"35059210B MARIA TERESA MORENTE (R: B62798210)\"}}},{\"pattern\":\"https://[*.]sedipualba.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"35059210B MARIA TERESA MORENTE (R: B62798210)\"}}},{\"pattern\":\"https://reg.redsara.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"35059210B MARIA TERESA MORENTE (R: B62798210)\"}}},{\"pattern\":\"https://aoberta.terrassa.cat/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"35059210B MARIA TERESA MORENTE (R: B62798210)\"}}},{\"pattern\":\"https://sede.valencia.es/*\",\"filter\":{\"SUBJECT\":{\"CN\":\"35059210B MARIA TERESA MORENTE (R: B62798210)\"}}}]",
    "--disable-back-forward-cache",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-blink-features=AutomationControlled",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-component-extensions-with-background-pages",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--disable-features=TranslateUI,ExternalProtocolDialog,AcceptCHFrame,AvoidUnnecessaryBeforeUnloadCheckSync,DestroyProfileOnBrowserClose,DialMediaRouteProvider,GlobalMediaControls,HttpsUpgrades,LensOverlay,MediaRouter,PaintHolding,ThirdPartyStoragePartitioning,Translate,AutoDeElevate,RenderDocument,OptimizationHints",
    "--disable-field-trial-config",
    "--disable-hang-monitor",
    "--disable-infobars",
    "--disable-ipc-flooding-protection",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-renderer-backgrounding",
    "--disable-search-engine-choice-screen",
    "--disable-sync",
    "--edge-skip-compat-layer-relaunch",
    "--enable-automation",
    "--enable-features=CDPScreenshotNewSurface",
    "--enable-logging=stderr",
    "--export-tagged-pdf",
    "--force-color-profile=srgb",
    "--force-device-scale-factor=1.0",
    "--lang=ca",
    "--log-level=0",
    "--log-net-log=tmp/chromium-netlog.json", 
    "--metrics-recording-only",
    "--net-log-capture-mode=IncludeSensitive",
    "--no-default-browser-check",
    "--no-service-autorun",
    "--password-store=basic",
    "--protocol-handler-registration-mode=auto",
    "--start-maximized",
    "--unsafely-disable-devtools-self-xss-warnings",
    "--use-mock-keychain",
    "--v=1",
    "--restore-last-session",
    "--restart"
]

async def main():
    async with async_playwright() as p:
        user_data_dir = Path("profiles/worker").absolute()
        print(f"Launching with profile: {user_data_dir}")
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=True,
                args=COMPLEX_ARGS,
                ignore_https_errors=True,
                accept_downloads=True
            )
            print("Successfully launched!")
            page = await context.new_page()
            await page.goto("https://www.google.com")
            print(f"Page title: {await page.title()}")
            await context.close()
        except Exception as e:
            print(f"Launch failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
