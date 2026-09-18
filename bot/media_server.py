import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import config


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


_server = None
_thread = None


def start():
    global _server, _thread
    if _server is not None:
        return _server.server_address[1]
    handler = partial(QuietHandler, directory=str(config.MEDIA_DIR))
    _server = ThreadingHTTPServer((config.MEDIA_HOST, config.MEDIA_PORT), handler)
    _thread = threading.Thread(target=_server.serve_forever, name="media-server", daemon=True)
    _thread.start()
    return config.MEDIA_PORT


def stop():
    global _server
    if _server is not None:
        _server.shutdown()
        _server.server_close()
        _server = None
