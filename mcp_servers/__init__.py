"""MCP servers. The only way agents reach a system.

One MCP server per system. Each wraps its stub over HTTP; agents never call a
stub directly. Write tools carry destructiveHint: true so NaviStorm's
discovery classifies them as write edges and keeps faults off them.
"""
