"""Configuracion por variables de entorno (sin valores por defecto para secretos)."""
import os

COGNEE_API_URL = os.environ.get("COGNEE_API_URL", "http://agents_cognee_api:8000")
COGNEE_MCP_URL = os.environ.get("COGNEE_MCP_URL", "http://agents_cognee_mcp:8000")
COGNEE_API_KEY = os.environ.get("COGNEE_API_KEY", "")  # preferred: revocable and passwordless
COGNEE_USER_EMAIL = os.environ.get("COGNEE_USER_EMAIL", "")
COGNEE_USER_PASSWORD = os.environ.get("COGNEE_USER_PASSWORD", "")

PG = dict(
    host=os.environ.get("INSPECTOR_PG_HOST", "agents_postgres"),
    port=int(os.environ.get("INSPECTOR_PG_PORT", "5432")),
    dbname=os.environ.get("INSPECTOR_PG_DB", "agents_memory"),
    user=os.environ.get("INSPECTOR_PG_USER", "agents_inspector"),
    password=os.environ.get("INSPECTOR_PG_PASSWORD", ""),
)

OBSERVER_URL = os.environ.get("OBSERVER_URL", "http://host.docker.internal:8017")
TELEMETRY_DIR = os.environ.get("TELEMETRY_DIR", "/telemetry")
OBSERVER_LOG = os.environ.get("OBSERVER_LOG", "/observer/observer-events.log")
REGISTRY_FILE = os.environ.get("REGISTRY_FILE", "/state/registry.json")
USAGE_FILE = os.environ.get("USAGE_FILE", "/state/usage.jsonl")
HOST_AGENT_URL = os.environ.get("HOST_AGENT_URL", "http://host.docker.internal:8018")
ALLOWED_HOSTS = [h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

STORAGE_DIR = os.environ.get("STORAGE_DIR", "/cognee-storage")
DOCKER_PROXY_URL = os.environ.get("DOCKER_PROXY_URL", "")
STACK_PROJECT = os.environ.get("STACK_PROJECT", "agents_memory_system")
CHARS_PER_TOKEN = float(os.environ.get("CHARS_PER_TOKEN", "3.8"))

# Swarm monitoring: dedicated READ-ONLY role (select on schema swarm only)
SWARM_PG = dict(
    host=PG["host"], port=PG["port"], dbname=os.environ.get("SWARM_PG_DB", PG["dbname"]),
    user=os.environ.get("SWARM_PG_USER", "swarm_reader"), password=os.environ.get("SWARM_PG_PASSWORD", ""),
)
