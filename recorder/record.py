import argparse
import asyncio
import json
import time
import sys
import os
import signal
from datetime import datetime
from pathlib import Path

# Fix import path for running as script
sys.path.append(os.getcwd())

from playwright.async_api import async_playwright
from recorder.capture import CaptureManager
from recorder.compile import compile_recording

# We will need to read inject_recorder.js
RECORDER_JS_PATH = Path(__file__).parent / "inject_recorder.js"

class Recorder:
    def __init__(self, site: str, protocol: str = None):
        self.site = site
        self.protocol = protocol
        self.events = []
        # Use absolute path based on project root (parent of recorder/)
        self.project_root = Path(__file__).parent.parent.resolve()
        self.output_dir = self.project_root / "recordings" / site
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_file = self.output_dir / f"{self.timestamp}.jsonl"
        self.stop_event = asyncio.Event()
        self.capture_manager = CaptureManager(site)
        self.browser_context = None
        self.js_content = None


    async def start(self):
        async with async_playwright() as p:
            # Launch persistent context with absolute path
            user_data_dir = self.project_root / "user_data" / self.site
            user_data_dir.mkdir(parents=True, exist_ok=True)

            print(f"Launching browser with user data: {user_data_dir}")

            self.browser_context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="msedge",
                headless=False,
                args=["--start-maximized"],
                no_viewport=True,
                ignore_https_errors=True
            )

            # Expose function to JS (using binding to get source page)
            # Note: expose_binding passes 'source' as first argument
            await self.browser_context.expose_binding("record_action", self.handle_action_binding)

            # Load JS content
            with open(RECORDER_JS_PATH, "r", encoding="utf-8") as f:
                self.js_content = f.read()

            # Inject script on load for NEW pages
            await self.browser_context.add_init_script(self.js_content)

            # Inject script into EXISTING pages (restored from persistent context)
            for page in self.browser_context.pages:
                try:
                    await page.evaluate(self.js_content)
                    print(f"Injected recorder into existing page: {page.url}")
                except Exception as e:
                    print(f"Could not inject into page {page.url}: {e}")

            # Listen for new pages and inject script
            self.browser_context.on("page", self._on_new_page)

            # Open a blank page if none exists (persistent context might restore tabs)
            if not self.browser_context.pages:
                page = await self.browser_context.new_page()
                print("Opened new blank page.")

            print(f"Recording started for {self.site}. Press Ctrl+C in terminal to stop.")
            print(f"Saving to {self.output_file}")
            print(f"Total events captured: 0")

            try:
                # Wait until user signals stop.
                while not self.stop_event.is_set():
                     if not self.browser_context.pages:
                         print("All pages closed.")
                         break
                     await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                print("Recording cancelled.")
            finally:
                print(f"\nStopping recorder... (captured {len(self.events)} events)")
                if self.browser_context:
                    try:
                        await self.browser_context.close()
                    except:
                        pass
                print("Browser closed.")

    def _on_new_page(self, page):
        async def inject():
            try:
                await page.evaluate(self.js_content)
                print(f"Injected recorder into new page: {page.url}")
            except:
                pass
        asyncio.create_task(inject())

    async def handle_action_binding(self, source, data):
        print(f"[Event #{len(self.events)+1}] {data['action']} on {data.get('field', {}).get('label') or data.get('field', {}).get('name') or 'element'}")
        self.events.append(data)

        page = source.page
        if page:
            await self.capture_manager.capture_checkpoint(page, data['url'], data.get('h1'))

        with open(self.output_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

    def post_process(self):
        print(f"\n{'='*50}")
        print(f"Processing recording... ({len(self.events)} events)")
        print(f"{'='*50}")
        
        if not self.events and not self.output_file.exists():
            print("\n[!] No events were captured!")
            print("    Possible causes:")
            print("    - The recorder JS was not injected (try navigating to a new page)")
            print("    - You did not interact with any elements")
            print("    - The page blocked the recorder script")
            return
        
        compile_recording(self.site, self.output_file)
        print(f"\nDone! Check the following outputs:")
        print(f"  - Documentation: explore-html/{self.site}-recording.md")
        print(f"  - Code skeleton: sites/{self.site}/")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True)
    parser.add_argument("--protocol")
    args = parser.parse_args()

    recorder = Recorder(args.site, args.protocol)

    # Handle Ctrl+C gracefully
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        print("\n[Ctrl+C detected] Stopping...")
        recorder.stop_event.set()
    
    # Add signal handler for Windows compatibility
    try:
        loop.add_signal_handler(signal.SIGINT, signal_handler)
    except NotImplementedError:
        # Windows doesn't support add_signal_handler, use alternative
        pass

    try:
        await recorder.start()
    except KeyboardInterrupt:
        print("\n[Ctrl+C detected] Stopping...")
        recorder.stop_event.set()
        # Give async tasks time to clean up
        await asyncio.sleep(0.5)
    finally:
        # ALWAYS run post-processing
        recorder.post_process()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # This catches Ctrl+C at the asyncio.run level
        print("\nRecorder terminated.")
