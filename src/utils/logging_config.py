"""Structured logging configuration for the RAG system."""
import sys
import logging
from pathlib import Path
from typing import Any, Dict
from loguru import logger
try:
    from app.config import settings
except ImportError:
    # Fallback for when config is not available
    class Settings:
        log_level = "INFO"
        log_file = None
        json_logs = False
        structured_logging = True
    settings = Settings()


class InterceptHandler(logging.Handler):
    """Intercept standard logging messages toward loguru."""

    def __init__(self, level: str = "INFO"):
        super().__init__()
        # Convert string level to logging level constant
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL
        }
        self.setLevel(level_map.get(level.upper(), logging.INFO))
        self.level_name = level

    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = self.level_name

        # Find caller from where originated the logged message
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(
    log_level: str = None,
    log_file: str = None,
    json_logs: bool = False,
    structured: bool = True
):
    """
    Setup structured logging with loguru.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        json_logs: Whether to output logs in JSON format
        structured: Whether to use structured logging format
    """
    # Remove default handler
    logger.remove()
    
    # Get log level from settings or use default
    level = log_level or getattr(settings, 'log_level', 'INFO').upper()
    
    # Format for structured logging
    if json_logs:
        # JSON format for log aggregation
        # Use serialize=True instead of custom format for JSON
        format_string = None  # Will use serialize=True
    elif structured:
        # Structured text format (human-readable)
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )
    else:
        # Simple format
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        )
    
    # Console handler
    logger.add(
        sys.stdout,
        format=format_string if not json_logs else None,
        level=level,
        colorize=not json_logs,
        serialize=json_logs,  # When True, outputs JSON automatically
        backtrace=True,
        diagnose=True,
    )
    
    # File handler (if specified)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.add(
            log_file,
            format=format_string,
            level=level,
            serialize=json_logs,
            rotation="10 MB",
            retention="7 days",
            compression="zip",
            backtrace=True,
            diagnose=True,
        )
    
    # Intercept standard logging
    import logging
    logging.basicConfig(handlers=[InterceptHandler(level)], level=0, force=True)
    
    return logger


def get_logger(name: str = None):
    """
    Get a logger instance with optional name.
    
    Args:
        name: Optional logger name (module name)
        
    Returns:
        Logger instance
    """
    if name:
        return logger.bind(name=name)
    return logger


# Initialize logging on module import
_log_level = getattr(settings, 'log_level', 'INFO')
_log_file = getattr(settings, 'log_file', None)
_json_logs = getattr(settings, 'json_logs', False)
_structured = getattr(settings, 'structured_logging', True)

setup_logging(
    log_level=_log_level,
    log_file=_log_file,
    json_logs=_json_logs,
    structured=_structured
)

# Export logger
__all__ = ['logger', 'get_logger', 'setup_logging']

