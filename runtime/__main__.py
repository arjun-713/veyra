"""Launch with python -m runtime --repo PATH; stdin is bounded NDJSON."""

import argparse
import json
import os
import sys
import threading

from .protocol import MAX_REQUEST, encode_message
from .service import ProductRuntime


def main():
    parser = argparse.ArgumentParser(description="Veyra supervised product runtime")
    parser.add_argument("--repo", default=os.getcwd())
    args = parser.parse_args()
    # Third-party Python and native extensions may print. Reserve fd1 exclusively for framing.
    output = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    runtime = ProductRuntime(args.repo)

    def writer():
        try:
            while True:
                item = runtime.outbox.take()
                if item is None:
                    if runtime.outbox.closed:
                        return
                    continue
                packet = memoryview(encode_message(*item))
                while packet:
                    sent = output.write(packet)
                    if not sent:
                        raise BrokenPipeError()
                    packet = packet[sent:]
        except (OSError, ValueError):
            runtime.stopping.set()

    worker = threading.Thread(target=runtime.run, name="veyra-playback", daemon=True)
    sender = threading.Thread(target=writer, name="veyra-output", daemon=True)
    worker.start()
    sender.start()
    try:
        for line in iter(lambda: sys.stdin.buffer.readline(MAX_REQUEST + 1), b""):
            if runtime.stopping.is_set():
                break
            if len(line) > MAX_REQUEST:
                raise ValueError("request exceeds size limit")
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise TypeError("request must be an object")
                if request.get("command") == "status":
                    runtime.outbox.publish(runtime.handle(request))
                else:
                    runtime.submit(request)
            except (TypeError, ValueError, UnicodeDecodeError) as error:
                runtime.outbox.publish(
                    {
                        "type": "response",
                        "id": None,
                        "ok": False,
                        "status": runtime.status(),
                        "error": {"code": "invalid_request", "message": str(error)},
                    }
                )
        # EOF is a queued shutdown so earlier commands have deterministic completion order.
        runtime.commands.put(
            {"id": "__eof__", "command": "shutdown", "args": {}}, timeout=2
        )
    except Exception as error:  # noqa: BLE001 - top-level boundary reports and stops the runtime.
        print(str(error), file=sys.stderr)
        runtime.stopping.set()
    worker.join(timeout=35)
    if worker.is_alive():
        if runtime.session:
            runtime.session.map_runner.close()
        runtime.stopping.set()
    sender.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
