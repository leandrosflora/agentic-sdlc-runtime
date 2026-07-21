"""Minimal MCP server over stdio used by test_mcp_stdio.py.

Speaks newline-delimited JSON-RPC 2.0 and exposes two tools: `echo`, which
returns its arguments, and `boom`, which reports a tool execution error.
"""
import json
import sys

TOOLS = [
    {"name": "echo", "description": "Echo the arguments back",
     "inputSchema": {"type": "object"}},
    {"name": "boom", "description": "Always fails",
     "inputSchema": {"type": "object"}},
]


def reply(request_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        if "id" not in message:
            continue  # notification
        if method == "initialize":
            # A server-initiated notification before the response exercises
            # the client's id matching.
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/message",
                                         "params": {"level": "info", "data": "ready"}}) + "\n")
            reply(message["id"], {"protocolVersion": message["params"]["protocolVersion"],
                                  "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "echo-mcp", "version": "0.0.1"}})
        elif method == "tools/list":
            reply(message["id"], {"tools": TOOLS})
        elif method == "tools/call":
            name = message["params"]["name"]
            if name == "echo":
                reply(message["id"], {"content": [{"type": "text",
                                                   "text": json.dumps(message["params"]["arguments"])}],
                                      "isError": False})
            else:
                reply(message["id"], {"content": [{"type": "text", "text": "kaboom"}],
                                      "isError": True})
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                                         "error": {"code": -32601, "message": f"unknown method {method}"}}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
