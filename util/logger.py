import os
import logging
from rich.logging import RichHandler

# Configure root logger with RichHandler for ALL libraries
logger = logging.getLogger()
logger.addHandler(RichHandler())
logger.propagate = True  # Ensure messages are propagated to the root logger

if os.getenv("DEBUG", "0") == "1":
    logger.setLevel(logging.DEBUG)
    logger.debug("Log level set to DEBUG='1'")
else:
    logger.setLevel(logging.INFO)