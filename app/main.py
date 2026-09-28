from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from langsmith import traceable
from dotenv import load_dotenv

from app.config import get_settings
from app.models import (
    ChatRequest, ChatResponse, HealthResponse, MetricsResponse, ErrorResponse
)
from app.security import SecurityPipeline
from app.cache import ResponseCache
from app.monitoring import get_logger, MetricsCollector, RequestTimer
from app.agent import ProductionAgent

load_dotenv()

logger = get_logger()

security: SecurityPipeline | None = None
cache: ResponseCache | None = None
metrics: MetricsCollector | None = None
agent: ProductionAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global security, cache, metrics, agent
    settings = get_settings()

    logger.info("Starting production API...", extra={"extra_data": {
        "environment": settings.app_env,
        "primary_model": settings.primary_model,
        "tracing_enabled": settings.langsmith_tracing,
    }})
    security = SecurityPipeline()
    cache = ResponseCache(ttl_seconds=settings.cache_ttl_seconds)
    metrics = MetricsCollector()
    agent = ProductionAgent()

    logger.info("All components initialized. Ready to serve requests.")

    yield

    logger.info("Shutting down...", extra={"extra_data": metrics.summary})


limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="Production LangGraph API",
    description="A production-ready chat API with security, caching, and observability",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", extra={"extra_data": {
        "path": request.url.path,
    }})
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_server_error",
            detail="An unexpected error occurred.",
        ).model_dump(),
    )


@app.post("/chat", response_model=ChatResponse)
@limiter.limit(get_settings().rate_limit)
@traceable(name="chat_endpoint")
async def chat(request: Request, body: ChatRequest):
    security_notes = []

    is_allowed, cleaned_message, notes = security.check_input(body.message)
    security_notes.extend(notes)

    if not is_allowed:
        logger.warning("Request blocked by security", extra={"extra_data": {
            "reason": notes,
            "thread_id": body.thread_id,
        }})
        metrics.record_request(latency_ms=0, error=True)
        raise HTTPException(
            status_code=400,
            detail="Your message was blocked by our security filters.",
        )

    cached_response = cache.get(cleaned_message)
    if cached_response is not None:
        metrics.record_request(latency_ms=0, cache_hit=True)
        logger.info("Cache hit", extra={"extra_data": {
            "thread_id": body.thread_id,
        }})
        return ChatResponse(
            response=cached_response,
            thread_id=body.thread_id,
            model_used="cache",
            cached=True,
            processing_time_ms=0,
        )

    with RequestTimer() as timer:
        try:
            # agent.invoke is synchronous; keep it off the event loop
            result = await run_in_threadpool(agent.invoke, cleaned_message)
        except Exception as e:
            logger.error(f"Agent invocation failed: {e}", extra={"extra_data": {
                "thread_id": body.thread_id,
                "error": str(e),
            }})
            metrics.record_request(latency_ms=0, error=True)
            raise HTTPException(
                status_code=500,
                detail="An error occurred while processing your request.",
            )

        response_text = result["response"]
        model_used = result["model_used"]

        validated_response, output_warnings = security.check_output(response_text)
        security_notes.extend(output_warnings)

        # Don't cache the fallback apology when both models failed
        agent_failed = model_used == "error_handler"
        if not agent_failed:
            cache.set(cleaned_message, validated_response)

    # Rough token estimate: ~1.3 tokens per word
    input_tokens = int(len(cleaned_message.split()) * 1.3)
    output_tokens = int(len(validated_response.split()) * 1.3)

    metrics.record_request(
        latency_ms=timer.elapsed,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error=agent_failed,
        cache_hit=False,
    )

    logger.info("Request completed", extra={"extra_data": {
        "thread_id": body.thread_id,
        "model_used": model_used,
        "latency_ms": round(timer.elapsed, 2),
        "security_notes": security_notes,
    }})

    if security_notes:
        logger.info("Security notes", extra={"extra_data": {
            "notes": security_notes,
            "thread_id": body.thread_id,
        }})

    return ChatResponse(
        response=validated_response,
        thread_id=body.thread_id,
        model_used=model_used,
        cached=False,
        processing_time_ms=round(timer.elapsed, 2),
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    settings = get_settings()
    return HealthResponse(
        environment=settings.app_env,
        checks={
            "agent": agent is not None,
            "cache": cache.stats if cache else None,
        },
    )


@app.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    summary = metrics.summary
    return MetricsResponse(
        total_requests=summary["requests_total"],
        total_errors=summary["errors_total"],
        error_rate=summary["error_rate"],
        avg_latency_ms=str(summary["avg_latency_ms"]),
        cache_hit_rate=summary["cache_hit_rate"],
        total_input_tokens=summary["input_tokens"],
        total_output_tokens=summary["output_tokens"],
    )

@app.get("/cache/stats")
async def cache_stats():
    return cache_stats

