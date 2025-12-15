"""Retry utilities with exponential backoff and circuit breaker pattern."""
import asyncio
import time
import functools
from typing import Callable, Any, Optional, Type, Tuple, List
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from src.utils.logging_config import get_logger

log = get_logger(__name__)


class ErrorType(Enum):
    """Error types for classification."""
    TRANSIENT = "transient"  # Temporary errors that might succeed on retry
    PERMANENT = "permanent"  # Errors that won't succeed on retry
    RATE_LIMIT = "rate_limit"  # Rate limiting errors
    TIMEOUT = "timeout"  # Timeout errors
    NETWORK = "network"  # Network errors
    UNKNOWN = "unknown"  # Unknown errors


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 3
    initial_delay: float = 1.0  # Initial delay in seconds
    max_delay: float = 60.0  # Maximum delay in seconds
    exponential_base: float = 2.0  # Exponential backoff base
    jitter: bool = True  # Add random jitter to avoid thundering herd
    retryable_errors: List[Type[Exception]] = field(default_factory=list)
    retryable_status_codes: List[int] = field(default_factory=lambda: [429, 500, 502, 503, 504])


class CircuitBreaker:
    """Circuit breaker pattern implementation."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Type[Exception] = Exception
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Time in seconds before attempting recovery
            expected_exception: Exception type to catch
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "closed"  # closed, open, half_open
        
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerOpenError if circuit is open
            Original exception if function fails
        """
        if self.state == "open":
            if self._should_attempt_recovery():
                self.state = "half_open"
                log.info("Circuit breaker entering half-open state")
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is open. Last failure: {self.last_failure_time}"
                )
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    async def call_async(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute async function with circuit breaker protection.
        
        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerOpenError if circuit is open
            Original exception if function fails
        """
        if self.state == "open":
            if self._should_attempt_recovery():
                self.state = "half_open"
                log.info("Circuit breaker entering half-open state")
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is open. Last failure: {self.last_failure_time}"
                )
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self.last_failure_time is None:
            return True
        
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout
    
    def _on_success(self):
        """Handle successful execution."""
        if self.state == "half_open":
            log.info("Circuit breaker recovered, closing circuit")
            self.state = "closed"
            self.failure_count = 0
        elif self.state == "closed":
            self.failure_count = 0
    
    def _on_failure(self):
        """Handle failed execution."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            if self.state != "open":
                log.warning(
                    f"Circuit breaker opened after {self.failure_count} failures",
                    extra={"failure_count": self.failure_count}
                )
            self.state = "open"
    
    def reset(self):
        """Manually reset circuit breaker."""
        self.state = "closed"
        self.failure_count = 0
        self.last_failure_time = None
        log.info("Circuit breaker manually reset")


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


def classify_error(error: Exception) -> ErrorType:
    """
    Classify error type for retry decision.
    
    Args:
        error: Exception to classify
        
    Returns:
        ErrorType enum
    """
    error_str = str(error).lower()
    error_type = type(error).__name__
    
    # Rate limiting errors
    if any(keyword in error_str for keyword in ["rate limit", "429", "quota", "quota exceeded"]):
        return ErrorType.RATE_LIMIT
    
    # Timeout errors
    if any(keyword in error_str or keyword in error_type for keyword in ["timeout", "Timeout", "timed out"]):
        return ErrorType.TIMEOUT
    
    # Network errors
    if any(keyword in error_str or keyword in error_type for keyword in [
        "connection", "network", "dns", "resolve", "unreachable"
    ]):
        return ErrorType.NETWORK
    
    # Transient errors (HTTP 5xx, temporary failures)
    if any(keyword in error_str for keyword in ["500", "502", "503", "504", "internal server error"]):
        return ErrorType.TRANSIENT
    
    # Permanent errors (HTTP 4xx except 429)
    if any(keyword in error_str for keyword in ["400", "401", "403", "404", "bad request", "unauthorized", "forbidden"]):
        return ErrorType.PERMANENT
    
    return ErrorType.UNKNOWN


def should_retry(error: Exception, attempt: int, max_retries: int) -> bool:
    """
    Determine if error should be retried.
    
    Args:
        error: Exception that occurred
        attempt: Current attempt number (1-indexed)
        max_retries: Maximum number of retries
        
    Returns:
        True if should retry, False otherwise
    """
    if attempt > max_retries:
        return False
    
    error_type = classify_error(error)
    
    # Don't retry permanent errors
    if error_type == ErrorType.PERMANENT:
        return False
    
    # Always retry transient, rate limit, timeout, and network errors
    if error_type in [ErrorType.TRANSIENT, ErrorType.RATE_LIMIT, ErrorType.TIMEOUT, ErrorType.NETWORK]:
        return True
    
    # For unknown errors, retry up to max_retries
    return True


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """
    Calculate delay for exponential backoff.
    
    Args:
        attempt: Current attempt number (1-indexed)
        config: Retry configuration
        
    Returns:
        Delay in seconds
    """
    import random
    
    # Exponential backoff: initial_delay * (base ^ (attempt - 1))
    delay = config.initial_delay * (config.exponential_base ** (attempt - 1))
    
    # Cap at max_delay
    delay = min(delay, config.max_delay)
    
    # Add jitter to avoid thundering herd
    if config.jitter:
        jitter = random.uniform(0, delay * 0.1)  # 10% jitter
        delay += jitter
    
    return delay


def retry_with_backoff(
    func: Optional[Callable] = None,
    *,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_errors: Optional[List[Type[Exception]]] = None
):
    """
    Decorator for retrying functions with exponential backoff.
    
    Args:
        func: Function to decorate (if used as decorator without arguments)
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Exponential backoff base
        jitter: Add random jitter
        retryable_errors: List of exception types to retry
        
    Returns:
        Decorated function
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        retryable_errors=retryable_errors or []
    )
    
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(1, config.max_retries + 1):
                try:
                    return f(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    
                    if not should_retry(e, attempt, config.max_retries):
                        log.debug(
                            f"Not retrying {type(e).__name__}: {str(e)}",
                            extra={"attempt": attempt, "error_type": classify_error(e).value}
                        )
                        raise
                    
                    if attempt < config.max_retries:
                        delay = calculate_delay(attempt, config)
                        error_type = classify_error(e)
                        
                        log.warning(
                            f"Retrying {f.__name__} after {delay:.2f}s (attempt {attempt}/{config.max_retries})",
                            extra={
                                "attempt": attempt,
                                "max_retries": config.max_retries,
                                "delay": delay,
                                "error_type": error_type.value,
                                "error": str(e)
                            }
                        )
                        
                        time.sleep(delay)
                    else:
                        log.error(
                            f"Max retries exceeded for {f.__name__}",
                            extra={
                                "max_retries": config.max_retries,
                                "error_type": classify_error(e).value,
                                "error": str(e)
                            },
                            exc_info=True
                        )
            
            # All retries exhausted
            raise last_error
        
        return wrapper
    
    # Support both @retry_with_backoff and @retry_with_backoff(...)
    if func is None:
        return decorator
    else:
        return decorator(func)


async def retry_with_backoff_async(
    func: Optional[Callable] = None,
    *,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_errors: Optional[List[Type[Exception]]] = None
):
    """
    Decorator for retrying async functions with exponential backoff.
    
    Args:
        func: Async function to decorate
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Exponential backoff base
        jitter: Add random jitter
        retryable_errors: List of exception types to retry
        
    Returns:
        Decorated async function
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        retryable_errors=retryable_errors or []
    )
    
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        async def wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(1, config.max_retries + 1):
                try:
                    return await f(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    
                    if not should_retry(e, attempt, config.max_retries):
                        log.debug(
                            f"Not retrying {type(e).__name__}: {str(e)}",
                            extra={"attempt": attempt, "error_type": classify_error(e).value}
                        )
                        raise
                    
                    if attempt < config.max_retries:
                        delay = calculate_delay(attempt, config)
                        error_type = classify_error(e)
                        
                        log.warning(
                            f"Retrying {f.__name__} after {delay:.2f}s (attempt {attempt}/{config.max_retries})",
                            extra={
                                "attempt": attempt,
                                "max_retries": config.max_retries,
                                "delay": delay,
                                "error_type": error_type.value,
                                "error": str(e)
                            }
                        )
                        
                        await asyncio.sleep(delay)
                    else:
                        log.error(
                            f"Max retries exceeded for {f.__name__}",
                            extra={
                                "max_retries": config.max_retries,
                                "error_type": classify_error(e).value,
                                "error": str(e)
                            },
                            exc_info=True
                        )
            
            # All retries exhausted
            raise last_error
        
        return wrapper
    
    # Support both @retry_with_backoff_async and @retry_with_backoff_async(...)
    if func is None:
        return decorator
    else:
        return decorator(func)


# Export
__all__ = [
    'ErrorType',
    'RetryConfig',
    'CircuitBreaker',
    'CircuitBreakerOpenError',
    'classify_error',
    'should_retry',
    'calculate_delay',
    'retry_with_backoff',
    'retry_with_backoff_async',
]

