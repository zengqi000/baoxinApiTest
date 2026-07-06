import logging
import os
from datetime import datetime


def setup_logger(name='api_test', log_dir='logs'):
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, f'{name}_{datetime.now().strftime("%Y-%m-%d")}.log')
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    if logger.handlers:
        logger.handlers.clear()
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s'
    )
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def get_logger(name='api_test'):
    return logging.getLogger(name)
