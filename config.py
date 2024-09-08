'''
This module defines the configuration settings for the Trendit³ Flask application.

It includes configurations for the environment, database, JWT, Paystack, mail, Cloudinary, and Celery. 
It also includes a function to configure logging for the application.

@author: Emmanuel Olowu
@link: https://github.com/zeddyemy
@package: Trendit³
'''
import os, logging
from flask import Flask
from datetime import timedelta
from typing import Final
from celery import Celery



class Config:
    # other app configurations
    ENV = os.environ.get("ENV") or "development"
    SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(32)
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "postgresql://postgres:zeddy@localhost:5432/trendit3"
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = (ENV == "development")  # Enable debug mode only in development
    STATIC_DIR = "app/static"
    UPLOADS_DIR = "app/static/uploads"
    EMERGENCY_MODE = os.environ.get("EMERGENCY_MODE") or False
    SUPPORT_EMAIL: Final = "support@trendit3.com"
    HELP_EMAIL: Final = "help@trendit3.com"
    DOMAIN_NAME = os.environ.get("DOMAIN_NAME") or "https://www.trendit3.com"
    
    APP_DOMAIN_NAME = os.environ.get("APP_DOMAIN_NAME") or "https://app.trendit3.com"
    API_DOMAIN_NAME = os.environ.get("API_DOMAIN_NAME") or "https://api.trendit3.com"
    CLIENT_ORIGINS = os.environ.get("CLIENT_ORIGINS") or "http://localhost:3000,http://localhost:5173,https://trendit3.vercel.app"
    CLIENT_ORIGINS = [origin.strip() for origin in CLIENT_ORIGINS.split(",")]
    REDIS_URL = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"
    
    # Telegram variables
    BOT_SECRET_KEY: Final = os.environ.get("BOT_SECRET_KEY")
    TELEGRAM_BOT_TOKEN: Final = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: Final = os.environ.get("TELEGRAM_CHAT_ID")
    TELEGRAM_SEND_MSG_URL: Final = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    APP_BOT_PASSWORD: Final = os.environ.get("APP_BOT_USERNAME")
    APP_BOT_PASSWORD: Final = os.environ.get("APP_BOT_PASSWORD")
    
    # Constants
    TASKS_PER_PAGE: Final = os.environ.get("TASKS_PER_PAGE") or 10
    ITEMS_PER_PAGE: Final = os.environ.get("ITEMS_PER_PAGE") or 10
    PAYMENT_TYPES: Final = ["task-creation", "membership-fee", "credit-wallet", "item-upload"]
    
    # JWT configurations
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=30)
    
    
    PAYMENT_GATEWAY = os.environ.get("PAYMENT_GATEWAY")
    # Paystack Configurations
    PAYSTACK_API_URL = "https://api.paystack.co"
    PAYSTACK_INITIALIZE_URL = "https://api.paystack.co/transaction/initialize"
    PAYSTACK_RECIPIENT_URL = "https://api.paystack.co/transferrecipient"
    PAYSTACK_TRANSFER_URL = "https://api.paystack.co/transfer"
    PAYSTACK_COUNTIES_URL = "https://api.paystack.co/country"
    PAYSTACK_STATES_URL = "https://api.paystack.co/address_verification/states"
    PAYSTACK_BANKS_URL = "https://api.paystack.co/bank"
    PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY")
    PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY")
    
    # Flutterwave Configurations
    FLW_INITIALIZE_URL = "https://api.flutterwave.com/v3/payments"
    FLW_BANKS_URL = "https://api.flutterwave.com/v3/banks"
    FLW_TRANSFER_URL = "https://api.flutterwave.com/v3/transfers"
    FLW_VERIFY_BANK_ACCOUNT_URL = "https://api.flutterwave.com/v3/accounts/resolve"
    FLW_SECRET_KEY = os.environ.get("FLW_SECRET_KEY")
    FLW_PUBLIC_KEY = os.environ.get("FLW_PUBLIC_KEY")
    FLW_SECRET_HASH = os.environ.get("FLW_SECRET_HASH")
    
    
    # mail configurations
    MAIL_SERVER = os.environ.get("MAIL_SERVER") or "smtp.gmail.com"
    MAIL_PORT = os.environ.get("MAIL_PORT") or 587
    MAIL_USE_SSL = False
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER")
    MAIL_ALIAS = (f"{MAIL_DEFAULT_SENDER}", f"{MAIL_USERNAME}")
    
    # Cloudinary configurations
    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")
    
    # Celery
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
    CELERY_CONFIG = {"broker_url": CELERY_BROKER_URL, "result_backend": CELERY_RESULT_BACKEND}
    CELERY_ACCEPT_CONTENT = ["application/json"]
    CELERY_TASK_SERIALIZER = "json"
    CELERY_RESULT_SERIALIZER = "json"
    
    #  ExchangeRate-API
    EXCHANGE_RATE_API_KEY = os.environ.get("EXCHANGE_RATE_API_KEY")
    EXCHANGE_RATE_API_URL = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_API_KEY}/latest"
    
    # Rate limit
    RATELIMIT_STORAGE_URI = REDIS_URL
    RATELIMIT_STORAGE_OPTIONS = os.environ.get("RATELIMIT_STORAGE_OPTIONS") or {}


    # Google config
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    # Facebook config
    FB_CLIENT_ID = os.environ.get("FB_CLIENT_ID")
    FB_CLIENT_SECRET = os.environ.get("FB_CLIENT_SECRET")

    # TikTok config


class StagingConfig(Config):
    DEBUG = True
    FLASK_DEBUG = True
    DEBUG_TOOLBAR = True  # Enable debug toolbar
    EXPOSE_DEBUG_SERVER = False  # Do not expose debugger publicly
    
    APP_DOMAIN_NAME = os.environ.get("APP_DOMAIN_NAME") or "https://staging.trendit3.com"
    API_DOMAIN_NAME = os.environ.get("API_DOMAIN_NAME") or "https://api-staging.trendit3.com"

class DevelopmentConfig(Config):
    FLASK_DEBUG = True
    DEBUG_TOOLBAR = True  # Enable debug toolbar
    EXPOSE_DEBUG_SERVER = False  # Do not expose debugger publicly
    
    APP_DOMAIN_NAME = os.environ.get("APP_DOMAIN_NAME") or "https://staging.trendit3.com"
    API_DOMAIN_NAME = os.environ.get("API_DOMAIN_NAME") or "http://127.0.0.1:5000"

class ProductionConfig(Config):
    DEBUG = True
    FLASK_DEBUG = False
    DEBUG_TOOLBAR = False
    EXPOSE_DEBUG_SERVER = False
    
    APP_DOMAIN_NAME = os.environ.get("APP_DOMAIN_NAME") or "https://app.trendit3.com"
    API_DOMAIN_NAME = os.environ.get("API_DOMAIN_NAME") or "https://api.trendit3.com"

# Map config based on environment
config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "staging": StagingConfig
}

config_class = DevelopmentConfig if Config.ENV == "development" else (
    StagingConfig if Config.ENV == "staging" else ProductionConfig
)

def configure_logging(app: Flask) -> None:
    if not app.logger.handlers:
        formatter = logging.Formatter("[%(asctime)s] ==> %(levelname)s in %(module)s: %(message)s")
        
        # Stream handler
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        app.logger.addHandler(stream_handler)
        
        app.logger.setLevel(logging.INFO)  # Set the desired logging level