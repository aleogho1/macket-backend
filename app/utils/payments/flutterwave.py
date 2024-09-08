"""
@author: Emmanuel Olowu
@link: https://github.com/zeddyemy
@package: Trendit³
"""

from decimal import Decimal
import requests, hmac, hashlib
from flask import json, request
from sqlalchemy.exc import ( DataError, DatabaseError )

from ...extensions import db
from ...models import Payment, Transaction, TransactionType, Withdrawal, Trendit3User, TaskPaymentStatus, BankAccount
from ..helpers.loggers import console_log, log_exception
from ..helpers.basic_helpers import generate_random_string
from ..helpers.task_helpers import get_task_by_key
from ..helpers.mail_helpers import send_other_emails
from ..helpers.telegram_bot import notify_telegram_admins_new_task
from ..helpers.user_helpers import update_membership_payment
from ..mailing import send_task_order_review_email
from .exceptions import TransactionMissingError, CreditWalletError, SignatureError, FlutterwaveError
from .wallet import credit_wallet
from .paystack import headers as paystack_headers
from config import Config



headers ={
    "Authorization": "Bearer {}".format(Config.FLW_SECRET_KEY ),
    "Content-Type": "application/json"
}

def initialize_flutterwave_payment(amount: int, payload: dict, payment_type: str, user: Trendit3User):
    try:
        
        response = requests.post(Config.FLW_INITIALIZE_URL, headers=headers, json=payload)
        status_code = int(response.status_code)
        console_log("response", response)
        
        response_data = response.json()
        console_log("response_data", response_data)
        console_log("ref", payload["tx_ref"])
        
        if "status" in response_data:
            if response_data["status"] == "success":
                tx_ref=payload["tx_ref"] # transaction reference
                transaction = Transaction(key=tx_ref, amount=amount, transaction_type=TransactionType.PAYMENT, description=f"{payment_type} payment", status="pending", trendit3_user=user)
                payment = Payment(key=tx_ref, amount=amount, payment_type=payment_type, payment_method=Config.PAYMENT_GATEWAY.lower(),status="pending", trendit3_user=user)
                db.session.add_all([transaction, payment])
                db.session.commit()
                
                authorization_url = response_data["data"]["link"] # Get authorization URL from response
                msg = "Payment initialized"
                success = True
                extra_data = {
                    "authorization_url": authorization_url,
                    "payment_type": payment_type,
                    "metadata": payload["meta"],
                    "status_code": status_code
                }
            else:
                msg = "Payment initialization failed"
                success = False
                response_data.update({"metadata": payload["meta"], "status_code": status_code})
                extra_data = response_data
        else:
            msg = "Payment initialization failed"
            success = False
            removed_message = response_data.pop("message") if "message" in response_data else ""
            extra_data = response_data
        
        console_log("extra_data", extra_data)
        result = {
            "msg": msg,
            "success": success,
            "extra_data": extra_data
        }
    except (DataError, DatabaseError) as e:
        raise e
    except Exception as e:
        raise e
    
    return result


def verify_flutterwave_payment(data):
    """ Verify payment with flutterwave"""
    
    try:
        reference = data.get("reference") # Extract reference from request body
        transaction_id = data.get("transaction_id") # Extract reference from request body
        
        flutterwave_response = requests.get(f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify", headers=headers)
        status_code = int(flutterwave_response.status_code)
        response_data = flutterwave_response.json()
        
        console_log("response_data", response_data)
        
        if "status" in response_data and response_data["data"]:
            # Extract needed data
            msg = ""
            payment_status = response_data["data"]["status"].lower()
            extra_data = {"payment_status": payment_status}
            
            transaction: Transaction = Transaction.query.filter_by(key=reference).first()
            payment: Payment = Payment.query.filter_by(key=reference).first()
            
            if not transaction:
                raise TransactionMissingError
            
            user_id = transaction.trendit3_user_id
            trendit3_user = transaction.trendit3_user
            payment_type = payment.payment_type
            extra_data.update({"payment_type": payment_type})
            
            # if verification was successful and payment was successful
            if response_data["status"] == "success" and payment_status == "successful":
                amount = float(response_data["data"]["amount"])
                currency = response_data["data"]["currency"]
                msg = f"Payment verified successfully"
                
                if transaction.status.lower() != "complete":
                    # Record the payment and transaction in the database
                    with db.session.begin_nested():
                        transaction.status = "complete"
                        payment.status = "complete"
                        db.session.commit()
                        
                    # Update user"s membership status in the database
                    if payment_type == "membership-fee":
                        trendit3_user.membership_fee(paid=True)
                        membership_fee_paid = trendit3_user.membership.membership_fee_paid
                        msg = "Payment verified successfully and Account has been activated"
                        extra_data.update({"membership_fee_paid": membership_fee_paid})
                        
                    elif payment_type == "task-creation":
                        task_key = response_data["data"]["meta"]["task_key"]
                        task = get_task_by_key(task_key)
                        task.update(payment_status=TaskPaymentStatus.COMPLETE)
                        task_dict = task.to_dict()
                        msg = "Payment verified and Task has been created successfully"
                        extra_data.update({"task": task_dict})
                        send_task_order_review_email(task.id)
                    elif payment_type == "credit-wallet":
                        # Credit user"s wallet
                        try:
                            credit_wallet(user_id, amount, credit_type="funded-wallet")
                        except ValueError as e:
                            raise CreditWalletError(f"Error crediting wallet. Please Try To Verify Again: {e}")
                        
                        msg = "Wallet Credited successfully"
                    
                elif transaction.status.lower() == "complete":
                    if payment_type == "membership-fee":
                        msg = "Payment Completed successfully and Account is already activated"
                        extra_data.update({"membership_fee_paid": trendit3_user.membership.membership_fee_paid,})
                            
                    elif payment_type == "task-creation":
                        task_key = response_data["data"]["meta"]["task_key"]
                        task = get_task_by_key(task_key)
                        task_dict = task.to_dict()
                        msg = "Payment Completed and Task has already been created successfully"
                        extra_data.update({"task": task_dict})
                            
                    elif payment_type == "credit-wallet":
                        msg = "Payment Completed and Wallet already credited"
                
                success = True
            elif response_data["status"] and payment_status == "abandoned":
                # Payment was not completed
                if transaction.status.lower() != "abandoned":
                    transaction.update(status="abandoned") # update the status
                    payment.update(status="abandoned") # update the status
                    
                msg = f"Abandoned."
                success = False
                    
            else:
                # Payment was not successful
                if transaction.status.lower() != "failed":
                    transaction.update(status="failed") # update the status
                    payment.update(status="failed") # update the status
                        
                msg = "Payment verification failed: " + response_data["message"]
                success = False
            
            extra_data.update({"user_data": trendit3_user.to_dict(), "status_code": status_code})
        else:
            msg = "An error occurred verifying payment: Contact the admin"
            success = False
            removed_message = response_data.pop("message") if "message" in response_data else ""
            extra_data = response_data
        
        console_log("extra_data", extra_data)
        result = {
            "msg": msg,
            "success": success,
            "extra_data": extra_data
        }
        console_log("result", result)
    except (DataError, DatabaseError) as e:
        raise e
    except Exception as e:
        raise e
    finally:
        try:
            task = task
            notify_telegram_admins_new_task(task) # send message to admins on telegram
        except NameError as e:
            log_exception("'task' variable doesn't exist", e)
            pass
    
    return result


def flutterwave_webhook():
    try:
        data = json.loads(request.data) # Get the data from the request
        console_log("DATA", data)
        
        secret_hash = Config.FLW_SECRET_HASH
        signature = request.headers.get("verif-hash") # Get the signature from the request headers
        
        
        if signature == None or (signature != secret_hash):
            # This request isn"t from Flutterwave; discard
            raise SignatureError(f"No signature in headers")
        
        # Extract needed data
        amount = float(data["data"]["amount"])
        reference = data["data"]["tx_ref"]
        payment_status = data["data"]["status"].lower()
        
        
        transaction: Transaction = Transaction.query.filter_by(key=reference).first()
        payment: Payment = Payment.query.filter_by(key=reference).first()
        
        if not transaction:
            result = {
                "success": False,
                "status_code": 404
            }
            return jsonify(result), 404
        
        if transaction:
            user_id = transaction.trendit3_user_id
            payment_type = payment.payment_type
            trendit3_user = transaction.trendit3_user
            
            # Check if this is a successful payment event
            if payment_status == "successful":
                if transaction.status.lower() != "complete":
                    # Record the payment and transaction in the database
                    transaction.update(status="complete")
                    payment.update(status="complete")
                    
                    # Update user"s membership status in the database
                    if payment_type == "membership-fee":
                        update_membership_payment(trendit3_user.id)
                        trendit3_user.membership_fee(paid=True)
                        try:
                            send_other_emails(trendit3_user.email, amount=amount) # send email
                        except Exception as e:
                            raise Exception("Error occurred sending Email")
                    
                    elif payment_type == "task-creation":
                        task_key = data["data"]["meta"]["task_key"]
                        task = get_task_by_key(task_key)
                        task.update(payment_status=TaskPaymentStatus.COMPLETE)
                    
                    elif payment_type == "credit-wallet":
                        # Credit user"s wallet
                        try:
                            credit_wallet(user_id, amount, credit_type="funded-wallet")
                            send_other_emails(trendit3_user.email, email_type="credit", amount=amount) # send credit alert to user"s email
                        except ValueError as e:
                            raise ValueError(f"Error crediting wallet: {e}")
                        except Exception as e:
                            raise Exception(f"Error occurred sending Email or crediting wallet: {e}")
                
                result = {
                    "success": True,
                    "status_code": 200
                }
                
            elif payment_status == "abandoned" or data["event"] == "charge.abandoned":
                # Payment was not completed
                if transaction.status.lower() != "abandoned":
                    transaction.update(status="abandoned") # update the status
                    payment.update(status="abandoned") # update the status
                            
                result = {
                    "success": False,
                    "status_code": 200
                }
            else:
                # Payment was not successful
                if transaction.status.lower() != "failed":
                    transaction.update(status="failed") # update the status
                    payment.update(status="failed") # update the status
                result = {
                    "success": False,
                    "status_code": 200
                }
        else:
            result = {
                "success": False,
                "status_code": 404
            }
    except SignatureError as e:
        fund_wallet = credit_wallet(user_id, amount, credit_type="failed-payment") if data["data"]["status"] == "successful" else False
        raise e
    except (DataError, DatabaseError) as e:
        fund_wallet = credit_wallet(user_id, amount, credit_type="failed-payment") if data["data"]["status"] == "successful" else False
        raise e
    except Exception as e:
        fund_wallet = credit_wallet(user_id, amount, credit_type="failed-payment") if data["data"]["status"] == "successful" else False
        raise e
    finally:
        try:
            task = task
            notify_telegram_admins_new_task(task) # send message to admins on telegram
        except NameError as e:
            log_exception("'task' variable doesn't exist", e)
            pass
    
    return result


def flutterwave_initiate_transfer(bank: BankAccount, amount: float, currency: str, user: Trendit3User) -> dict:
    try:
        user_wallet = user.wallet
        bank_name = bank.bank_name
        account_no = bank.account_no
        reference = f"{generate_random_string(20)}-{generate_random_string(19)}"
        narration = f"withdraw from {user.profile.firstname}'s Trendit³ wallet"
        
        data = {
            "account_bank": str(bank.bank_code),
            "account_number": str(account_no),
            "amount": int(amount),
            "currency": str(currency),
            "narration": narration,
            "reference": reference,
            "callback_url": f"{Config.API_DOMAIN_NAME}/api/payment/withdraw-approval"
        }
        response = requests.post(Config.FLW_TRANSFER_URL, headers=headers, json=data)
        response_data = response.json()
        
        console_log("data", data)
        
        console_log("flw_transfer_resp_data", response_data)
        
        console_log("FLW_TRANSFER_URL", Config.FLW_TRANSFER_URL)
        
        if "status" in response_data and response_data["status"] == "success":
            reference = response_data["data"]["reference"]
            status = response_data["data"]["status"]
            
            fee_percentage = Decimal("0.015")  # Represents 1.5% as a decimal
            fee = amount * fee_percentage
            
            transaction = Transaction.create_transaction(key=reference, amount=amount, transaction_type=TransactionType.WITHDRAWAL, description=narration, status="pending", trendit3_user=user)
            withdrawal = Withdrawal.create_withdrawal(reference=reference, amount=amount, bank_name=bank_name, account_no=account_no, status=status, trendit3_user=user)
            
            withdrawal.status=status  # Update withdrawal status
            transaction.status="complete"  # Update transaction status
            user_wallet.balance -= (amount + fee) # Debit the wallet
            db.session.commit()
            
            transfer_info =  {
                "status": status,
                "amount": amount,
                "reference": reference,
                "transfer_id": response_data["data"]["id"],
                "currency": response_data["data"]["currency"],
                "created_at": response_data["data"]["created_at"]
            }
        else:
            msg = response_data["message"]
            raise FlutterwaveError(f"{msg}")
        
        return transfer_info
        
    except requests.exceptions.RequestException as e:
        raise e
    except (DataError, DatabaseError) as e:
        raise e
    except Exception as e:
        raise e


def get_banks(country:str = None) -> list:
    try:
        iso_code = get_iso_code(country) if country else "NG"
        url = f"{Config.FLW_BANKS_URL}/{iso_code}" if iso_code else Config.FLW_BANKS_URL
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # raise an exception if the request failed
        response_data = response.json()
        
        
        if "status" in response_data and response_data["status"] == "success":
            supported_banks = response_data["data"]
        else:
            supported_banks = None
    
    except requests.exceptions.RequestException as e:
        raise e
    except Exception as e:
        raise e
    
    return supported_banks

def create_bank_name_to_code_mapping(country : str = None) -> dict:
    """This will give you a dictionary mapping bank names to their codes"""
    supported_banks = get_banks(country)
    
    mapping = {}
    if supported_banks:
        mapping = {bank["name"].lower(): str(bank["code"]) for bank in supported_banks}
    
    console_log("mapping", mapping)
    
    return mapping

def get_bank_code(bank_name: str, country: str | None = None) -> str:
    console_log("bank_name", bank_name)
    
    bank_name_to_code_mapping = create_bank_name_to_code_mapping(country)
    bank_code = bank_name_to_code_mapping[bank_name.lower()]
    
    console_log("bank_code", bank_code)
    
    return str(bank_code)



def fetch_supported_countries() -> list:
    supported_countries = [
        {"name": "Nigeria", "iso_code": "NG", "currency_code": "NGN"},
        {"name": "Ghana", "iso_code": "GH", "currency_code": "GHS"},
        {"name": "South Africa", "iso_code": "ZA", "currency_code": "ZAR"},
        {"name": "Kenya", "iso_code": "KE", "currency_code": "KES"},
        {"name": "Malawi", "iso_code": "MW", "currency_code": "MWK"},
        {"name": "Uganda", "iso_code": "UG", "currency_code": "UGX"},
        {"name": "Rwanda", "iso_code": "RW", "currency_code": "RWF"},
        {"name": "Tanzania", "iso_code": "TZ", "currency_code": "TZS"},
        
        # Francophone Africa (Central Africa)
        {"name": "Cameroon", "iso_code": "CM", "currency_code": "XAF"},
        {"name": "Central African Republic", "iso_code": "CF", "currency_code": "XAF"},
        {"name": "Chad", "iso_code": "TD", "currency_code": "XAF"},
        {"name": "Republic of the Congo", "iso_code": "CG", "currency_code": "XAF"},
        {"name": "Equatorial Guinea", "iso_code": "GQ", "currency_code": "XAF"},
        {"name": "Gabon", "iso_code": "GA", "currency_code": "XAF"},
        
        # Francophone Africa (West Africa)
        {"name": "Benin", "iso_code": "BJ", "currency_code": "XOF"},
        {"name": "Burkina Faso", "iso_code": "BF", "currency_code": "XOF"},
        {"name": "Ivory Coast", "iso_code": "CI", "currency_code": "XOF"},
        {"name": "Guinea-Bissau", "iso_code": "GW", "currency_code": "XOF"},
        {"name": "Mali", "iso_code": "ML", "currency_code": "XOF"},
        {"name": "Niger", "iso_code": "NE", "currency_code": "XOF"},
        {"name": "Senegal", "iso_code": "SN", "currency_code": "XOF"},
        {"name": "Togo", "iso_code": "TG", "currency_code": "XOF"},
        
        {"name": "United States", "iso_code": "US", "currency_code": "USD"},
        {"name": "Europe", "iso_code": "EU", "currency_code": "EUR"},
        {"name": "United Kingdom", "iso_code": "GB", "currency_code": "GBP"},
    ]
    try:
        if supported_countries:
            supported_countries = supported_countries
        else:
            supported_countries = None
        
    except Exception as e:
        raise e
    
    return supported_countries


def get_iso_code(country_name: str) -> str:
    """
    This function retrieves the ISO code for a given country name
    """
    try:
        supported_countries = fetch_supported_countries()
        for country in supported_countries:
            if country["name"].lower() == country_name.lower():
                return country["iso_code"]
        return None
    except (KeyError, ValueError):
        # Handle cases where the country name is not found or the structure is invalid
        return None


def flutterwave_verify_bank_account(account_no: str, bank_code: str) -> dict:
    try:
        data = {
            "account_number": account_no,
            "account_bank": str(bank_code)
        }
        
        response = requests.post(Config.FLW_VERIFY_BANK_ACCOUNT_URL, headers=headers, json=data)
        response_data = response.json()
        
        console_log("fwl_response_data", response_data)
        
        if "status" in response_data and response_data["status"] == "success":
            account_info =  {
                "account_number": response_data["data"]["account_number"],
                "account_name": response_data["data"]["account_name"]
            }
            return account_info
        else:
            # a fallback logic with paystack if the check with flutter wave fails
            # the bank_mapping is put in place because 
            # flutterwave appears to have a problem with OPay and PalmPay bank codes
            bank_mapping = {
                "305": "OPay Digital Services Limited (OPay)",
                "100004": "OPay Digital Services Limited (OPay)",
                "100033": "PalmPay",
                "090405": "Moniepoint MFB"
            }
            bank_name = bank_mapping.get(bank_code, None)
            
            if bank_name:
                from .paystack import get_bank_code as paystack_get_bank_code
                bank_code = paystack_get_bank_code(bank_name, "nigeria")
            
            fallback_url = f"https://api.paystack.co/bank/resolve?account_number={account_no}&bank_code={bank_code}"
            paystack_response = requests.get(fallback_url, headers=paystack_headers)
            paystack_response_data = paystack_response.json()
            
            console_log("paystack_response_data", paystack_response_data)
            
            if paystack_response_data["status"]:
                account_info =  {
                    "account_number": paystack_response_data["data"]["account_number"],
                    "account_name": paystack_response_data["data"]["account_name"]
                }
                return account_info
            else:
                msg = response_data["message"]
                raise ValueError(f"Account Verification Failed: {msg}")
    except requests.exceptions.RequestException as e:
        raise e
    except Exception as e:
        raise e


def flutterwave_fetch_balance() -> dict:
    try:
        url = f"https://api.flutterwave.com/v3/balances/NGN"
        response = requests.get(url, headers=headers)
        
        console_log("response", response)
        console_log("response_data", response.json())
        
        response.raise_for_status()  # raise an exception if the request failed
        response_data = response.json()
        
        console_log("response_data", response_data)
        
        if "status" in response_data and response_data["status"] == "success":
            balances: dict = response_data["data"]
        else:
            balances = None
        
        return balances
    
    except requests.exceptions.RequestException as e:
        raise e
    except Exception as e:
        raise e
