"""WPO agents: a LangGraph supervisor over four nightly nodes, plus Manager Copilot.

Agents reach systems only through MCP (see wpo_agents.mcp_client). No module in
this package imports httpx to call a stub.
"""
