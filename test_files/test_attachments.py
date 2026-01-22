import asyncio
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
from core.attachments import AttachmentDownloader, AttachmentInfo

class TestAttachmentDownloader(unittest.IsolatedAsyncioTestCase):
    async def test_download_single_success(self):
        downloader = AttachmentDownloader(download_dir=Path("tmp/test_downloads"))
        attachment = AttachmentInfo(id="123", filename="test.pdf", url="http://example.com/test.pdf")

        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b"content"
            mock_get.return_value.__aenter__.return_value = mock_resp

            result = await downloader.download_single(attachment, "rec_1")

            self.assertTrue(result.success)
            self.assertEqual(result.filename, "test.pdf")
            self.assertTrue(result.local_path.exists())
            self.assertEqual(result.local_path.read_bytes(), b"content")

    async def test_sanitize_filename(self):
        downloader = AttachmentDownloader()
        unsafe = 'file/with\\bad:chars?.pdf'
        safe = downloader._sanitize_filename(unsafe)
        self.assertEqual(safe, 'file_with_bad_chars_.pdf')

if __name__ == '__main__':
    unittest.main()
