"""Trial-local Responses relay. Run only outside the untrusted worker.

No HTTP control interface, credential forwarding, stored resources or hosted tools.
The controller alone writes /state/control.json and retains /state/meter.json.
"""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import threading
import time


MAX_BODY = 512 * 1024
MAX_RESPONSE = 2 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_REQUESTS = 64
MAX_TOKENS = 4096
MAX_SECONDS = 7200
ALLOWED = {
    "model", "instructions", "input", "tools", "tool_choice", "parallel_tool_calls",
    "reasoning", "stream", "store", "include", "text", "metadata", "client_metadata",
    "max_output_tokens", "prompt_cache_key", "service_tier", "stream_options",
}


def local_tool(tool):
    if not isinstance(tool, dict):
        return False
    if tool.get("type") == "namespace":
        return isinstance(tool.get("tools"), list) and all(local_tool(t) for t in tool["tools"])
    return tool.get("type") in {"function", "custom"}


def inline_text(value):
    return isinstance(value, str) or isinstance(value, list) and all(
        isinstance(c, dict) and c.get('type') in {'input_text', 'output_text'}
        and not c.keys() - {'type', 'text', 'annotations', 'logprobs'} and isinstance(c.get('text'), str) for c in value)


def validate(data, model, effort, trial):
    if not isinstance(data, dict) or data.keys() - ALLOWED:
        raise ValueError("unsupported request fields")
    reasoning = data.get("reasoning")
    if not isinstance(reasoning, dict) or reasoning.keys() - {"effort", "summary", "context"}:
        raise ValueError("unsupported reasoning settings")
    if reasoning.get('context') != 'all_turns':
        raise ValueError('reasoning context drift')
    if data.get("model") != model or reasoning.get("effort") != effort:
        raise ValueError("model/reasoning drift")
    if data.get("store") is not False or data.get("stream") is not True:
        raise ValueError("only non-stored streaming responses")
    if data.get("tool_choice", "auto") not in ("auto", "none", "required"):
        raise ValueError("unsupported tool selection")
    if not isinstance(data.get("tools", []), list) or not all(local_tool(t) for t in data.get("tools", [])):
        raise ValueError("hosted/unsupported tools")
    if data.get("service_tier") not in (None, "default"):
        raise ValueError("service tier drift")
    if set(data.get("include", [])) - {"reasoning.encrypted_content"}:
        raise ValueError("unsupported server includes")
    if data.get("text", {}).get("format", {}).get("type", "text") != "text":
        raise ValueError("unsupported output format")
    items = data.get("input")
    if not isinstance(items, list):
        raise ValueError("expanded input required")
    for item in items:
        if not isinstance(item, dict) or item.get("type", "message") not in {
            "message", "agent_message", "function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output", "reasoning", "additional_tools",
        }:
            raise ValueError("stored/media input reference")
        if item.get('type') == 'agent_message':
            # Native local reviewer envelopes carry inline text and opaque
            # inherited context, never a hosted conversation/resource handle.
            if (item.keys() - {'type', 'id', 'author', 'recipient', 'content', 'internal_chat_message_metadata_passthrough'}
                    or any(not isinstance(item.get(k), str) or not item[k].startswith('/root') for k in ('author', 'recipient'))
                    or not isinstance(item.get('content'), list)
                    or any(not isinstance(c, dict) or not (
                        c.keys() == {'type', 'text'} and c.get('type') == 'input_text' and isinstance(c.get('text'), str)
                        or c.keys() == {'type', 'encrypted_content'} and c.get('type') == 'encrypted_content' and isinstance(c.get('encrypted_content'), str)
                    ) for c in item['content'])):
                raise ValueError('unsupported local agent context')
        if item.get('type') == 'additional_tools':
            if item.keys() - {'type', 'id', 'role', 'tools'} or item.get('role') != 'developer' or not isinstance(item.get('tools'), list) or not all(local_tool(t) for t in item['tools']):
                raise ValueError('hosted/unsupported additional tools')
        if item.get('type') in {'function_call_output', 'custom_tool_call_output'} and not inline_text(item.get('output')):
            raise ValueError('only inline text tool output')
        if item.get("type", "message") == "message":
            content = item.get("content", [])
            if not isinstance(content, list) or any(
                not isinstance(c, dict) or c.get("type") not in {"input_text", "output_text"}
                or c.keys() - {"type", "text", "annotations", "logprobs"} for c in content
            ):
                raise ValueError("only inline text context")
    tokens = data.get("max_output_tokens", MAX_TOKENS)
    if type(tokens) is not int or not 1 <= tokens <= MAX_TOKENS:
        raise ValueError("output token limit")
    return {**data, "max_output_tokens": tokens, "prompt_cache_key": trial}


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class Relay:
    def __init__(self, state, model, effort, trial, credential):
        self.state, self.model, self.effort, self.trial = Path(state), model, effort, trial
        self.credential = credential
        self.state.mkdir(parents=True, exist_ok=True)
        if (self.state / "meter.json").exists():
            raise RuntimeError("relay restart cannot reset retained quotas")
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.connections = {}
        self.started = time.monotonic()
        self.meter = {"trial": trial, "requests": 0, "input_bytes": 0, "output_bytes": 0, "accepted": 0, "denied": 0, 'closed_reason': None}
        self.save()
        threading.Thread(target=self.watch, daemon=True).start()

    def save(self):
        tmp = self.state / "meter.tmp"
        tmp.write_text(json.dumps(self.meter), encoding="utf-8")
        tmp.replace(self.state / "meter.json")

    def armed(self):
        try:
            control = json.loads((self.state / "control.json").read_text())
            return (control["trial"] == self.trial and time.time() < control["expires"]
                    and time.monotonic() - self.started < MAX_SECONDS
                    and self.meter['closed_reason'] is None
                    and self.meter['requests'] <= MAX_REQUESTS
                    and self.meter['input_bytes'] <= MAX_TOTAL and self.meter['output_bytes'] <= MAX_TOTAL)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def watch(self):
        while not self.stop.is_set():
            if not self.armed():
                with self.lock:
                    for conn, active_socket in list(self.connections.items()):
                        if active_socket is None:
                            # DNS/connect/TLS/send can block before a controllable
                            # socket is published. End this disposable relay so
                            # no delayed setup can send after admission closes.
                            self.meter['closed_reason'] = 'admission revoked during upstream setup'
                            self.save()
                            os._exit(70)
                        # Keep the actual TLS socket even when getresponse()
                        # detaches conn.sock for a Connection: close response.
                        for active in {active_socket, conn.sock} - {None}:
                            try:
                                active.shutdown(socket.SHUT_RDWR)
                            except OSError:
                                pass
                        conn.close()
            self.stop.wait(0.1)


class Handler(BaseHTTPRequestHandler):
    server_version = "EvaluationRelay"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass  # Request bodies/headers and upstream errors are never diagnostics.

    def parse_request(self):
        if not super().parse_request():
            return False
        relay = self.server.relay
        with relay.lock:
            relay.meter['requests'] += 1
            if relay.meter['requests'] > MAX_REQUESTS:
                relay.meter['closed_reason'] = 'request quota exhausted'
            relay.save()
            if relay.meter['closed_reason']:
                self.reply(403, {'error': 'aggregate quota exhausted'})
                return False
        return True

    def reply(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"trial": self.server.relay.trial, "model": self.server.relay.model})
        else:
            self.reply(403, {"error": "unsupported operation"})

    def do_POST(self):
        relay, conn = self.server.relay, None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.path != "/v1/responses" or self.headers.get("Transfer-Encoding") or self.headers.get("Upgrade") or not 0 < length <= MAX_BODY:
                raise ValueError("unsupported operation/size")
            with relay.lock:
                relay.meter["input_bytes"] += length
                relay.save()
                if relay.meter['input_bytes'] > MAX_TOTAL:
                    relay.meter['closed_reason'] = 'input quota exhausted'
                    relay.save()
                    raise ValueError("aggregate quota exhausted")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("incomplete body")
            data = json.loads(body, object_pairs_hook=strict_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
            data = validate(data, relay.model, relay.effort, relay.trial)
            with relay.lock:
                if not relay.armed():
                    raise ValueError("admission closed")
                conn = http.client.HTTPSConnection("api.openai.com", timeout=60)
                relay.connections[conn] = None
                relay.meter["accepted"] += 1
                relay.save()
            conn.request("POST", "/v1/responses", json.dumps(data), {
                "Authorization": "Bearer " + relay.credential,
                "Content-Type": "application/json", "Accept": "text/event-stream", "Accept-Encoding": "identity",
            })
            with relay.lock:
                relay.connections[conn] = socket.socket(fileno=socket.dup(conn.sock.fileno())) if conn.sock else None
            response = conn.getresponse()
            if response.status != 200:
                self.reply(502, {"error": "upstream rejected", "upstream_status": response.status})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            count = 0
            while relay.armed():
                chunk = response.read1(65536)
                if not chunk:
                    break
                count += len(chunk)
                with relay.lock:
                    relay.meter["output_bytes"] += len(chunk)
                    relay.save()
                    if count > MAX_RESPONSE or relay.meter["output_bytes"] > MAX_TOTAL:
                        relay.meter['closed_reason'] = 'response quota exhausted'
                        relay.save()
                        raise OSError("response quota exhausted")
                self.wfile.write(chunk)
                self.wfile.flush()
        except (ValueError, TypeError, AttributeError) as error:
            with relay.lock:
                relay.meter["denied"] += 1
                relay.save()
            self.reply(403, {"error": str(error)[:100]})
        except (OSError, http.client.HTTPException):
            self.close_connection = True
        finally:
            if conn:
                with relay.lock:
                    control_socket = relay.connections.pop(conn, None)
                    if control_socket:
                        control_socket.close()
                conn.close()


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, relay):
        super().__init__(address, Handler)
        self.relay = relay
        self.slots = threading.BoundedSemaphore(3)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            with self.relay.lock:
                self.relay.meter['requests'] += 1
                self.relay.meter['denied'] += 1
                if self.relay.meter['requests'] > MAX_REQUESTS:
                    self.relay.meter['closed_reason'] = 'request quota exhausted'
                self.relay.save()
            request.close()
            return
        super().process_request(request, address)

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


if __name__ == "__main__":
    Server(("0.0.0.0", 8080), Relay("/state", os.environ["EVALUATION_MODEL"], os.environ["EVALUATION_EFFORT"],
                                   os.environ["EVALUATION_TRIAL"], os.environ["OPENAI_API_KEY"])).serve_forever()
