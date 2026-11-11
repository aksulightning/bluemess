"""Exercise the real binary on a PTY with delayed cursor replies and fake greetd.

No PAM, hardware or host display manager is used. This is not a VT boot test.
"""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import time


def trial(binary, delay):
    with tempfile.TemporaryDirectory() as tmp:
        sockpath = str(Path(tmp) / 'greetd.sock')
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(sockpath)
            server.listen(1)
            server.settimeout(5)
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
            process = subprocess.Popen(
                [binary, '--greeting', 'BME-PTY-READY', '--cmd', '/bin/true'],
                stdin=slave, stdout=slave, stderr=slave,
                env=dict(os.environ, TERM='linux', LANG='C.UTF-8', GREETD_SOCK=sockpath),
                start_new_session=True,
            )
            os.close(slave)
            output = b''
            query_buffer = b''
            try:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(5)
                    deadline = time.monotonic() + 3.5
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise AssertionError(f'early exit {process.returncode}: {output!r}')
                        if not select.select([master], [], [], 0.05)[0]:
                            continue
                        data = os.read(master, 65536)
                        output += data
                        query_buffer += data
                        while b'\x1b[6n' in query_buffer:
                            _, query_buffer = query_buffer.split(b'\x1b[6n', 1)
                            time.sleep(delay)
                            os.write(master, b'\x1b[1;1R')
                        query_buffer = query_buffer[-3:]
                    assert b'BME-PTY-READY' in output, output
                    # An alive process is insufficient: verify keyboard -> greetd IPC.
                    os.write(master, b'bme-pty-test\r')

                    def receive(size):
                        data = b''
                        while len(data) < size:
                            chunk = connection.recv(size - len(data))
                            if not chunk:
                                raise AssertionError('greetd connection closed')
                            data += chunk
                        return data

                    length = struct.unpack('=I', receive(4))[0]
                    assert length < 65536
                    request = json.loads(receive(length))
                    assert request == {'type': 'create_session', 'username': 'bme-pty-test'}, request
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
                os.close(master)


if __name__ == '__main__':
    binary = str(Path(sys.argv[1]).resolve())
    for delay in (0, 0.1, 0.3, 0.5, 1.0):
        trial(binary, delay)
        print(f'PASS: cursor reply delay {delay}s, UI render and keyboard IPC', flush=True)
