from flask import Flask
from threading import Thread
from flask import render_template, current_app
from flask_mail import Message
from enum import Enum

from app import mail
from config import Config
from ..helpers.loggers import console_log, log_exception
from ...models import Trendit3User


class EmailType(Enum):
    VERIFY_EMAIL = 'verify_email'
    PWD_RESET = 'pwd_reset'
    TWO_FA = '2FA'
    WELCOME = 'welcome'
    TASK_APPROVED = 'task_approved'
    TASK_REJECTED = 'task_rejected'
    CREDIT = 'credit'
    DEBIT = 'debit'

# SEND VERIFICATION CODE TO USER'S EMAIL
def send_payout_otp_async_email(app: Flask, code:int | str, code_type:str):
    """
    Sends an email asynchronously.

    This function runs in a separate thread and sends an email to Admin for payout confirmation. 
    It uses the Flask application context to ensure the mail object works correctly.

    Args:
        app (Flask): The Flask application instance.
        code (str): The six-digit code to include in the email.
        code_type (str): The type of the code ('verify_email', 'pwd_reset', '2FA').

    Returns:
        None
    """
    with app.app_context():
        email = "trendit3media@gmail.com"
        firstname = "Dave"
        
        subject = 'Payout confirmation OTP'
        template = render_template("mail/payout-otp.html", otp_code=code, name=firstname)
        msg = Message(subject, sender=Config.MAIL_ALIAS, recipients=[email], html=template)
        
        try:
            mail.send(msg)
        except Exception as e:
            console_log('EXCEPTION SENDING MAIL', f'An error occurred while sending the {code_type} code: {str(e)}')


def send_payout_otp_to_email(code, code_type='payout'):
    
    Thread(target=send_payout_otp_async_email, args=(current_app._get_current_object(), code, code_type)).start()

