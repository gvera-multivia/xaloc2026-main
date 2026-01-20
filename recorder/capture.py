import asyncio
from pathlib import Path
from datetime import datetime

class CaptureManager:
    def __init__(self, site: str):
        self.site = site
        self.screenshot_dir = Path("screenshots") / site
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.last_url = None
        self.last_h1 = None

    async def capture_checkpoint(self, page, url: str, h1: str):
        """
        Captures a screenshot if URL or H1 changed significantly.
        Returns the path to the screenshot if taken, else None.
        """
        if url != self.last_url or h1 != self.last_h1:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

            # Sanitize filename
            safe_url = url.split("?")[0].replace("://", "_").replace("/", "_").replace(".", "_")[-50:]
            filename = f"{timestamp}_{safe_url}.png"
            filepath = self.screenshot_dir / filename

            try:
                await page.screenshot(path=str(filepath))
                self.last_url = url
                self.last_h1 = h1
                return str(filepath)
            except Exception as e:
                print(f"Failed to capture screenshot: {e}")
                return None
        return None

    async def capture_explicit(self, page, name: str):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{name}.png"
        filepath = self.screenshot_dir / filename
        try:
            await page.screenshot(path=str(filepath))
            return str(filepath)
        except Exception as e:
            print(f"Failed to capture screenshot: {e}")
            return None
