import logging
import json
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

class JSONFormatter(logging.Formatter):

    def format(self, record):
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }
        if hasattr(record, "extra_data"):
            log_obj.update(record.extra_data)
        return json.dumps(log_obj)
             
def get_logger(name: str = "production-api") -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

class MetricsCollector:

    def __init__(self):
        self._requests_total = 0
        self._error_total = 0
        self._latency_sum = 0.0
        self._latency_count = 0
        self._token_input = 0
        self._token_output = 0
        self._cache_hits = 0
        self._cache_misses = 0

    def record_request(
            self,
            latency_ms : float,
            input_tokens: int = 0,
            output_tokens: int = 0,
            error: bool = False,
            cache_hit: bool = False,
     ):
        self._requests_total +=1
        self._latency_sum += latency_ms
        self._latency_count += 1
        self._token_input += input_tokens
        self._token_output += output_tokens

        if error:
            self._error_total += 1
        if cache_hit:
            self._cache_hits += 1
        else:
            self._cache_misses += 1

    @property
    def summary(self) -> dict:
        avg_latency = (
            self._latency_sum / self._latency_count
            if self._latency_count > 0 else 0.0
        )
        error_rate = (
            self._error_total / self._requests_total
            if self._requests_total > 0 else 0.0
        )
        cache_total = self._cache_hits + self._cache_misses
        cache_hit_rate = (
            self._cache_hits / cache_total
            if cache_total > 0 else 0.0
        )

        return {
            "requests_total": self._requests_total,
            "errors_total": self._error_total,
            "error_rate": f"{error_rate:.1%}",
            "avg_latency_ms": round(avg_latency, 2),
            "input_tokens": self._token_input,
            "output_tokens": self._token_output,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": f"{cache_hit_rate:.1%}",
        }

class RequestTimer:

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.elapsed = (time.time() - self.start) * 1000


