"""Console real do Windows: stdin encerrado não fecha o resultado do Noturno."""

import contextlib
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import run_noturno_console as console

HELPER = r"""
import ctypes,struct,sys,threading,time
from ctypes import wintypes
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import run_noturno_console as app
root=Path(sys.argv[3])
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
k.CreateFileW.restype=wintypes.HANDLE
handle=k.CreateFileW('CONIN$',0xC0000000,3,None,3,0,None)
if handle in (None,ctypes.c_void_p(-1).value): raise OSError('Console de teste indisponivel')
k.WriteConsoleInputW.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
k.CloseHandle.argtypes=[wintypes.HANDLE]
def key(code):
    record=ctypes.create_string_buffer(struct.pack('<H2xiHHHHI',1,1,1,code,0,code,0))
    count=wintypes.DWORD()
    if not k.WriteConsoleInputW(handle,record,1,ctypes.byref(count)): raise OSError('Entrada sintetica falhou')
key(13) # ENTER antigo precisa ser descartado antes do resumo final.
def drive():
    while True:
        try:
            path=root/'keypress'
            if path.is_file():
                code=int(path.read_text(encoding='ascii'))
                path.unlink()
                key(code)
                (root/('ack'+str(code))).touch()
        except (FileNotFoundError,PermissionError): pass
        time.sleep(.03)
threading.Thread(target=drive,daemon=True).start()
app.run=lambda: int(sys.argv[2])
try: raise SystemExit(app.main())
finally: k.CloseHandle(handle)
"""


@unittest.skipUnless(os.name == "nt", "Exige console Win32 real")
class NoturnoConsoleWindowsTests(unittest.TestCase):
    def test_real_mutex_blocks_concurrent_run_and_releases_after_failure(self):
        with patch.object(
            console, "MUTEX_NAME", "Local\\NexoFlowConsoleTest_" + uuid4().hex
        ):
            with console.operation_lock():
                with self.assertRaisesRegex(RuntimeError, "em andamento"):
                    with console.operation_lock():
                        self.fail("Uma segunda execução adquiriu o bloqueio")
            with console.operation_lock():
                pass

    def test_real_window_stays_open_with_closed_stdin_until_new_console_enter(self):
        for code in (0, 3, 7):
            with (
                self.subTest(code=code),
                tempfile.TemporaryDirectory(prefix="nexo console ") as folder,
            ):
                root = Path(folder)
                helper = root / "helper.py"
                helper.write_text(HELPER, encoding="utf-8")
                ready, lines = threading.Event(), []
                info = subprocess.STARTUPINFO()
                info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                info.wShowWindow = 0
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-u",
                        str(helper),
                        str(Path(console.__file__).parent),
                        str(code),
                        str(root),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    startupinfo=info,
                )

                def read_output(process=process, lines=lines, ready=ready):
                    for line in process.stdout:
                        lines.append(line)
                        if "Pressione ENTER" in line:
                            ready.set()

                reader = threading.Thread(target=read_output, daemon=True)
                reader.start()
                try:
                    self.assertTrue(ready.wait(15), "".join(lines))
                    pending = root / "pending"
                    pending.write_text("32", encoding="ascii")
                    pending.replace(root / "keypress")
                    deadline = time.monotonic() + 5
                    while not (root / "ack32").exists() and time.monotonic() < deadline:
                        time.sleep(0.03)
                    self.assertTrue(
                        (root / "ack32").exists(), "Entrada sintética não foi consumida"
                    )
                    time.sleep(0.15)
                    self.assertIsNone(
                        process.poll(),
                        "Fechou com stdin encerrado, ENTER antigo ou outra tecla",
                    )
                    pending.write_text("13", encoding="ascii")
                    pending.replace(root / "keypress")
                    self.assertEqual(process.wait(timeout=10), code)
                    reader.join(timeout=2)
                    self.assertIn(f"Código de saída: {code}", "".join(lines))
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
                    with contextlib.suppress(OSError):
                        process.stdout.close()
