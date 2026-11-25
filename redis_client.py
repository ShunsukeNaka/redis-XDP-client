#!/usr/bin/env python3
"""Minimal Redis client speaking RESP directly over a TCP socket (stdlib only).

Usage:
    python3 redis_client.py                      # interactive REPL
    python3 redis_client.py SET foo bar          # one-shot command
    python3 redis_client.py --bench 10000 GET foo        # latency benchmark
    python3 redis_client.py --bench 10000 -P 16 GET foo  # pipelined benchmark
    python3 redis_client.py --hexdump PING       # show the raw bytes sent/received
"""

from __future__ import annotations

import argparse
import shlex
import socket
import sys
import time


class RedisError(Exception):
    """Error reply from the server (a '-' line)."""


class ProtocolError(Exception):
    """Malformed or unexpected data on the wire."""


def encode_command(*args) -> bytes:
    """Encode a command as a RESP array of bulk strings."""
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        if isinstance(a, bytes):
            b = a
        elif isinstance(a, str):
            b = a.encode()
        else:
            b = str(a).encode()
        out.append(b"$%d\r\n%s\r\n" % (len(b), b))
    return b"".join(out)


class RedisClient:
    def __init__(self, host="127.0.0.1", port=6379, timeout=5.0, hexdump=False):
        self.host = host
        self.port = port
        self.hexdump = hexdump
        self.sock = socket.create_connection((host, port), timeout=timeout)
        # Send each command immediately rather than letting Nagle coalesce them.
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._rfile = self.sock.makefile("rb")

    # ---- low level -------------------------------------------------------

    def send_raw(self, data: bytes) -> None:
        if self.hexdump:
            _dump(">>", data)
        self.sock.sendall(data)

    def _readline(self) -> bytes:
        line = self._rfile.readline()
        if not line:
            raise ConnectionError("connection closed by server")
        if not line.endswith(b"\r\n"):
            raise ProtocolError(f"line not terminated by CRLF: {line!r}")
        if self.hexdump:
            _dump("<<", line)
        return line[:-2]

    def _readexact(self, n: int) -> bytes:
        data = self._rfile.read(n + 2)
        if len(data) != n + 2:
            raise ConnectionError("connection closed by server")
        if self.hexdump:
            _dump("<<", data)
        return data[:-2]

    def read_reply(self):
        """Read one reply. Error replies are returned as RedisError instances."""
        line = self._readline()
        if not line:
            raise ProtocolError("empty line")
        t, rest = line[:1], line[1:]
        if t == b"+":                      # simple string
            return rest.decode(errors="replace")
        if t == b"-":                      # error
            return RedisError(rest.decode(errors="replace"))
        if t == b":":                      # integer
            return int(rest)
        if t == b"$":                      # bulk string
            n = int(rest)
            return None if n < 0 else self._readexact(n)
        if t == b"*":                      # array
            n = int(rest)
            return None if n < 0 else [self.read_reply() for _ in range(n)]
        # RESP3 types (only seen after HELLO 3)
        if t == b"_":
            return None
        if t == b"#":
            return rest == b"t"
        if t == b",":
            return float(rest)
        if t == b"(":
            return int(rest)
        if t in (b"=", b"!"):              # verbatim string / blob error
            data = self._readexact(int(rest))
            return RedisError(data.decode(errors="replace")) if t == b"!" else data
        if t in (b"~", b">"):              # set / push
            return [self.read_reply() for _ in range(int(rest))]
        if t == b"%":                      # map
            return {_hashable(self.read_reply()): self.read_reply() for _ in range(int(rest))}
        raise ProtocolError(f"unknown reply type: {line!r}")

    # ---- high level ------------------------------------------------------

    def execute(self, *args):
        """Send one command and return its reply; raises RedisError on error reply."""
        self.send_raw(encode_command(*args))
        reply = self.read_reply()
        if isinstance(reply, RedisError):
            raise reply
        return reply

    def pipeline(self, commands):
        """Send several commands in one write, then read all replies (errors are returned, not raised)."""
        self.send_raw(b"".join(encode_command(*c) for c in commands))
        return [self.read_reply() for _ in commands]

    def close(self):
        try:
            self._rfile.close()
        finally:
            self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _hashable(x):
    return tuple(x) if isinstance(x, list) else x


def _dump(prefix: str, data: bytes) -> None:
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hx = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"{prefix} {i:04x}  {hx:<47}  {asc}", file=sys.stderr)


# ---- output formatting (redis-cli style) ----------------------------------

def format_reply(r, indent: int = 0) -> str:
    pad = " " * indent
    if r is None:
        return "(nil)"
    if isinstance(r, RedisError):
        return f"(error) {r}"
    if isinstance(r, bool):
        return "(true)" if r else "(false)"
    if isinstance(r, int):
        return f"(integer) {r}"
    if isinstance(r, float):
        return f"(double) {r}"
    if isinstance(r, bytes):
        return '"' + r.decode("utf-8", errors="backslashreplace").replace('"', '\\"') + '"'
    if isinstance(r, str):
        return r
    if isinstance(r, dict):
        r = [x for kv in r.items() for x in kv]
    if isinstance(r, list):
        if not r:
            return "(empty array)"
        w = len(str(len(r)))
        lines = []
        for i, item in enumerate(r, 1):
            prefix = f"{i:>{w}}) "
            body = format_reply(item, indent + len(prefix))
            lines.append((pad if i > 1 else "") + prefix + body)
        return "\n".join(lines)
    return repr(r)


# ---- modes ----------------------------------------------------------------

def repl(client: RedisClient) -> None:
    prompt = f"{client.host}:{client.port}> "
    try:
        import readline  # noqa: F401  (line editing / history if available)
    except ImportError:
        pass
    while True:
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return
        try:
            args = shlex.split(line)
        except ValueError as e:
            print(f"(parse error) {e}")
            continue
        if not args:
            continue
        if args[0].lower() in ("quit", "exit"):
            return
        client.send_raw(encode_command(*args))
        print(format_reply(client.read_reply()))


def bench(client: RedisClient, args, n: int, depth: int) -> None:
    payload = encode_command(*args)
    lat_ns = []
    errors = 0
    done = 0
    t_start = time.perf_counter_ns()
    while done < n:
        k = min(depth, n - done)
        t0 = time.perf_counter_ns()
        client.send_raw(payload * k)
        for _ in range(k):
            if isinstance(client.read_reply(), RedisError):
                errors += 1
        lat_ns.append(time.perf_counter_ns() - t0)
        done += k
    elapsed = (time.perf_counter_ns() - t_start) / 1e9

    lat_ns.sort()
    us = lambda q: lat_ns[min(len(lat_ns) - 1, int(q * len(lat_ns)))] / 1000
    unit = "request" if depth == 1 else f"batch of {depth}"
    print(f"command   : {' '.join(args)}")
    print(f"requests  : {n} (pipeline depth {depth}, errors {errors})")
    print(f"elapsed   : {elapsed:.3f} s")
    print(f"throughput: {n / elapsed:,.0f} req/s")
    print(f"latency per {unit} (us):")
    print(f"  min {us(0):.1f}  p50 {us(0.5):.1f}  p90 {us(0.9):.1f}  "
          f"p99 {us(0.99):.1f}  p99.9 {us(0.999):.1f}  max {lat_ns[-1] / 1000:.1f}  "
          f"avg {sum(lat_ns) / len(lat_ns) / 1000:.1f}")


def main() -> int:
    p = argparse.ArgumentParser(description="Minimal RESP client for Redis")
    p.add_argument("-H", "--host", default="127.0.0.1")
    p.add_argument("-p", "--port", type=int, default=6379)
    p.add_argument("-t", "--timeout", type=float, default=5.0)
    p.add_argument("--bench", type=int, metavar="N", help="send the command N times and report latency")
    p.add_argument("-P", "--pipeline", type=int, default=1, metavar="DEPTH",
                   help="pipeline depth for --bench (default 1)")
    p.add_argument("--hexdump", action="store_true", help="hexdump bytes sent/received to stderr")
    p.add_argument("command", nargs=argparse.REMAINDER, help="command and arguments")
    a = p.parse_args()

    if a.bench and not a.command:
        p.error("--bench requires a command")
    if a.pipeline < 1:
        p.error("--pipeline must be >= 1")

    try:
        client = RedisClient(a.host, a.port, a.timeout, hexdump=a.hexdump)
    except OSError as e:
        print(f"could not connect to {a.host}:{a.port}: {e}", file=sys.stderr)
        return 1

    with client:
        if a.bench:
            bench(client, a.command, a.bench, a.pipeline)
        elif a.command:
            client.send_raw(encode_command(*a.command))
            reply = client.read_reply()
            print(format_reply(reply))
            return 1 if isinstance(reply, RedisError) else 0
        else:
            repl(client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
