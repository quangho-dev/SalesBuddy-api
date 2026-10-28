import os
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv

load_dotenv()

if not os.getenv("SUPABASE_API_URL") or not os.getenv("SUPABASE_SECRET_KEY"):
    raise ValueError(
        "SUPABASE_API_URL and SUPABASE_SECRET_KEY must be set in .env file"
    )

if not os.getenv("CLERK_SECRET_KEY") or not os.getenv("DOMAIN"):
    raise ValueError("CLERK_SECRET_KEY and DOMAIN must be set in .env file")


if (
    not os.getenv("S3_BUCKET_NAME")
    or not os.getenv("AWS_REGION")
    or not os.getenv("AWS_SECRET_ACCESS_KEY")
    or not os.getenv("AWS_ACCESS_KEY_ID")
    or not os.getenv("AWS_ENDPOINT_URL_S3")
):
    raise ValueError(
        "S3_BUCKET_NAME, AWS_REGION, AWS_ACCESS_KEY_ID, AWS_ENDPOINT_URL_S3 and AWS_SECRET_ACCESS_KEY must be set in .env file"
    )

if not os.getenv("REDIS_URL"):
    raise ValueError("REDIS_URL must be set in .env file")

if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY must be set in .env file")

if not os.getenv("SCRAPINGBEE_API_KEY"):
    raise ValueError("SCRAPINGBEE_API_KEY must be set in .env file")

if not os.getenv("TAVILY_API_KEY"):
    raise ValueError("TAVILY_API_KEY must be set in .env file")

_langsmith_api_key = (os.getenv("LANGSMITH_API_KEY") or "").strip()
_langsmith_project = (
    os.getenv("LANGSMITH_PROJECT") or "sales-buddy-search-target-customers"
)
_langsmith_endpoint = (
    os.getenv("LANGSMITH_ENDPOINT") or "https://api.smith.langchain.com"
)
_langsmith_enabled = bool(_langsmith_api_key)

if _langsmith_enabled:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = _langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = _langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = _langsmith_endpoint

def _docker_host_url(url: str, *, in_docker: bool) -> str:
    """Inside Docker, 127.0.0.1 and localhost are the container, not the host.

    Remote URLs such as https://*.supabase.co stay unchanged, including in production.
    """
    if not in_docker:
        return url
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return url
    host = "host.docker.internal"
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth = f"{auth}:{parsed.password}"
        netloc = f"{auth}@{netloc}"
    return urlunparse(parsed._replace(netloc=netloc))


def _supabase_api_url() -> str:
    return _docker_host_url(
        os.getenv("SUPABASE_API_URL") or "",
        in_docker=os.path.exists("/.dockerenv"),
    )


appConfig = {
    "supabase_api_url": _supabase_api_url(),
    "supabase_secret_key": os.getenv("SUPABASE_SECRET_KEY"),
    "clerk_secret_key": os.getenv("CLERK_SECRET_KEY"),
    "domain": os.getenv("DOMAIN"),
    "s3_bucket_name": os.getenv("S3_BUCKET_NAME"),
    "aws_region": os.getenv("AWS_REGION"),
    "aws_endpoint_url_s3": os.getenv("AWS_ENDPOINT_URL_S3"),
    "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
    "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
    "redis_url": os.getenv("REDIS_URL"),
    "openai_api_key": os.getenv("OPENAI_API_KEY"),
    "scrapingbee_api_key": os.getenv("SCRAPINGBEE_API_KEY"),
    "tavily_api_key": os.getenv("TAVILY_API_KEY"),
    "langsmith_enabled": _langsmith_enabled,
    "langsmith_api_key": _langsmith_api_key,
    "langsmith_project": _langsmith_project,
    "langsmith_endpoint": _langsmith_endpoint,
}
