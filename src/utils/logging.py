import logging
from rich.logging import RichHandler
from rich.console import Console
from loguru import logger

console = Console()
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[RichHandler(
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        markup=True,
    )],
)
console = Console()

logger.remove()
logger.add(
    RichHandler(
        show_time=True,
        show_path=True,
        rich_tracebacks=True,
        markup=True,
    ),
    format="{message}",
)
