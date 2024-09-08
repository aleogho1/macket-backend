from decimal import Decimal
import logging, requests, hmac, hashlib
from flask import request, jsonify, json
from sqlalchemy.exc import ( DataError, DatabaseError )
from flask_jwt_extended import get_jwt_identity

from ...extensions import db
from ...models import (Trendit3User, BankAccount, Recipient, Payment, Transaction, Withdrawal, TaskPaymentStatus)
from ...utils.helpers.response_helpers import error_response, success_response
from ...utils.helpers.loggers import console_log, log_exception
from ...utils.helpers.bank_helpers import get_bank_code
from ...utils.helpers.task_helpers import get_task_by_key
from ...utils.helpers.mail_helpers import send_other_emails
from ...utils.helpers.telegram_bot import notify_telegram_admins_new_withdraw

# import payment modules
from ...utils.payments.utils import initialize_payment
from ...utils.payments.flutterwave import verify_flutterwave_payment, flutterwave_webhook, flutterwave_initiate_transfer
from ...utils.payments.exceptions import TransactionMissingError, CreditWalletError, SignatureError, FlutterwaveError
from config import Config

class PaymentController:
    @staticmethod
    def process_payment(payment_type):
        """
        Processes a payment for a user.

        This function extracts payment information from the request, checks if the user exists and if the payment has already been made. If the user exists and the payment has not been made, it initializes a transaction with Paystack. If the transaction initialization is successful, it returns a success response with the authorization URL. If an error occurs at any point, it returns an error response with an appropriate status code and message.

        Returns:
            json, int: A JSON object containing the status of the payment, a status code, and a message (and an authorization URL in case of success), and an HTTP status code.
        """
        
        data = request.get_json()
        callback_url = request.headers.get('CALLBACK-URL')
        if not callback_url:
            return error_response('callback URL not provided in the request headers', 400)
        data['callback_url'] = callback_url # add callback url to data
        
        user_id = int(get_jwt_identity())

        return initialize_payment(user_id, data, payment_type)


    @staticmethod
    def verify_payment():
        """
        Verifies a payment for a user using the Paystack API.

        This function extracts the transaction ID from the request, verifies the transaction with FlutterWave, and checks if the verification was successful. If the verification was successful, it updates the user's membership status in the database, records the payment in the database, and returns a success response with the payment details. If an error occurs at any point, it returns an error response with an appropriate status code and message.

        Returns:
            json, int: A JSON object containing the status of the verification, a status code, a message (and payment details in case of success), and an HTTP status code.
        """
        
        try:
            # Extract body from request
            data = request.get_json()
            
            current_user_id = get_jwt_identity()
            
            result = verify_flutterwave_payment(data)
            
            msg = result['msg']
            extra_data = result['extra_data']
            
            if result['success']:
                api_response = success_response(msg, 200, extra_data)
            else:
                api_response = error_response(msg, 500, extra_data)
            
        except (DataError, DatabaseError) as e:
            db.session.rollback()
            log_exception('Database error occurred during payment verification', e)
            return error_response('Error interacting to the database.', 500)
        except TransactionMissingError as e:
            db.session.rollback()
            return error_response(f'{e}', 500)
        except CreditWalletError as e:
            db.session.rollback()
            return error_response(f'{e}', 500)
        except Exception as e:
            db.session.rollback()
            logging.exception(f"An exception occurred during payment verification {str(e)}")
            return error_response('An unexpected error. Our developers are already looking into it.', 500)
        finally:
            db.session.close()
        
        return api_response


    @staticmethod
    def handle_webhook():
        """
        Handles a webhook for a payment.

        This function verifies the signature of the webhook request, checks if the event is a successful payment event, and if so, updates the user's membership status in the database and records the payment in the database. If an error occurs at any point, it returns an error response with an appropriate status code and message.

        Returns:
            json, int: A JSON object containing the status of the webhook handling, and an HTTP status code.
        """
        try:
            result = flutterwave_webhook()
            
            if result['success']:
                return jsonify({'status': 'success'}), result['status_code']
            else:
                return jsonify({'status': 'failed'}), result['status_code']
        except SignatureError as e:
            db.session.rollback()
            log_exception(f"An exception occurred Handling webhook", e)
        except ValueError as e:
            db.session.rollback()
            log_exception(f"An exception occurred", e)
        except (DataError, DatabaseError) as e:
            db.session.rollback()
            log_exception(f"error connecting to the database", e)
        except Exception as e:
            db.session.rollback()
            log_exception("An exception occurred Handling webhook", e)
            return jsonify({'status': 'failed'}), 500


    @staticmethod
    def get_payment_history():
        """
        Fetches the payment history for a user.

        This function extracts the current_user_id from the jwt identity, checks if the user exists, and if so, fetches the user's payment history from the database and returns it. If an error occurs at any point, it returns an error response with an appropriate status code and message.

        Returns:
            json, int: A JSON object containing the status of the request, a status code, a message (and payment history in case of success), and an HTTP status code.
        """
        
        try:
            current_user_id = int(get_jwt_identity())
            page = request.args.get("page", 1, type=int)
            items_per_page = request.args.get("per_page", 15, type=int)
            
            # Check if user exists
            user = Trendit3User.query.get(current_user_id)
            if user is None:
                return error_response('User not found', 404)
            
            # Fetch payment records from the database
            pagination = Payment.query.filter_by(trendit3_user_id=current_user_id) \
                .order_by(Payment.created_at.desc()) \
                .paginate(page=page, per_page=items_per_page, error_out=False)
            
            payments = pagination.items
            current_payments = [payment.to_dict() for payment in payments]
            extra_data = {
                'total': pagination.total,
                "current_page": pagination.page,
                "total_pages": pagination.pages,
                "payment_history": current_payments,
            }
            
            if not payments:
                return success_response(f'No payments has been made', 200, extra_data)
            
            return success_response('Payment history fetched successfully', 200, extra_data)
        except Exception as e:
            logging.exception(f"An exception occurred during fetching payment history. {str(e)}") # Log the error details for debugging
            return error_response('An unexpected error. Our developers are already looking into it.', 500)


    @staticmethod
    def withdraw():
        """
        Process for users to Withdraw money into their bank accounts.

        Returns:
            json: A JSON object containing the status of the withdrawal, a status code, and a message.
        """
        try:
            current_user_id = int(get_jwt_identity())
            user: Trendit3User = Trendit3User.query.get(current_user_id)
            
            data = request.get_json()
            amount = int(str(data.get('amount')).replace(',', ''))
            if amount < 1000:
                return error_response("Invalid withdrawal amount", 400)
            
            fee_percentage = Decimal('0.015')  # Represents 1.5% as a decimal
            fee = amount * fee_percentage
            
            # Check if the user has enough balance to cover both the amount and the fee
            if user.wallet_balance < (amount + fee):
                return error_response("Insufficient balance to cover the amount and the fee", 400)
            
            name = user.profile.firstname
            is_primary = data.get('is_primary', True)
            bank_name = data.get('bank_name', '')
            account_no = data.get('account_no', '')
            bank_code = get_bank_code(bank_name) if bank_name else ''
            currency = user.wallet.currency_code
            
            if is_primary:
                bank = BankAccount.query.filter_by(trendit3_user_id=user.id, is_primary=True).first()
                if not bank:
                    return error_response("You have not added your account details. please update your bank account before placing withdrawals of your funds. Go to settings to add your primary bank account", 404)
            else:
                bank = BankAccount.add_bank(trendit3_user=user, bank_name=bank_name, bank_code=bank_code, account_no=account_no, is_primary=False, account_name=name)
            
            transfer_info = flutterwave_initiate_transfer(bank, amount, currency, user)
            
            
            msg = f"{amount} {currency} is on it's way to {bank.account_name}"
            extra_data = {
                "withdrawal_info": transfer_info
            }
            
            api_response = success_response(msg, 200, extra_data)
        except FlutterwaveError as e:
            log_exception("An exception occurred processing the withdrawal request", e)
            db.session.rollback()
            api_response = error_response(f"Flutterwave error: {e}", 500)
        except Exception as e:
            log_exception("An exception occurred processing the withdrawal request", e)
            db.session.rollback()
            api_response = error_response('An unexpected error. Our developers are already looking into it.', 500)
        
        return api_response


    @staticmethod
    def verify_withdraw():
        try:
            current_user_id = get_jwt_identity()
            user: Trendit3User = Trendit3User.query.get(current_user_id)
            user_wallet = user.wallet
            
            data = request.get_json()
            transfer_id = data.get('transfer_id', '')
            reference = data.get('reference', '')
            if not reference:
                return error_response("reference key is required in request's body", 401)
            
            url = f"https://api.flutterwave.com/v3/transfers/{transfer_id}"
            headers = {
                "Authorization": f"Bearer {Config.FLW_SECRET_KEY}",
                "Content-Type": "application/json"
            }
            flw_response = requests.get(url, headers=headers)
            verification_response = flw_response.json()
            
            console_log("response data", verification_response)
            
            if verification_response['status'] != "success":
                return error_response(verification_response['message'], 401)
            
            # Extract needed data
            amount = Decimal(verification_response['data']['amount'])
            fee_percentage = Decimal('0.015')  # Represents 1.5% as a decimal
            fee = amount * fee_percentage
            transfer_status = verification_response['data']['status']
            
            transaction = Transaction.query.filter_by(key=reference).first()
            withdrawal = Withdrawal.query.filter_by(reference=reference).first()
            
            if not transaction:
                return error_response('transaction not found', 404)
            
            if not withdrawal:
                return error_response('withdrawal not found', 404)
            
            extra_data = {'withdrawal_status': transfer_status}
            
            # if verification was successful
            if transfer_status == "SUCCESSFUL":
                msg = f"Withdrawal was successful"
                
                if transaction.status.lower() != 'complete':
                    with db.session.begin_nested():
                        withdrawal.status=transfer_status  # Update withdrawal status
                        transaction.status="complete"  # Update transaction status
                        db.session.commit()
                    
                    extra_data.update({'withdrawal_info': withdrawal.to_dict()})
                elif transaction.status.lower() == 'complete':
                    extra_data.update({'withdrawal_info': withdrawal.to_dict()})
                
                api_response = success_response(msg, 200, extra_data)
                notify_telegram_admins_new_withdraw(withdrawal)
            elif transfer_status == "PENDING":
                # withdrawal was not successful
                msg = f"Your withdrawal request is being processed"
                with db.session.begin_nested():
                    transaction.status="pending"  # Update transaction status
                    withdrawal.status=transfer_status  # Update withdrawal status
                    db.session.commit()
                
                extra_data.update({'withdrawal_info': withdrawal.to_dict()})
                api_response = success_response(msg, 200, extra_data)
            elif transfer_status == "FAILED":
                # withdrawal was not successful
                msg = f"Withdrawal was not successful. Please try again."
                if transaction.status.lower() != 'failed':
                    with db.session.begin_nested():
                        transaction.status="failed"  # Update transaction status
                        withdrawal.status=transfer_status  # Update withdrawal status
                        user_wallet.balance += (amount + fee) # reverse amount to users the wallet
                        db.session.commit()
                    
                    msg = f"Withdrawal was not successful. Please try again."
                    extra_data.update({'withdrawal_info': withdrawal.to_dict()})
                
                api_response = success_response(msg, 400, extra_data)
            else:
                msg = f"Withdrawal was not successful. Please try again."
                if transaction.status.lower() != transfer_status.lower():
                    with db.session.begin_nested():
                        transaction.status=transfer_status.lower()  # Update transaction status
                        withdrawal.status=transfer_status  # Update withdrawal status
                        db.session.commit()
                        extra_data.update({'withdrawal_info': withdrawal.to_dict()})
                        
                api_response = success_response(msg, 400, extra_data)
        
        except ValueError as e:
            log_exception(f"A ValueError occurred during withdrawal verification", e)
            api_response = error_response("Invalid data provided", 400)
        except requests.exceptions.RequestException as e:
            log_exception(f"A RequestException occurred during withdrawal verification", e)
            api_response = error_response("Error connecting to payment gateway", 500)
        except (DataError, DatabaseError) as e:
            log_exception(f"An exception occurred during database operation", e)
            api_response = error_response("Database error occurred", 500)
        except Exception as e:
            log_exception(f"An unexpected exception occurred during withdrawal verification", e)
            api_response = error_response('An unexpected error. Our developers are already looking into it.', 500)
        finally:
            db.session.close()
        
        return api_response


    @staticmethod
    def withdraw_approval_webhook():
        try:
            data = request.get_json()
            console_log('DATA', data)
            data = json.loads(request.data) # Get the data from the request
            console_log('DATA', data)
            
            secret_hash = Config.FLW_SECRET_HASH
            signature = request.headers.get('verif-hash') # Get the signature from the request headers
            
            console_log('secret_hash', secret_hash)
            console_log('signature', signature)
            
            if signature == None or (signature != secret_hash):
                # This request isn't from Flutterwave; discard
                raise SignatureError(f'No signature in headers')
            
            # Extract needed data
            reference = data['data']['reference']
            amount = Decimal(data['data']['amount'])
            fee_percentage = Decimal('0.015')  # Represents 1.5% as a decimal
            fee = amount * fee_percentage
            transfer_status = data['data']['status']
            
            transaction: Transaction = Transaction.query.filter_by(key=reference).first()
            withdrawal: Withdrawal = Withdrawal.query.filter_by(reference=reference).first()
            
            user: Trendit3User = transaction.trendit3_user
            user_wallet = user.wallet
            
            if not transaction:
                return error_response('transaction not found', 404)
            
            if not withdrawal:
                return error_response('withdrawal not found', 404)
            
            # if verification was successful
            if transfer_status == "SUCCESSFUL":
                if transaction.status.lower() != 'complete':
                    with db.session.begin_nested():
                        withdrawal.status=transfer_status  # Update withdrawal status
                        transaction.status="complete"  # Update transaction status
                        db.session.commit()
                
                notify_telegram_admins_new_withdraw(withdrawal)
                return jsonify(message='Transfer approved'), 200 # Respond with a 200 OK if details are authentic
            
            elif transfer_status == "PENDING":
                # withdrawal was not successful
                with db.session.begin_nested():
                    transaction.status="pending"  # Update transaction status
                    withdrawal.status=transfer_status  # Update withdrawal status
                    db.session.commit()
                
                return jsonify(error='transfer pending'), 400
            elif transfer_status == "FAILED":
                # withdrawal was not successful
                if transaction.status.lower() != 'failed':
                    with db.session.begin_nested():
                        transaction.status="failed"  # Update transaction status
                        withdrawal.status=transfer_status  # Update withdrawal status
                        user_wallet.balance += (amount + fee) # reverse amount to users the wallet
                        db.session.commit()
            else:
                if transaction.status.lower() != transfer_status.lower():
                    with db.session.begin_nested():
                        transaction.status=transfer_status.lower()  # Update transaction status
                        withdrawal.status=transfer_status  # Update withdrawal status
                        db.session.commit()
                
                return jsonify(error='Transfer Failed'), 400
        
        except Exception as e:
            log_exception("Withdraw Webhook Exception", e)
            return jsonify(error='Internal Server Error'), 500
        finally:
            db.session.close()


    @staticmethod
    def show_balance():
        """
        This function returns the user balance.
        
        @al-chris
        """
        try:
            current_user_id = int(get_jwt_identity())
            user = Trendit3User.query.get(current_user_id)
            user_wallet = user.wallet
            
            user_wallet_dict = user_wallet.to_dict()
            user_wallet_dict.pop("id")
            user_wallet_dict.pop("user_id")

            extra_data = user_wallet_dict

            return success_response(f'Balanced fetched successfully', 200, extra_data)
        
        except Exception as e:
            logging.exception(f"An exception occurred while fetching user's wallet balance: {str(e)}")
            return error_response('An unexpected error. Our developers are already looking into it.', 500)