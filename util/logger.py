import os
import logging
from rich.logging import RichHandler
from datetime import datetime

# Ensure logs directory exists
log_dir = os.getenv("LOG_FOLDER_PATH", "logs")
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Generate a unique log file name
now = datetime.now()
log_filename = os.path.join(log_dir, f"npf_{now.strftime('%Y-%m-%d_%H%M%S')}.log")

# Configure file handler
file_handler = logging.FileHandler(log_filename)
file_handler.setLevel(logging.DEBUG)  # Log everything to the file

# Configure formatter for file logs
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

# Configure root logger
logger = logging.getLogger()
logger.addHandler(RichHandler())  # Rich for console
logger.addHandler(file_handler)  # File for persistent logs
logger.propagate = True

# Set log level based on environment variable
if os.getenv("DEBUG", "0") == "1":
    logger.setLevel(logging.DEBUG)
    logger.debug("Log level set to DEBUG='1'")
else:
    logger.setLevel(logging.INFO)