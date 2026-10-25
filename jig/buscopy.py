"""Speak to Alfred's local bus copy. Does not start a broker. Does not print a token."""

import base64
import json
import os
import socket
import struct


def _handshake(sock, host, port, path):
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        "GET %s HTTP/1.1\r\n"
        "Host: %s:%s\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: %s\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    ) % (path, host, port, key)
    sock.sendall(request.encode())
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("bus copy closed")
        data += chunk
    head, rest = data.split(b"\r\n\r\n", 1)
    status = head.split(b"\r\n", 1)[0].decode("iso-8859-1", "replace")
    if " 101 " not in status:
        raise RuntimeError("bus copy refused the join")
    return rest


class Link:
    def __init__(self, host, port, path="/ws", timeout=10):
        self.sock = socket.create_connection((host, port), timeout)
        self.sock.settimeout(timeout)
        self.buf = _handshake(self.sock, host, port, path)

    def send(self, text):
        payload = text.encode()
        mask = os.urandom(4)
        n = len(payload)
        header = bytearray([0x81])
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", n))
        header.extend(mask)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv(self):
        def take(n):
            while len(self.buf) < n:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise RuntimeError("bus copy closed")
                self.buf += chunk
            out, self.buf = self.buf[:n], self.buf[n:]
            return out

        while True:
            b0, b1 = take(2)
            opcode = b0 & 0x0F
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack("!H", take(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", take(8))[0]
            if b1 & 0x80:
                mask = take(4)
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(take(length)))
            else:
                payload = take(length)
            if opcode == 0x1:
                return payload.decode()
            if opcode == 0x8:
                raise RuntimeError("bus copy closed")

    def drain(self, timeout=0.2):
        frames = []
        self.sock.settimeout(timeout)
        try:
            while True:
                frames.append(self.recv())
        except (TimeoutError, socket.timeout):
            return frames
        finally:
            self.sock.settimeout(10)

    def close(self):
        self.sock.close()


def _json(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("bus copy sent a bad frame") from exc


def exchange(host, port, token, sender, target, body, timeout=10):
    """Alfred's copy carries one message to Jig. The token is not returned."""
    left = Link(host, port, timeout=timeout)
    right = Link(host, port, timeout=timeout)
    try:
        left.send(json.dumps({"op": "join", "peer": sender, "token": token}))
        joined = _json(left.recv())
        if joined.get("op") != "joined" or joined.get("peer") != sender:
            raise RuntimeError("sender did not join")
        left.drain()
        right.send(json.dumps({"op": "join", "peer": target, "token": token}))
        joined = _json(right.recv())
        if joined.get("op") != "joined" or joined.get("peer") != target:
            raise RuntimeError("jig did not join")
        right.drain()
        left.send(json.dumps({"op": "send", "to": target, "body": body}))
        queued = _json(left.recv())
        while queued.get("op") != "queued":
            queued = _json(left.recv())
        if queued.get("to") != target:
            raise RuntimeError("send was not queued")
        delivered = _json(right.recv())
        while delivered.get("body") != body:
            delivered = _json(right.recv())
        if delivered.get("op") != "deliver":
            raise RuntimeError("jig did not receive the body")
        right.send(json.dumps({"op": "ack", "id": delivered["id"]}))
        acked = _json(right.recv())
        if acked.get("op") != "acked":
            raise RuntimeError("ack was rejected")
        return {"from": sender, "to": target, "body": delivered["body"], "ack": acked["op"]}
    finally:
        right.close()
        left.close()
