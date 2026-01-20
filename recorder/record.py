import argparse
import asyncio
import json
import time
import sys
import os
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
        self.output_dir = Path(f"recordings/{site}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_file = self.output_dir / f"{self.timestamp}.jsonl"
        self.stop_event = asyncio.Event()
        self.capture_manager = CaptureManager(site)
        self.browser_context = None

    async def start(self):
        async with async_playwright() as p:
            # Launch persistent context
            user_data_dir = Path(f"user_data/{self.site}")
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

            # Inject script on load
            with open(RECORDER_JS_PATH, "r", encoding="utf-8") as f:
                js_content = f.read()

            await self.browser_context.add_init_script(js_content)

            # Open a blank page if none exists (persistent context might restore tabs)
            if not self.browser_context.pages:
                await self.browser_context.new_page()

            print(f"Recording started for {self.site}. Press Ctrl+C in terminal to stop.")
            print(f"Saving to {self.output_file}")

            try:
                # Wait until user signals stop.
                while not self.stop_event.is_set():
                     if not self.browser_context.pages:
                         print("All pages closed.")
                         break
                     await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                pass
            finally:
                if self.browser_context:
                    try:
                        await self.browser_context.close()
                    except:
                        pass
                print("Browser closed.")
                self.post_process()

    async def handle_action_binding(self, source, data):
        print(f"Action: {data['action']} on {data['url']}")
        self.events.append(data)

        page = source.page
        if page:
            await self.capture_manager.capture_checkpoint(page, data['url'], data.get('h1'))

        with open(self.output_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

    def post_process(self):
        print("Processing recording...")
        compile_recording(self.site, self.output_file)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True)
    parser.add_argument("--protocol")
    args = parser.parse_args()

    recorder = Recorder(args.site, args.protocol)

    # Handle Ctrl+C
    try:
        await recorder.start()
    except KeyboardInterrupt:
        recorder.stop_event.set()

if __name__ == "__main__":
    asyncio.run(main())
