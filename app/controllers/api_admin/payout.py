import pyotp
import requests
from decimal import Decimal
from datetime import timedelta
from flask import request, current_app
from jwt import ExpiredSignatureError
from jwt.exceptions import DecodeError
from flask_jwt_extended import create_access_token, decode_token
from sqlalchemy.exc import ( DataError, DatabaseError )

from ...extensions import db
from ...models import Trendit3User, Wallet, Transaction, Notification, TransactionType, NotificationType
from ...utils.helpers.response_helpers import error_response, success_response
from ...utils.helpers.basic_helpers import log_exception, console_log, generate_random_number, generate_random_string
from ...utils.payments.flutterwave import flutterwave_fetch_balance
from ...utils.payments.rates import convert_amount
from ...utils.helpers.user_helpers import get_trendit3_user
from ...utils.mailing.payout import send_payout_otp_to_email

class AdminPayoutController:
    @staticmethod
    def initiate_payout():
        try:
            data = request.get_json()
            email = data.get("email", "")
            amount = float(str(data.get("amount")).replace(",", ""))
            description = data.get("description", "A gift from Trendit³")
            
            if not email:
                return error_response("an email needs to be provided", 400)
            
            user = get_trendit3_user(email)
            
            if not user:
                return error_response("user not found", 404)
            
            # If the request comes from the bot, skip OTP. The OTP has been handled by the bot.
            bot_secret = request.headers.get("X-Bot-Secret")
            if bot_secret == current_app.config.get("BOT_SECRET_KEY"):
                
                user_wallet: Wallet = user.wallet
                user_wallet.balance += Decimal(amount)
                
                key = generate_random_string(16)
                transaction = Transaction.create_transaction(key=key, amount=amount, transaction_type=TransactionType.CREDIT, status="complete",description=description, trendit3_user=user, commit=False)
                
                currency_code = user_wallet.currency_code
                converted_amount = convert_amount(amount_in_naira=amount, target_currency=currency_code)
                Notification.add_notification(
                    recipient_id=user.id,
                    body=f"Congratulation! You have been credited with the sum of {currency_code} {converted_amount} to your Trendit³ wallet.",
                    notification_type=NotificationType.MESSAGE,
                    commit=False
                )
                
                db.session.commit()
                
                extra_data = {
                    "user_data": user.to_dict(),
                    "user_wallet": user_wallet.to_dict()
                }
                
                api_response = success_response("Payout made successfully", 200, extra_data)
            else:
                otp = generate_random_number(7)
                
                try:
                    send_payout_otp_to_email(otp)
                except Exception as e:
                    return error_response(f"An error occurred sending the OTP code", 500)
                
                identity={
                    "username": user.username,
                    "email": user.email,
                    "otp": otp,
                    "amount": amount,
                    "description": description
                }
                expires = timedelta(minutes=10)
                payout_token = create_access_token(identity=identity, expires_delta=expires, additional_claims={"type": "payout"})
                extra_data = {"payout_token": payout_token}
                
                api_response = success_response("An OTP has been sent to Admin for confirmation", 200, extra_data)
        except requests.exceptions.RequestException as e:
            log_exception("A RequestException occurred fetching flutterwave balance", e)
            api_response = error_response("Error connecting to payment gateway", 500)
        except (DataError, DatabaseError) as e:
            db.session.rollback()
            log_exception(f"An exception occurred during database operation:", e)
            api_response = error_response("Error interacting with the database.", 500)
        except Exception as e:
            db.session.rollback()
            log_exception(f"An unexpected exception occurred initiating payout", e)
            api_response = error_response("An unexpected error. Our developers are already looking into it.", 500)
        
        return api_response
    
    
    @staticmethod
    def verify_payout_otp():
        try:
            data = request.get_json()
            payout_token = data.get("payout_token")
            entered_code = data.get("entered_code")
            
            try:
                # Decode the JWT and extract the user's info and the 2FA code
                decoded_token = decode_token(payout_token)
                token_data = decoded_token["sub"]
            except ExpiredSignatureError as e:
                log_exception("The OTP code has expired. Please try again.", e)
                return error_response("The OTP code has expired. Please try again.", 401)
            except Exception as e:
                log_exception("An Exception occurred verifying 2fa", e)
                return error_response(f"An unexpected error occurred: {str(e)}.", 500)
            
            if not decoded_token:
                return error_response("Invalid or expired OTP code", 401)
            
            user = get_trendit3_user(token_data["username"])
            if not user:
                return error_response("user not found", 404)
            
            
            amount = token_data["amount"]
            description = token_data["description"]
            
            
            # Check if the entered code matches the one in the JWT
            if int(entered_code) != int(token_data["otp"]):
                return error_response("The wrong OTP was provided. Please check your mail for the correct code and try again.", 400)
            
            # 2FA token is valid, log user in.
            # User authentication successful
            user_wallet: Wallet = user.wallet
            user_wallet.balance += Decimal(amount)
                
            key = generate_random_string(16)
            transaction = Transaction.create_transaction(key=key, amount=amount, transaction_type=TransactionType.CREDIT, status="complete",description=description, trendit3_user=user, commit=False)
            
            currency_code = user_wallet.currency_code
            converted_amount = convert_amount(amount_in_naira=amount, target_currency=currency_code)
            Notification.add_notification(
                recipient_id=user.id,
                body=f"Congratulation! You have been credited with the sum of {currency_code} {converted_amount} to your Trendit³ wallet.",
                notification_type=NotificationType.MESSAGE,
                commit=False
            )
            
            db.session.commit()
            
            extra_data = {
                "user_data": user.to_dict(),
                "user_wallet": user_wallet.to_dict()
            }
            
            api_response = success_response("Payout made successfully", 200, extra_data)
        except (DataError, DatabaseError) as e:
            db.session.rollback()
            log_exception("Database error", e)
            return error_response("Error interacting with the database.", 500)
        except Exception as e:
            db.session.rollback()
            log_exception("An exception occurred trying to verify OTP:", e)
            return error_response("An unexpected error. Our developers are already looking into it.", 500)
        
        return api_response
