from flask import request
from sqlalchemy.exc import ( DataError, DatabaseError )
from datetime import datetime, date, timedelta
from sqlalchemy import func
from decimal import Decimal


from ...extensions import db
from ...utils.helpers.response_helpers import error_response, success_response
from ...utils.helpers.basic_helpers import log_exception, console_log
from ...utils.payments.rates import format_currency


from ...models import (Trendit3User, Task, TaskStatus, SocialMediaProfile, SocialLinkStatus, Payment, Withdrawal)


class AdminStatsController:

    @staticmethod
    def get_statistics():
        try:
            period = request.args.get('period', 'day')  # Default to 'day'
            
            today = date.today()
            
            if period == 'day':
                start_date = today
                end_date = today + timedelta(days=1)
            elif period == 'yesterday':
                start_date = today - timedelta(days=1)
                end_date = today
            elif period == 'month':
                start_date = today.replace(day=1)
                end_date = (start_date + timedelta(days=32)).replace(day=1)
            elif period == 'year':
                start_date = today.replace(month=1, day=1)
                end_date = start_date.replace(year=start_date.year + 1)
            else:
                return error_response("Invalid period specified", 400)
            
            
            # Fetch statistics from the database
            new_signups = db.session.query(func.count(Trendit3User.id)).filter(Trendit3User.date_joined >= start_date, Trendit3User.date_joined < end_date).scalar()
            new_task = db.session.query(func.count(Task.id)).filter(Task.date_created >= start_date, Task.date_created < end_date).scalar()
            
            approved_tasks = db.session.query(func.count(Task.id)).filter(Task.date_created >= start_date, Task.date_created < end_date, Task.status==TaskStatus.APPROVED).scalar()
            declined_tasks = db.session.query(func.count(Task.id)).filter(Task.date_created >= start_date, Task.date_created < end_date, Task.status==TaskStatus.DECLINED).scalar()
            
            pending_tasks = db.session.query(func.count(Task.id)).filter(Task.date_created >= start_date, Task.date_created < end_date, Task.status==TaskStatus.PENDING).scalar()
            
            pending_social_profiles = db.session.query(func.count(SocialMediaProfile.id)).filter(SocialMediaProfile.status==SocialLinkStatus.PENDING).scalar()
            
            # Calculate total successful paid amounts by every user, excluding "wallet" payments
            total_payments = db.session.query(func.sum(Payment.amount)).filter(
                Payment.created_at >= start_date,
                Payment.created_at < end_date,
                Payment.payment_method != "wallet",
                Payment.status == "complete"
            ).scalar() or 0.00
            
            # Calculate total payments for each specific payment type
            task_creation_payments = db.session.query(func.sum(Payment.amount)).filter(
                Payment.created_at >= start_date,
                Payment.created_at < end_date,
                Payment.payment_method != 'wallet',
                Payment.status == "complete",
                Payment.payment_type == 'task-creation'
            ).scalar() or 0.00
            
            membership_payments = db.session.query(func.sum(Payment.amount)).filter(
                Payment.created_at >= start_date,
                Payment.created_at < end_date,
                Payment.payment_method != 'wallet',
                Payment.status == "complete",
                Payment.payment_type == 'membership-fee'
            ).scalar() or 0.00
            
            credit_wallet_payments = db.session.query(func.sum(Payment.amount)).filter(
                Payment.created_at >= start_date,
                Payment.created_at < end_date,
                Payment.payment_method != 'wallet',
                Payment.status == "complete",
                Payment.payment_type == 'credit-wallet'
            ).scalar() or 0.00
            
            
            withdrawals = db.session.query(func.sum(Withdrawal.amount)).filter(
                Withdrawal.created_at >= start_date,
                Withdrawal.created_at < end_date,
                Withdrawal.status == "SUCCESSFUL",
            ).scalar() or 0.00
            
            
            
            extra_data={
                "stats": {
                    "new_signups": new_signups,
                    "new_task": new_task,
                    "approved_tasks": approved_tasks,
                    "declined_tasks": declined_tasks,
                    "pending_tasks": pending_tasks,
                    "pending_social_profiles": pending_social_profiles,
                    
                    "total_payments": format_currency(Decimal(total_payments)),"task_creation_payments": format_currency(Decimal(task_creation_payments)),
                    "membership_payments": format_currency(Decimal(membership_payments)),
                    "credit_wallet_payments": format_currency(Decimal(credit_wallet_payments)),
                    "total_withdrawals": format_currency(Decimal(withdrawals))
                }
            }
            
            api_response = success_response("Statistics fetched successfully", 200, extra_data)
        except (DataError, DatabaseError) as e:
            log_exception(f"An exception occurred during database operation:", e)
            api_response = error_response("Database error occurred", 500)
        except Exception as e:
            log_exception(f"An unexpected exception occurred fetching statistics", e)
            api_response = error_response('An unexpected error. Our developers are already looking into it.', 500)
        
        return api_response


    @staticmethod
    def get_payment_stats():
        try:
            period = request.args.get('period', 'day')  # Default to 'day'
            
            today = date.today()
            
            if period == 'day':
                start_date = today
                end_date = today + timedelta(days=1)
            elif period == 'yesterday':
                start_date = today - timedelta(days=1)
                end_date = today
            elif period == 'month':
                start_date = today.replace(day=1)
                end_date = (start_date + timedelta(days=32)).replace(day=1)
            elif period == 'year':
                start_date = today.replace(month=1, day=1)
                end_date = start_date.replace(year=start_date.year + 1)
            else:
                return error_response("Invalid period specified", 400)
            
            
            # Fetch statistics from the database
            
            # Calculate total successful paid amounts by every user, excluding "wallet" payments
            total_payments = db.session.query(func.sum(Payment.amount)).filter(
                Payment.created_at >= start_date,
                Payment.created_at < end_date,
                Payment.payment_method != "wallet",
                Payment.status == "complete"
            ).scalar() or 0
            
            # Calculate total payments for each specific payment type
            task_creation_payments = db.session.query(func.sum(Payment.amount)).filter(
                Payment.created_at >= start_date,
                Payment.created_at < end_date,
                Payment.payment_method != 'wallet',
                Payment.status == "complete",
                Payment.payment_type == 'task-creation'
            ).scalar() or 0
            
            membership_payments = db.session.query(func.sum(Payment.amount)).filter(
                Payment.created_at >= start_date,
                Payment.created_at < end_date,
                Payment.payment_method != 'wallet',
                Payment.status == "complete",
                Payment.payment_type == 'membership-fee'
            ).scalar() or 0
            
            credit_wallet_payments = db.session.query(func.sum(Payment.amount)).filter(
                Payment.created_at >= start_date,
                Payment.created_at < end_date,
                Payment.payment_method != 'wallet',
                Payment.status == "complete",
                Payment.payment_type == 'credit-wallet'
            ).scalar() or 0
            
            
            
            extra_data={
                "stats": {
                    "total_payments": format_currency(Decimal(total_payments)),"task_creation_payments": format_currency(Decimal(task_creation_payments)),
                    "membership_payments": format_currency(Decimal(membership_payments)),
                    "credit_wallet_payments": format_currency(Decimal(credit_wallet_payments))
                }
            }
            
            api_response = success_response("Statistics fetched successfully", 200, extra_data)
        except (DataError, DatabaseError) as e:
            log_exception(f"An exception occurred during database operation:", e)
            api_response = error_response("Database error occurred", 500)
        except Exception as e:
            log_exception(f"An unexpected exception occurred fetching statistics", e)
            api_response = error_response('An unexpected error. Our developers are already looking into it.', 500)
        
        return api_response

