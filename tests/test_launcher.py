# 바탕화면 실행의 기존 서버 재사용·새 서버 시작·다른 서비스 거부와 실패 안내를 검증한다.
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import launch_app


class LauncherTests(unittest.TestCase):
    def test_existing_server_opens_browser_without_new_process(self):
        with patch.object(launch_app, 'ready', return_value=True), patch.object(launch_app.subprocess, 'Popen') as spawn, patch.object(launch_app.webbrowser, 'open', return_value=True) as browser:
            launch_app.launch()
        spawn.assert_not_called()
        browser.assert_called_once_with('http://127.0.0.1:8766/')

    def test_foreign_service_is_not_opened_or_replaced(self):
        with patch.object(launch_app, 'HTTPConnection') as connection:
            response = connection.return_value.getresponse.return_value
            for status, body in ((200, b'<title>Other app</title>'), (302, b'')):
                response.status = status
                response.read.return_value = body
                with self.assertRaises(RuntimeError):
                    launch_app.ready()
        connection.return_value.close.assert_called()

    def test_failed_start_has_log_location_and_no_browser(self):
        with patch.object(launch_app, 'ready', return_value=False), patch.object(launch_app.subprocess, 'Popen') as spawn, patch.object(launch_app.webbrowser, 'open') as browser:
            spawn.return_value.poll.return_value = 1
            with self.assertRaisesRegex(RuntimeError, 'launcher.log'):
                launch_app.launch()
        browser.assert_not_called()

    def test_real_cold_start_on_isolated_port_and_library(self):
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            port = available.getsockname()[1]
        real_spawn = subprocess.Popen
        children = []
        with tempfile.TemporaryDirectory() as folder:
            def spawn(arguments, **options):
                arguments = list(arguments)
                arguments[arguments.index('--root') + 1] = str(Path(folder) / 'library')
                child = real_spawn(arguments, **options)
                children.append(child)
                return child
            try:
                with patch.object(launch_app, 'PORT', port), patch.object(launch_app.subprocess, 'Popen', side_effect=spawn), patch.object(launch_app.webbrowser, 'open', return_value=True) as browser:
                    launch_app.launch()
                    self.assertTrue(launch_app.ready())
                    launch_app.launch()
                self.assertEqual(len(children), 1)
                self.assertEqual(browser.call_count, 2)
                self.assertTrue((Path(folder) / 'library/library.sqlite3').is_file())
            finally:
                for child in children:
                    child.terminate()
                    child.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
