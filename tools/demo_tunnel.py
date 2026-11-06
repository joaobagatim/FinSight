"""Loopback-only fallback for a broken Docker Desktop port publisher.

Forward PostgreSQL bytes to TCP/SCRAM inside one verified demo container ID.
No SQL is generated, no credentials are passed to docker, no auth is bypassed.
"""

import socket
import socketserver
import subprocess
import threading


def open_tunnel(container_id):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            process = subprocess.Popen(
                [
                    "docker",
                    "exec",
                    "-i",
                    container_id,
                    "bash",
                    "-c",
                    "exec 3<>/dev/tcp/127.0.0.1/5432; "
                    "cat <&3 & cat >&3; kill $! 2>/dev/null || true",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            with self.server.guard:
                self.server.processes.add(process)

            def receive():
                try:
                    while chunk := process.stdout.read(65536):
                        self.request.sendall(chunk)
                except OSError:
                    pass
                finally:
                    try:
                        self.request.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

            reader = threading.Thread(target=receive, daemon=True)
            reader.start()
            try:
                while chunk := self.request.recv(65536):
                    process.stdin.write(chunk)
            except OSError:
                pass
            finally:
                process.stdin.close()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait()
                reader.join(timeout=3)
                process.stdout.close()
                with self.server.guard:
                    self.server.processes.discard(process)

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

    server = Server(("127.0.0.1", 5546), Handler)
    server.guard = threading.Lock()
    server.processes = set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def close_tunnel(server):
    server.shutdown()
    server.server_close()
    with server.guard:
        for process in server.processes.copy():
            if process.poll() is None:
                process.terminate()  # Own docker-exec subprocesses only.
