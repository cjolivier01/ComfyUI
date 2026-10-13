#!/usr/bin/env python3
"""Serve the output directory over HTTP so other devices on the LAN can browse and watch it."""

import argparse
import os
import re
import socket
import sys
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BYTE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_byte_range(header, size):
    """Resolve a single `bytes=` range against a file size, or None if it cannot be satisfied."""
    match = BYTE_RANGE.match(header.strip())
    if match is None:
        return None
    first, last = match.groups()
    if first:
        start = int(first)
        end = int(last) if last else size - 1
    elif last:
        start = max(size - int(last), 0)
        end = size - 1
    else:
        return None
    end = min(end, size - 1)
    if start > end:
        return None
    return start, end


class RangeRequestHandler(SimpleHTTPRequestHandler):
    """Static file handler with byte ranges, which browsers need to seek in a video."""

    protocol_version = "HTTP/1.1"
    range_length = None

    def send_head(self):
        self.range_length = None
        header = self.headers.get("Range")
        path = self.translate_path(self.path)
        if header is None or os.path.isdir(path):
            return super().send_head()

        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None

        st = os.fstat(f.fileno())
        span = parse_byte_range(header, st.st_size)
        if span is None:
            f.close()
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", "bytes */%d" % st.st_size)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None

        start, end = span
        f.seek(start)
        self.range_length = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Length", str(self.range_length))
        self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, st.st_size))
        self.send_header("Last-Modified", self.date_time_string(st.st_mtime))
        self.end_headers()
        return f

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def copyfile(self, source, outputfile):
        if self.range_length is None:
            super().copyfile(source, outputfile)
            return
        remaining = self.range_length
        while remaining > 0:
            buf = source.read(min(256 * 1024, remaining))
            if not buf:
                break
            outputfile.write(buf)
            remaining -= len(buf)


class OutputServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # Players abort connections on every seek, that is not worth a traceback.
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def lan_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # UDP, so nothing is sent: this only resolves the default route
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"),
                        help="directory to serve (default: the output directory next to this script)")
    parser.add_argument("--port", type=int, default=8189)
    parser.add_argument("--listen", default="0.0.0.0")
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        parser.error("not a directory: %s" % args.directory)

    server = OutputServer((args.listen, args.port), partial(RangeRequestHandler, directory=args.directory))
    print("Serving %s at http://%s:%d/" % (args.directory, lan_address(), args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
