'''
Application factory for Trendit³ API

It sets up and configures the Flask application, initializes various Flask extensions,
sets up CORS, configures logging, registers blueprints and defines additional app-wide settings.

@author Emmanuel Olowu
@link: https://github.com/zeddyemy
@package Trendit³
@Copyright © 2024 Emmanuel Olowu
'''

from flask import Flask, jsonify
from flask_swagger import swagger
from celery import Celery

from .models.role import create_roles
from .models.task_option import populate_task_options

from .celery import make_celery
from .extensions import db, mail, limiter, initialize_extensions
from .blueprints import register_all_blueprints
from .utils.helpers.loggers import log_exception, console_log
from .utils.hooks import register_hooks
from config import Config, configure_logging, config_by_name


def create_app(config_name=Config.ENV):
    '''
    Creates and configures the Flask application instance.

    Args:
        config_name: The configuration class to use (Defaults to Config).

    Returns:
        The Flask application instance.
    '''
    flask_app = Flask(__name__)
    flask_app.config.from_object(config_by_name[config_name])
    
    
    # Initialize Flask extensions here
    initialize_extensions(app=flask_app)

    # Register before and after request hooks
    register_hooks(flask_app)
    
    # Configure logging
    configure_logging(flask_app)
    
    # Register blueprints
    register_all_blueprints(flask_app)

    @flask_app.route('/spec')
    def spec():
        swag = swagger(flask_app)
        swag['info']['title'] = "Your API"
        swag['info']['description'] = "API documentation"
        swag['info']['version'] = "1.0.0"
        return jsonify(swag)
    
    
    # Initialize Celery and ensure tasks are imported
    celery = make_celery(flask_app)
    import app.celery.jobs.tasks # Ensure the tasks are imported
    celery.set_default()
    
    
    with flask_app.app_context():
        create_roles()  # Create roles for trendit3
        populate_task_options(clear=True)
    
    return flask_app, celery
