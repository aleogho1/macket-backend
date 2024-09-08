'''
This module contains the function to register all blueprints in defined for the Flask application.

@author: Emmanuel Olowu
@link: https://github.com/zeddyemy
@package: Trendit³
'''

from flask import Flask

def register_all_blueprints(app: Flask) -> None:
    
    from .routes.main import main_bp
    app.register_blueprint(main_bp)
    
    from .routes.api import api as api_bp
    app.register_blueprint(api_bp)
    
    from .routes.api_admin import bp as api_admin_bp
    app.register_blueprint(api_admin_bp)
    
    from .routes.telegram import telegram_bp
    app.register_blueprint(telegram_bp)
    
    from .routes.mail import mail_bp
    app.register_blueprint(mail_bp)
    
    from .error_handlers import bp as errorHandler_bp
    app.register_blueprint(errorHandler_bp)
    
    from .utils.debugging import debugger as debugger_bp
    app.register_blueprint(debugger_bp)
    
    # Swagger setup
    from flask_swagger_ui import get_swaggerui_blueprint

    SWAGGER_URL = '/api/docs'
    API_URL = 'http://petstore.swagger.io/v2/swagger.json'
    swaggerui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL,
        API_URL,
        config={
            'app_name': "Trendit³ API"
        }
    )
    app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)
