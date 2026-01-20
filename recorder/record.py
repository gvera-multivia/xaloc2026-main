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
        
        # Create the output file immediately to ensure path is valid
        try:
            self.output_file.touch()
            print(f"Created recording file: {self.output_file}")
        except Exception as e:
            print(f"ERROR: Could not create recording file: {e}")
            raise


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

            # Setup injection for ALL pages (existing and new)
            for page in self.browser_context.pages:
                await self._setup_page_injection(page)

            # Listen for new pages
            self.browser_context.on("page", lambda page: asyncio.create_task(self._setup_page_injection(page)))

            # Open a blank page if none exists
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

    async def _setup_page_injection(self, page):
        """Setup injection for a page - injects now AND on every future navigation."""
        # Inject immediately if page has content
        await self._inject_into_page(page)
        
        # Re-inject after every navigation (this is the key fix!)
        async def on_load():
            await self._inject_into_page(page)
        
        page.on("load", lambda: asyncio.create_task(on_load()))
        print(f"  [Page setup] Listening for navigations on: {page.url}")

    async def _inject_into_page(self, page):
        """Inject the recorder script into a page."""
        try:
            # Reset the injection flag so script runs again
            await page.evaluate("window._recorder_injected = false")
            await page.evaluate(self.js_content)
            print(f"  [Injected] {page.url[:80]}...")
        except Exception as e:
            # Page might be navigating or closed
            pass


    async def handle_action_binding(self, source, data):
        # Data is now a JSON string to avoid Array.prototype.toJSON issues
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                print(f"  -> ERROR parsing JSON: {e}")
                return
        
        event_num = len(self.events) + 1
        field_info = data.get('field', {})
        print(f"[Event #{event_num}] {data.get('action', 'unknown')} on {field_info.get('id') or field_info.get('name') or 'element'}")
        
        # FIRST: Write to file immediately (synchronous, cannot be cancelled)
        try:
            with open(self.output_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(data) + "\n")
                f.flush()
            print(f"  -> Event #{event_num} saved to file")
        except Exception as e:
            print(f"  -> ERROR writing event #{event_num} to file: {e}")
        
        # THEN: Add to memory
        self.events.append(data)
        
        # FINALLY: Try to capture screenshot (this can fail/be cancelled, but file is already saved)
        try:
            page = source.page
            if page:
                await self.capture_manager.capture_checkpoint(page, data.get('url', ''), data.get('h1'))
        except Exception as e:
            print(f"  -> Screenshot capture failed: {e}")



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
