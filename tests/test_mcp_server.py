import unittest

from mcp.server import McpServer


class McpServerTests(unittest.TestCase):
    def tearDown(self):
        if hasattr(self, "server"):
            self.server.close()

    def test_tool_catalog_is_safe_and_typed(self):
        self.server = McpServer(".")
        response = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("get_runtime_status", names)
        self.assertIn("set_layer", names)
        self.assertNotIn("execute_shell", names)

    def test_unknown_tool_is_rejected(self):
        self.server = McpServer(".")
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "execute_shell", "arguments": {}},
            }
        )
        self.assertTrue(response["result"]["isError"])

    def test_named_layer_and_metrics_tools_use_product_commands(self):
        self.server = McpServer(".")
        layer = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "set_layer", "arguments": {"layer": "lod"}},
            }
        )
        self.assertFalse(layer["result"]["isError"])
        self.assertEqual(layer["result"]["structuredContent"]["layer"], "lod")
        metrics = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "get_metrics", "arguments": {}},
            }
        )
        self.assertEqual(metrics["result"]["structuredContent"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
