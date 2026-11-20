FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY stubs/ stubs/
COPY mcp_servers/ mcp_servers/
COPY wpo_agents/ wpo_agents/
COPY wpo_ui/ wpo_ui/
COPY run_systems.py topology.yaml ./

# stubs 8101-8106, MCP servers 9101-9108, WPO console 8000
EXPOSE 8000 8101-8106 9101-9108

CMD ["python", "run_systems.py"]
