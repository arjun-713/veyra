import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

from viewer import server
from viewer.runtime import RuntimeSession


def _write_frame(root: Path, frame_id: str, x: float) -> None:
    scans = root / "00000" / "vel_cloud_node_kitti_bin"
    labels = root / "00000" / "vel_cloud_node_semantickitti_label_id"
    scans.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    np.asarray([[x, 0.0, 0.0, 0.2]], dtype=np.float32).tofile(scans / f"{frame_id}.bin")
    np.asarray([7], dtype=np.uint32).tofile(labels / f"{frame_id}.label")


class ViewerRuntimeHttpTests(unittest.TestCase):
    def test_local_http_runtime_exposes_frame_status_and_reset(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_frame(root, "000000", 1.0)
            _write_frame(root, "000001", 2.0)
            previous = server.RUNTIME
            listener = None
            thread = None
            try:
                server.RUNTIME = RuntimeSession.from_dataset_settings(
                    dataset="rellis3d",
                    dataset_root=root,
                    sequences=["00000"],
                    pipeline_config={"semantic": {"mode": "ground_truth"}},
                )
                listener = server.http.server.ThreadingHTTPServer(
                    ("127.0.0.1", 0), server.Handler
                )
                thread = threading.Thread(target=listener.serve_forever, daemon=True)
                thread.start()
                port = listener.server_address[1]

                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                connection.request("GET", "/api/runtime/status")
                status_response = connection.getresponse()
                status = json.loads(status_response.read())
                connection.request(
                    "GET", "/api/frame?dataset=rellis3d&seq=00000&index=1&budget=1000"
                )
                frame_response = connection.getresponse()
                frame = json.loads(frame_response.read())
                connection.request("POST", "/api/runtime/reset?budget=1000")
                reset_response = connection.getresponse()
                reset = json.loads(reset_response.read())
                connection.close()
            finally:
                if listener is not None:
                    listener.shutdown()
                    listener.server_close()
                if thread is not None:
                    thread.join(timeout=3)
                server.RUNTIME = previous

            self.assertEqual(status_response.status, 200)
            self.assertEqual(status["state"], "configured")
            self.assertEqual(frame_response.status, 200)
            self.assertEqual(frame["id"], "000001")
            self.assertEqual(reset_response.status, 200)
            self.assertEqual(reset["index"], 0)

    def test_map_cells_endpoint_reports_unavailable_without_map_runtime(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_frame(root, "000000", 1.0)
            previous = server.RUNTIME
            listener = None
            thread = None
            try:
                server.RUNTIME = RuntimeSession.from_dataset_settings(
                    dataset="rellis3d",
                    dataset_root=root,
                    sequences=["00000"],
                    pipeline_config={"semantic": {"mode": "ground_truth"}},
                )
                listener = server.http.server.ThreadingHTTPServer(
                    ("127.0.0.1", 0), server.Handler
                )
                thread = threading.Thread(target=listener.serve_forever, daemon=True)
                thread.start()
                port = listener.server_address[1]

                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                connection.request("GET", "/api/map_cells?budget=1000")
                cells_response = connection.getresponse()
                cells = json.loads(cells_response.read())
                connection.request("GET", "/api/map_cells?budget=nope")
                bad_response = connection.getresponse()
                bad_response.read()
                connection.close()
            finally:
                if listener is not None:
                    listener.shutdown()
                    listener.server_close()
                if thread is not None:
                    thread.join(timeout=3)
                server.RUNTIME = previous

            self.assertEqual(cells_response.status, 200)
            self.assertEqual(cells["status"], "unavailable")
            self.assertIn("reason", cells)
            self.assertEqual(bad_response.status, 400)


if __name__ == "__main__":
    unittest.main()
