import sys, os
from decimal import Decimal
from threading import Thread
from flask import request, current_app
from sqlalchemy import func
from sqlalchemy.exc import ( DataError, DatabaseError, )
from flask_jwt_extended import get_jwt_identity
from datetime import datetime, timedelta

from ...extensions import db
from ...models import Task, AdvertTask, EngagementTask, TaskStatus, TaskPaymentStatus, TaskPerformance, RoleNames
from .loggers import console_log, log_exception
from ...utils.helpers.media_helpers import save_media, save_media_files_to_temp
from ...exceptions import PendingTaskError, NoUnassignedTaskError
from .user_helpers import add_user_role



def fetch_task(task_id_key: int | str) -> Task:
    """
    Fetches a task from the database based on either its ID or task_key.

    Parameters:
    - task_id_key (int or str): The ID or task_key of the task to fetch. 
        - If an integer, the function fetches the task by ID; 
        - if a string, it fetches the task by task_key.

    Returns:
    - Task or None: The fetched task if found, or None if no task matches the provided ID or task_key.
    """
    try:
        # Check if task_id_key is an integer
        task_id_key = int(task_id_key)
        # Fetch the task by id
        task = Task.query.filter_by(id=task_id_key).first()
    except ValueError:
        # If not an integer, treat it as a string
        task = Task.query.filter_by(task_key=task_id_key).first()

    if task:
        return task
    else:
        return None


def get_tasks_dict_grouped_by_field(field: str, task_type: str) -> dict:
    tasks_dict = {}
    
    try:
        if task_type == 'advert':
            tasks = AdvertTask.query.filter_by(payment_status=TaskPaymentStatus.COMPLETE, status=TaskStatus.APPROVED).all()
        elif task_type == 'engagement':
            tasks = EngagementTask.query.filter_by(payment_status=TaskPaymentStatus.COMPLETE, status=TaskStatus.APPROVED).all()
        else:
            raise ValueError(f"Invalid task_type: {task_type}")

        for task in tasks:
            key = getattr(task, field)
            if key not in tasks_dict:
                tasks_dict[key] = {
                    'total': 0,
                    'tasks': [],
                }
            tasks_dict[key]['total'] += 1
            tasks_dict[key]['tasks'].append(task.to_dict())
    except AttributeError as e:
        raise ValueError(f"Invalid field: {field}")
    except Exception as e:
        raise e

    return tasks_dict


def get_aggregated_task_counts_by_field(field: str, task_type: None | str =None) -> dict:
    """Retrieves aggregated task counts grouped by the specified field,
    optimized using database-level aggregation, and returns results as a dictionary.

    Args:
        field (str): The field to group tasks by.
        task_type (str): The type of tasks to retrieve ('advert' or 'engagement').

    Returns:
        dict: A dictionary where keys are the field values and values are dictionaries
                containing the field value ('name') and its count ('total').

    Raises:
        ValueError: If an invalid field or task_type is provided.
    """

    try:
        task_model = (AdvertTask if task_type == 'advert' else EngagementTask if task_type == 'engagement' else Task)
        
        results = db.session.query(getattr(task_model, field), func.count(task_model.id).label('task_count')) \
                            .filter_by(payment_status=TaskPaymentStatus.COMPLETE, status=TaskStatus.APPROVED) \
                            .group_by(getattr(task_model, field)) \
                            .all()
        
        return {key: {'name': key, 'total': count} for key, count in results}

    except AttributeError as e:
        raise ValueError(f"Invalid field: {field}")
    except Exception as e:
        raise e


def generate_random_task(task_type:str, filter_value:str) -> AdvertTask | EngagementTask:
    """Retrieves a random task of the specified type, filtering by platform or goal, ensuring it's not assigned to another user.

        Args:
            task_type (str): The type of task to retrieve ('advert' or 'engagement').
            filter_value (str): The value to filter tasks by (platform for adverts, goal for engagements).

        Returns:
            Object: A DB object of the randomly selected task.

        Raises:
            LookupError: If no unassigned task was found
            ValueError: If an invalid task type or platform is provided.
            Exception: If an unexpected error occurs during retrieval.
    """
    try:
        current_user_id = int(get_jwt_identity())
        performed_task = None
        if task_type == "advert":
            performed_task = TaskPerformance.query.join(Task).filter(TaskPerformance.status == "pending", TaskPerformance.task_type == task_type, TaskPerformance.user_id==current_user_id, Task.platform==filter_value).first()
        elif task_type == "engagement":
            performed_tasks = TaskPerformance.query.filter_by(status="pending", user_id=current_user_id, task_type=task_type).all()
            for performed_task in performed_tasks:
                task = EngagementTask.query.filter_by(id=performed_task.task_id, goal=filter_value).first()
                if task:
                    raise PendingTaskError
            
        
        if performed_task:
            raise PendingTaskError
        
        task_model = (AdvertTask if task_type == 'advert' else EngagementTask if task_type == 'engagement' else None)
        
        # Dynamically filter by platform, goal, posts_count or engagements_count based on task type
        filter_field = 'platform' if task_type == 'advert' else 'goal'
        count_field = 'posts_count' if task_type == 'advert' else 'engagements_count'
        
        # Filter for unassigned tasks
        random_task = task_model.query.filter(
            getattr(task_model, filter_field) == filter_value,
            task_model.payment_status == TaskPaymentStatus.COMPLETE,
            task_model.status == TaskStatus.APPROVED,
            getattr(task_model, count_field) > getattr(task_model, 'total_success'),
            task_model.trendit3_user_id != current_user_id,  # Exclude tasks created by the current user
            ~TaskPerformance.query.filter(
                TaskPerformance.task_id == task_model.id,
                TaskPerformance.user_id == current_user_id
            ).exists()
        ).order_by(func.random()).first()
        
        if not random_task:
            raise NoUnassignedTaskError(f"There are no {task_type} tasks for the {filter_field} '{filter_value}'.")
        
        return random_task  # Return the generated task

    except AttributeError as e:
        raise ValueError(f"Invalid Task Type or Filter: {task_type}/{filter_value}")
    except Exception as e:
        raise e


def initiate_task(task: Task, status='pending') -> dict:
    try:
        current_user_id = int(get_jwt_identity())
        
        if task is None:
            raise NoUnassignedTaskError("Task not found.")
        
        # Validate task readiness (adjust criteria as needed)
        if task.payment_status != TaskPaymentStatus.COMPLETE:
            raise ValueError("This task is not available for performance")
        
        reward_money = task.reward_money
        
        # Create a new TaskPerformance instance
        initiated_task = TaskPerformance.create_task_performance(user_id=current_user_id, task_id=task.id, task_type=task.task_type, reward_money=reward_money, proof_screenshot=None, account_name='', post_link='', status=status)
        
        add_user_role(RoleNames.EARNER, current_user_id) # Give user role of Earner
        
        # Mark the task as assigned
        task.total_allocated += 1
        db.session.add(task)
        db.session.commit()
        
        return initiated_task.to_dict()
    except ValueError as e:
        raise e
    except Exception as e:
        db.session.rollback()
        log_exception("An exception occurred trying to initiate task performance", e)
        raise e


def get_task_by_key(task_key) -> Task | AdvertTask | EngagementTask:
    task = EngagementTask.query.filter_by(task_key=task_key).first()

    if task is None:
        task = AdvertTask.query.filter_by(task_key=task_key).first()

    if task is None:
        task = Task.query.filter_by(task_key=task_key).first()
    
    return task


def async_save_task_media_files(app, task_id_key: str | int, media_file_paths):
    with app.app_context():
        try:
            console_log("saving media", f"starting... {media_file_paths}")
            task = fetch_task(task_id_key)
            
            #save media files
            if media_file_paths:
                for media_file_path in media_file_paths:
                    filename = os.path.basename(media_file_path)
                    with open(media_file_path, 'rb') as media_file:
                        media = save_media(media_file, filename)
                        task.media.append(media)
                    
            elif not media_file_paths and task:
                task.media = task.media
            
            db.session.commit()
            console_log("end of saving...", "...")
        except Exception as e:
            log_exception("an exception occurred saving task media", e)
            raise e

def save_task_media_files(task_id_key: str | int, media_file_paths):
    Thread(target=async_save_task_media_files, args=(current_app._get_current_object(), task_id_key, media_file_paths)).start()

def save_task(data, task_id_key=None, payment_status=TaskPaymentStatus.PENDING):
    try:
        console_log("saving task", "...")
        user_id = int(get_jwt_identity())
        task = fetch_task(task_id_key) if task_id_key else None
        
        task_type = data.get('task_type', task.task_type if task else '')
        platform = data.get('platform', task.platform if task else '').lower()
        fee = 20
        fee_paid = data.get('amount', task.fee_paid if task else '')
        target_country = data.get('target_country', task.target_country if task else '')
        target_state = data.get('target_state', task.target_state if task else '')
        gender = data.get('gender', task.gender if task else '')
        religion = data.get('religion', task.religion if task else '')
        reward_money = data.get('reward_money', task.reward_money if task else None)
        
        if not reward_money:
            raise ValueError("reward_money needs to be provided")
        
        reward_money = Decimal(reward_money)
        
        if task_type == 'advert':
            caption = data.get('caption', task.caption if task and hasattr(task, "caption") else '')
            hashtags = data.get('hashtags', task.hashtags if task and hasattr(task, "hashtags") else '')
            posts_count_str = data.get('posts_count', task.posts_count if task and hasattr(task, "posts_count") else '')
            posts_count = int(posts_count_str) if posts_count_str and posts_count_str.isdigit() else 0
            
        if task_type == 'engagement':
            goal = data.get('goal', task.goal if task and hasattr(task, "goal") else '')
            account_link = data.get('account_link', task.account_link if task and hasattr(task, "account_link") else '')
            engagements_count_str = data.get('engagements_count', task.engagements_count if task and hasattr(task, "engagements_count") else '')
            engagements_count = int(engagements_count_str) if engagements_count_str and engagements_count_str.isdigit() else 0
        
        # Get multiple media files
        media_files = request.files.getlist('media')
        
        # Save media files to temp directory and get paths
        media_file_paths = save_media_files_to_temp(media_files)
        console_log("media_file_paths", media_file_paths)
        
        
        if task_type == 'advert':
            if task:
                task.update(trendit3_user_id=user_id, task_type=task_type, platform=platform, fee_paid=fee_paid, fee=fee, payment_status=payment_status, posts_count=posts_count, target_country=target_country, target_state=target_state, gender=gender, religion=religion, caption=caption, hashtags=hashtags, reward_money=reward_money)
                
                console_log("saving media files with celery...", "save_task_media_files sent to celery")
                save_task_media_files(task_id_key=task.id, media_file_paths=media_file_paths) #save media files
                
                return task
            else:
                new_task = AdvertTask.create_task(trendit3_user_id=user_id, task_type=task_type, platform=platform, fee_paid=fee_paid, fee=fee, payment_status=payment_status, posts_count=posts_count, target_country=target_country, target_state=target_state, gender=gender, religion=religion, caption=caption, hashtags=hashtags, reward_money=reward_money)

                add_user_role(RoleNames.ADVERTISER, user_id)
                
                console_log("saving media files with celery...", "save_task_media_files sent to celery")
                save_task_media_files(task_id_key=new_task.id, media_file_paths=media_file_paths) #save media files
                
                return new_task
            
        elif task_type == 'engagement':
            if task:
                task.update(trendit3_user_id=user_id, task_type=task_type, platform=platform, fee_paid=fee_paid, fee=fee, payment_status=payment_status, goal=goal, account_link=account_link, engagements_count=engagements_count, target_country=target_country, target_state=target_state, gender=gender, religion=religion, reward_money=reward_money)
                
                return task
            else:
                new_task = EngagementTask.create_task(trendit3_user_id=user_id, task_type=task_type, platform=platform, fee_paid=fee_paid, fee=fee, payment_status=payment_status, goal=goal, account_link=account_link, engagements_count=engagements_count, target_country=target_country, target_state=target_state, gender=gender, religion=religion, reward_money=reward_money)

                add_user_role(RoleNames.ADVERTISER, user_id)
                
                return new_task
        else:
            raise ValueError("invalid Task type")
    except (DataError, DatabaseError) as e:
        raise e
    except Exception as e:
        log_exception(f"An exception occurred trying to save Task {data.get('task_type')}", e)
        raise e
    finally:
        console_log("task saved", "...")



def update_performed_task(data, pt_id=None, status='pending'):
    try:
        user_id = int(get_jwt_identity())
        task_id_key = data.get('task_id_key', '')
        task = fetch_task(task_id_key)
        
        if task is None:
            raise ValueError("Task not found.")
        
        task_id = task.id
        
        reward_money = float(data.get('reward_money'))
        screenshot = request.files.get('screenshot', '')
        account_name = data.get('account_name')
        post_link = data.get('post_link', '')
        
        console_log("account_name", account_name)
        console_log("post_link", post_link)
        
        task_type = task.task_type
        
        performed_task = None
        if pt_id:
            performed_task = TaskPerformance.query.get(pt_id)
        else:
            performed_task = TaskPerformance.query.filter_by(user_id=user_id, task_id=task_id, status='pending').first()
        
        
        if not performed_task:
            raise ValueError("Couldn't find Task you are trying to perform")
            
        if task.task_type == "engagement" and screenshot == '':
            raise ValueError("No screenshot provided.")
        
        proof_screenshot = None
        if screenshot and screenshot.filename != '':
            try:
                proof_screenshot = save_media(screenshot)
            except ValueError as e:
                current_app.logger.error(f"An error occurred while saving Screenshot: {str(e)}")
                raise ValueError(f"{e}")
            except Exception as e:
                current_app.logger.error(f"An error occurred while saving Screenshot: {str(e)}")
                raise Exception("Error saving Screenshot.")
        elif screenshot == '' and task:
            if performed_task.proof_screenshot_id:
                proof_screenshot = performed_task.proof_screenshot
            else:
                if task.task_type == "engagement":
                    raise Exception("No screenshot provided.")
                else:
                    pass
        else:
            if task.task_type == "engagement":
                raise Exception("No screenshot provided.")
            else:
                pass
        
        if performed_task:
            performed_task.update(user_id=user_id, task_id=task_id, task_type=task_type, proof_screenshot=proof_screenshot, account_name=account_name, post_link=post_link, status=status)
            
            return performed_task
        else:
            new_performed_task = TaskPerformance.create_task_performance(user_id=user_id, task_id=task_id, task_type=task_type, reward_money=reward_money, proof_screenshot=proof_screenshot, account_name=account_name, post_link=post_link, status=status)
            
            return new_performed_task
    except Exception as e:
        log_exception("An exception occurred trying to save performed task", e)
        db.session.rollback()
        raise e



def fetch_performed_tasks_by_status(status):

    try:
        current_user_id = int(get_jwt_identity())
        page = request.args.get("page", 1, type=int)
        tasks_per_page = int(6)
        pagination = TaskPerformance.query.filter_by(user_id=current_user_id, status=status) \
            .order_by(TaskPerformance.started_at.desc()) \
            .paginate(page=page, per_page=tasks_per_page, error_out=False)
        
        
        performed_tasks = pagination.items
        current_tasks = [performed_task.to_dict() for performed_task in performed_tasks]
        json_data = {
            'total': pagination.total,
            "performed_tasks": current_tasks,
            "current_page": pagination.page,
            "total_pages": pagination.pages,
        }
        return json_data
    except Exception as e:
        raise e


def fetch_performed_task(pt_id_key):
    """
    Fetches a Performed task from the database based on either its ID or key.

    Parameters:
    - pt_id_key (int or str): The ID or task_key of the task to fetch. 
        - If an integer, the function fetches the task by ID; 
        - if a string, it fetches the task by task_key.

    Returns:
    - Task or None: The fetched Performed task if found, or None if no Performed task matches the provided ID or key.
    """
    try:
        # Check if task_id_key is an integer
        pt_id_key = int(pt_id_key)
        # Fetch the task by id
        performed_task = TaskPerformance.query.filter_by(id=pt_id_key).first()
    except ValueError:
        # If not an integer, treat it as a string
        performed_task = TaskPerformance.query.filter_by(key=pt_id_key).first()

    if performed_task:
        return performed_task
    else:
        return None


def get_user_tasks_metrics(user: object) -> dict:
    
    try:
        all_time_total_tasks = user.total_tasks # get total task ever created by the user
        
        
        # Get the beginning of the month
        month_start = datetime.now().replace(day=1).replace(hour=0, minute=0, second=0, microsecond=0)

        # Build the query
        tasks_query = Task.query.filter_by(trendit3_user_id=user.id)
        tasks_query = tasks_query.filter(Task.date_created >= month_start) # get task since the beginning of the month

        # Count the tasks
        month_total_task = tasks_query.count()
        task_metrics = {
            'all_time_total_tasks': user.total_tasks,
            'month_total_task': month_total_task,
        }
    except Exception as e:
        log_exception('An exception occurred getting getting task metrics', e)
        raise e
    
