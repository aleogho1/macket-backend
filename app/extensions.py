'''
This module initializes the extensions used in the Trendit³ Flask application.

It sets up SQLAlchemy, Flask-Mail, and Celery with the configurations defined in the Config class.

@author: Emmanuel Olowu
@link: https://github.com/zeddyemy
@package: Trendit³
'''
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from flask_limiter import Limiter
from flask_migrate import Migrate
from flask_limiter.util import get_remote_address
from flask_jwt_extended import JWTManager
from flask_cors import CORS

from config import Config

db = SQLAlchemy()
mail = Mail()
cors = CORS()
migration = Migrate()
jwt_extended = JWTManager()
limiter = Limiter(key_func=get_remote_address)

def initialize_extensions(app: Flask):
    db.init_app(app)
    mail.init_app(app)
    limiter.init_app(app) # initialize rate limiter
    migration.init_app(app, db=db)
    jwt_extended.init_app(app)
    
    # Set up CORS. Allow '*' for origins.
    cors.init_app(app=app, resources={r"/*": {"origins": Config.CLIENT_ORIGINS}}, supports_credentials=True)