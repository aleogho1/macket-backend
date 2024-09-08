import requests, random, os, app
from datetime import timedelta
from flask import request, make_response
from sqlalchemy.exc import ( IntegrityError, DataError, DatabaseError, InvalidRequestError, )
from werkzeug.exceptions import UnsupportedMediaType
from flask_jwt_extended import create_access_token
from flask_jwt_extended.exceptions import JWTDecodeError
from jwt import ExpiredSignatureError, DecodeError
from flask import redirect, request, session
from requests_oauthlib import OAuth2Session
from requests_oauthlib.compliance_fixes import facebook_compliance_fix

from config import config_class
from ...extensions import db
from ...models.role import Role
from ...models import Role, RoleNames, TempUser, Trendit3User, Address, Profile, OneTimeToken, ReferralHistory, Membership, Wallet, UserSettings, SocialLinks
from ...models.membership import Membership
from ...models.payment import Wallet
from ...utils.helpers.loggers import console_log, log_exception
from ...utils.helpers.basic_helpers import generate_random_string
from ...utils.helpers.response_helpers import error_response, success_response
from ...utils.helpers.user_helpers import get_trendit3_user_by_google_id
from ...utils.helpers.location_helpers import get_currency_info
from ...utils.helpers.auth_helpers import generate_six_digit_code, send_code_to_email, save_pwd_reset_token
from ...utils.helpers.user_helpers import is_user_exist, get_trendit3_user, referral_code_exists
from ...utils.helpers.mail_helpers import send_other_emails, send_code_to_email



# Facebook OAuth configuration
FB_CLIENT_ID = config_class.FB_CLIENT_ID
FB_CLIENT_SECRET = config_class.FB_CLIENT_SECRET

# Facebook OAuth endpoints
FB_AUTHORIZATION_BASE_URL = os.environ.get('FB_AUTHORIZATION_BASE_URL')
FB_TOKEN_URL = os.environ.get('FB_TOKEN_URL')
FB_LOGIN_REDIRECT_URI = f"{config_class.API_DOMAIN_NAME}/api/fb_login_callback"
FB_SIGNUP_REDIRECT_URI = f"{config_class.API_DOMAIN_NAME}/api/fb_signup_callback"


# Google OAuth configuration
GOOGLE_CLIENT_ID = config_class.GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET = config_class.GOOGLE_CLIENT_SECRET

GOOGLE_SIGNUP_REDIRECT_URI = f"{config_class.API_DOMAIN_NAME}/api/gg_signup_callback"
GOOGLE_SIGNUP_REDIRECT_URI_APP = f"{config_class.API_DOMAIN_NAME}/api/app/gg_signup_callback"
GOOGLE_LOGIN_REDIRECT_URI = f"{config_class.API_DOMAIN_NAME}/api/gg_login_callback"
GOOGLE_LOGIN_REDIRECT_URI_APP = f"{config_class.API_DOMAIN_NAME}/api/app/gg_login_callback"

# Google OAuth endpoints
GOOGLE_AUTHORIZATION_BASE_URL = 'https://accounts.google.com/o/oauth2/auth'
GOOGLE_TOKEN_URL = 'https://accounts.google.com/o/oauth2/token'
GOOGLE_USER_INFO_URL = 'https://www.googleapis.com/oauth2/v1/userinfo'


class SocialAuthController:

    @staticmethod
    def fb_signup():

        try:
            facebook = OAuth2Session(FB_CLIENT_ID, redirect_uri=FB_SIGNUP_REDIRECT_URI)
            facebook = facebook_compliance_fix(facebook)
            authorization_url, state = facebook.authorization_url(FB_AUTHORIZATION_BASE_URL)

            # Save the state to compare it in the callback
            session['oauth_state'] = state

            return redirect(authorization_url)
        
        except Exception as e:
            msg = f'An error occurred while logging in through facebook: {e}'
            log_exception("An error occurred while logging in through facebook ", e)
            status_code = 500
            return error_response(msg, status_code)
        
    @staticmethod
    def fb_signup_callback():
        try:
            facebook = OAuth2Session(FB_CLIENT_ID, redirect_uri=FB_SIGNUP_REDIRECT_URI)
            token = facebook.fetch_token(FB_TOKEN_URL, client_secret=FB_CLIENT_SECRET, authorization_response=request.url)

            # Use the token to make a request to the Facebook Graph API to get user data
            graph_api_url = 'https://graph.facebook.com/me'
            params = {'access_token': token['access_token'], 'fields': 'id,name,email'}
            response = requests.get(graph_api_url, params=params)

            if response.status_code == 200:
                user_data = response.json()
                email = user_data.get('email', '')

                if not email:
                    return error_response('Facebook account not linked to an email. Email is required', 400)

                if Trendit3User.query.filter_by(email=email).first():
                    return error_response('Email already taken', 409)

                firstname = user_data.get('name', '').split()[0]
                lastname = user_data.get('name', '').split()[1] if len(user_data.get('name', '').split()) > 1 else ''
                username = generate_random_string(12)

                while Trendit3User.query.filter_by(username=username).first():
                    username = generate_random_string(12)

                new_user = Trendit3User(email=email, username=username)
                new_user_profile = Profile(trendit3_user=new_user, firstname=firstname, lastname=lastname)
                new_user_address = Address(trendit3_user=new_user)
                new_membership = Membership(trendit3_user=new_user)
                new_user_wallet = Wallet(trendit3_user=new_user)
                new_user_setting = UserSettings(trendit3_user=new_user)
                role = Role.query.filter_by(name=RoleNames.CUSTOMER).first()
                if role:
                    new_user.roles.append(role)

                db.session.add_all([new_user, new_user_profile, new_user_address, new_membership, new_user_wallet, new_user_setting])
                db.session.commit()

                user_data = new_user.to_dict()

                referral = ReferralHistory.query.filter_by(email=email).first()
                if referral:
                    referral.update(username=username, status='registered', date_joined=new_user.date_joined)

                # Create access token
                access_token = create_access_token(identity=new_user.id, expires_delta=timedelta(minutes=1440), additional_claims={'type': 'access'})

                # Send Welcome Email
                try:
                    send_other_emails(email, email_type='welcome')  # send Welcome message to user's email
                except Exception as e:
                    log_exception(f"Error sending Email", e)
                    return error_response(f'An error occurred while sending the verification email: {str(e)}', 500)

                db.session.close()

                return redirect(f"{config_class.APP_DOMAIN_NAME}/?access_token={access_token}")

            else:
                return error_response('Error occurred processing the request. Response from Facebook was not ok', 500)

        except IntegrityError as e:
            db.session.rollback()
            log_exception('Integrity Error:', e)
            return error_response(f'User already exists: {str(e)}', 409)

        except (DataError, DatabaseError) as e:
            db.session.rollback()
            log_exception('Database error occurred during registration', e)
            return error_response('Error interacting with the database.', 500)

        except Exception as e:
            db.session.rollback()
            log_exception('An error occurred during registration', e)
            return error_response(f'An error occurred while processing the request: {str(e)}', 500)

        finally:
            db.session.close()



    @staticmethod
    def fb_login():

        try:
            facebook = OAuth2Session(FB_CLIENT_ID, redirect_uri=FB_LOGIN_REDIRECT_URI)
            facebook = facebook_compliance_fix(facebook)
            authorization_url, state = facebook.authorization_url(FB_AUTHORIZATION_BASE_URL)

            # Save the state to compare it in the callback
            session['oauth_state'] = state

            return redirect(authorization_url)
        
        except Exception as e:
            msg = f'An error occurred while logging in through facebook: {e}'
            log_exception("An error occured while logging in through facebook ", e)
            status_code = 500
            return error_response(msg, status_code)
        
    @staticmethod
    def fb_login_callback():
        # Check for CSRF attacks
        # if request.args.get('state') != session.pop('oauth_state', None):
        #     return 'Invalid state'

        try:
            facebook = OAuth2Session(FB_CLIENT_ID, redirect_uri=FB_LOGIN_REDIRECT_URI)
            token = facebook.fetch_token(FB_TOKEN_URL, client_secret=FB_CLIENT_SECRET, authorization_response=request.url)

            # Use the token to make a request to the Facebook Graph API to get user data
            graph_api_url = 'https://graph.facebook.com/me'
            params = {'fields': 'id,name,email', 'access_token': token['access_token']}
            response = requests.get(graph_api_url, params=params)

            if response.status_code == 200:
                user_data = response.json()
                email = user_data.get('email')
                if not email:
                    error_response('Facebook account does not provide an email.', 401)
                    return redirect(f"{config_class.APP_DOMAIN_NAME}/login?error=Facebook_account_does_not_provide_an_email")

                # Attempt to find the user by email
                user = get_trendit3_user(email)
                if not user:
                    error_response('Facebook account is incorrect or doesn\'t exist in our records', 401)
                    return redirect(f"{config_class.APP_DOMAIN_NAME}/login?error=Facebook_Account_is_incorrect_or_does_not_exist_in_our_records")

                # Assuming create_access_token is a method that creates JWT tokens
                access_token = create_access_token(identity=user.id, expires_delta=timedelta(minutes=1440), additional_claims={'type': 'access'})

                db.session.close()  # It is good practice to close the session when done.
                success_response('Logged in successfully', 200)
                
                return redirect(f"{config_class.APP_DOMAIN_NAME}/login?access_token={access_token}")
            else:
                error_response('Error occurred processing the Facebook API response.', 500)
                return redirect(f"{config_class.APP_DOMAIN_NAME}/login?error=Error_occurred_processing_the_Facebook_API_response")

        except Exception as e:
            log_exception(f"An error occurred during Facebook login", e)
            error_response(f'An unexpected error occurred processing the request: {str(e)}', 500)
            return redirect(f"{config_class.APP_DOMAIN_NAME}/login?error=An_unexpected_error_occurred_processing_the_request")



    @staticmethod
    def tiktok_signup():

        try:
            csrf_state = str(random.random())[2:]
            response = make_response()
            response.set_cookie('csrfState', csrf_state, max_age=60000)

            url = 'https://www.tiktok.com/v2/auth/authorize/'

            # the following params need to be in `application/x-www-form-urlencoded` format.
            url += '?client_key={}'.format(os.environ.get('TIKTOK_CLIENT_KEY'))
            url += '&scope=user.info.basic'
            url += '&response_type=code'
            url += '&redirect_uri={}'.format(request.url_root[:-1] + '/tt_callback') # figure out how to get the redirect uri
            url += '&state=' + csrf_state

            return redirect(url)
        
        except Exception as e:
            msg = f'An error occurred while logging in through tiktok'
            log_exception("An error occured while logging in through tiktok ", e)
            status_code = 500
            return error_response(msg, status_code)

    @staticmethod
    def tiktok_signup_callback():

        try:
            user_data = request.get_json()
            # code = data.get('code')
            # scope = data.get('scope')
            # state = data.get('state')
            # error = data.get('error')
            extra_data = {"user_data": user_data}
            # change this to actually log in the user
            return success_response('User messages fetched successfully', 200, extra_data)
        
        except Exception as e:
            msg = f'An error occurred while fetching user data from tiktok: {e}'
            log_exception("An error occured while fetching user data from tiktok ", e)
            status_code = 500
            return error_response(msg, status_code)


    @staticmethod
    def tiktok_login():

        try:
            csrf_state = str(random.random())[2:]
            response = make_response()
            response.set_cookie('csrfState', csrf_state, max_age=60000)

            url = 'https://www.tiktok.com/v2/auth/authorize/'

            # the following params need to be in `application/x-www-form-urlencoded` format.
            url += '?client_key={}'.format(os.environ.get('TIKTOK_CLIENT_KEY'))
            url += '&scope=user.info.basic'
            url += '&response_type=code'
            url += '&redirect_uri={}'.format(request.url_root[:-1] + '/tt_callback') # figure out how to get the redirect uri
            url += '&state=' + csrf_state

            return redirect(url)
        
        except Exception as e:
            msg = f'An error occurred while logging in through tiktok: {e}'
            log_exception("An error occured while logging in through tiktok ", e)
            status_code = 500
            return error_response(msg, status_code)

    @staticmethod
    def tiktok_login_callback():

        try:
            user_data = request.get_json()
            # code = data.get('code')
            # scope = data.get('scope')
            # state = data.get('state')
            # error = data.get('error')
            extra_data = {"user_data": user_data}
            # change this to actually log in the user
            return success_response('User messages fetched successfully', 200, extra_data)
        
        except Exception as e:
            msg = f'An error occurred while fetching user data from tiktok: {e}'
            log_exception("An error occured while fetching user data from tiktok ", e)
            status_code = 500
            return error_response(msg, status_code)

    
    @staticmethod
    def google_signup():
        google = OAuth2Session(GOOGLE_CLIENT_ID, redirect_uri=GOOGLE_SIGNUP_REDIRECT_URI, scope=['profile', 'email'])
        authorization_url, state = google.authorization_url(GOOGLE_AUTHORIZATION_BASE_URL, access_type='offline') # offline for refresh token

        # Save the state to compare it in the callback
        session['oauth_state'] = state

        # return redirect(authorization_url)
        extra_data = {'authorization_url': authorization_url}
        # print(authorization_url)
        return success_response("Successful: redirect the user to the authorization url", 200, extra_data)

    @staticmethod
    def google_signup_callback():
        # Check for CSRF attacks
        # if request.args.get('state') != session.pop('oauth_state', None):
        #     return 'Invalid state'

        try:

            google = OAuth2Session(GOOGLE_CLIENT_ID, redirect_uri=GOOGLE_SIGNUP_REDIRECT_URI)
            token = google.fetch_token(GOOGLE_TOKEN_URL, client_secret=GOOGLE_CLIENT_SECRET, authorization_response=request.url)

            # Use the token to make a request to the Google API to get user data
            response = google.get(GOOGLE_USER_INFO_URL)

            if response.status_code == 200:
                user_google_data = response.json()
                print(user_google_data)
                # Return the user's data (you can customize this response as needed)
                email = user_google_data['email'] # not using .get() here because this compulsorily has to work
                
                if not email:
                    error_response('Email is required', 400)
                    return redirect(f"{config_class.APP_DOMAIN_NAME}/?error=Email_is_required")

                if Trendit3User.query.filter_by(email=email).first():
                    error_response('Email already taken', 409)
                    return redirect(f"{config_class.APP_DOMAIN_NAME}/?error=User_already_exists")
                
                console_log("user google data", user_google_data)
                
                firstname = user_google_data.get('given_name', '')
                lastname = user_google_data.get('family_name', '')
                username = f"{firstname}_{generate_random_string(2)}_{lastname}"

                while (Trendit3User.query.filter_by(username=username).first()):
                    username = generate_random_string(12)

                new_user = Trendit3User(email=email, username=username)
                new_user_profile = Profile(trendit3_user=new_user, firstname=firstname, lastname=lastname)
                new_user_address = Address(trendit3_user=new_user)
                new_membership = Membership(trendit3_user=new_user)
                new_user_wallet = Wallet(trendit3_user=new_user)
                new_user_setting = UserSettings(trendit3_user=new_user)
                new_user_social_links = SocialLinks(trendit3_user=new_user)
                
                role = Role.query.filter_by(name=RoleNames.CUSTOMER).first()
                if role:
                    new_user.roles.append(role)

                db.session.add_all([
                    new_user,
                    new_user_profile,
                    new_user_address,
                    new_membership,
                    new_user_wallet,
                    new_user_setting,
                    new_user_social_links
                ])
                
                db.session.commit()

                user_data = new_user.to_dict()
            
                referral = ReferralHistory.query.filter_by(email=email).first()
                if referral:
                    referral.update(username=username, status='registered', date_joined=new_user.date_joined)
                
                # create access token.
                access_token = create_access_token(identity=new_user.id, expires_delta=timedelta(minutes=131400), additional_claims={'type': 'access'})
                
                # Send Welcome Email
                try:
                    send_other_emails(email, email_type='welcome') # send Welcome message to user's email
                except Exception as e:
                    log_exception(f"Error sending Email", e)
                    return error_response(f'An error occurred while sending the verification email: {str(e)}', 500)

                return redirect(f"{config_class.APP_DOMAIN_NAME}/?access_token={access_token}")
            
            else:
                error_response('Error occurred processing the request. Response from google was not ok', 500)
                return redirect(f"{config_class.APP_DOMAIN_NAME}/?error=Error_occurred_processing_the_request")
                
        except IntegrityError as e:
            db.session.rollback()
            log_exception('Integrity Error:', e)
            error_response(f'User already exists: {str(e)}', 409)
            return redirect(f"{config_class.APP_DOMAIN_NAME}/?error=User_already_exists")
        
        except (DataError, DatabaseError) as e:
            db.session.rollback()
            log_exception('Database error occurred during registration', e)
            error_response('Error interacting with the database.', 500)
            return redirect(f"{config_class.APP_DOMAIN_NAME}/?error=Error_interacting_with_the_database")
            
        except Exception as e:
            db.session.rollback()
            log_exception('An error occurred during registration', e)
            error_response(f'An error occurred while processing the request: {str(e)}', 500)
            return redirect(f"{config_class.APP_DOMAIN_NAME}/?error=An_error_occurred_while_processing_the_request")
            
        finally:
            db.session.close()


    
    @staticmethod
    def google_login():
        google = OAuth2Session(GOOGLE_CLIENT_ID, redirect_uri=GOOGLE_LOGIN_REDIRECT_URI, scope=['profile', 'email'])
        authorization_url, state = google.authorization_url(GOOGLE_AUTHORIZATION_BASE_URL, access_type='offline') # offline for refresh token

        # Save the state to compare it in the callback
        session['oauth_state'] = state

        # return redirect(authorization_url)
        extra_data = {'authorization_url': authorization_url}
        # print(authorization_url)
        return success_response("Successful: redirect the user to the authorization url", 200, extra_data)
    

    @staticmethod
    def google_login_callback():
        # Check for CSRF attacks
        # if request.args.get('state') != session.pop('oauth_state', None):
        #     return 'Invalid state'

        google = OAuth2Session(GOOGLE_CLIENT_ID, redirect_uri=GOOGLE_LOGIN_REDIRECT_URI)
        token = google.fetch_token(GOOGLE_TOKEN_URL, client_secret=GOOGLE_CLIENT_SECRET, authorization_response=request.url)

        # Use the token to make a request to the Google API to get user data
        response = google.get(GOOGLE_USER_INFO_URL)

        try:

            if response.status_code == 200:
                user_data = response.json()
                # Return the user's data (you can customize this response as needed)
                id = user_data['id']
                email = user_data['email']
                # user = get_trendit3_user_by_google_id(id)
                user = get_trendit3_user(email)
                print(user)
            
                if not user:
                    error_response('Google Account is incorrect or doesn\'t exist', 401)
                    return redirect(f"{config_class.APP_DOMAIN_NAME}/login?error=Google_Account_is_incorrect_or_doesnt_exist")
                
                # # Check if user has enabled 2FA
                # user_settings = user.user_settings
                # user_security_setting = user_settings.security_setting
                # two_factor_method = user_security_setting.two_factor_method if user_security_setting else None
                
                # identity = {
                #     'username': user.username,
                #     'email': user.email,
                #     'two_factor_method': two_factor_method
                # }

                access_token = create_access_token(identity=user.id, expires_delta=timedelta(minutes=1440), additional_claims={'type': 'access'})

                db.session.close() # close the session
                msg = 'Logged in successfully'

                success_response(msg, 200)

                return redirect(f"{config_class.APP_DOMAIN_NAME}/login?access_token={access_token}")
        
        except UnsupportedMediaType as e:
            db.session.close()
            log_exception(f"An UnsupportedMediaType exception occurred", e)
            error_response(f"{str(e)}", 415)
            
            return redirect(f"{config_class.APP_DOMAIN_NAME}/login?error=UnsupportedMediaType")
            
        except Exception as e:
            db.session.close()
            log_exception(f"An exception occurred trying to login", e)
            error_response(f'An Unexpected error occurred processing the request.', 500)
            
            return redirect(f"{config_class.APP_DOMAIN_NAME}/login?error=An_Unexpected_error_occurred_processing_the_request")


    @staticmethod
    def google_login_app():
        google = OAuth2Session(GOOGLE_CLIENT_ID, redirect_uri=GOOGLE_LOGIN_REDIRECT_URI_APP, scope=['profile', 'email'])
        authorization_url, state = google.authorization_url(GOOGLE_AUTHORIZATION_BASE_URL, access_type='offline') # offline for refresh token

        # Save the state to compare it in the callback
        session['oauth_state'] = state

        # return redirect(authorization_url)
        extra_data = {'authorization_url': authorization_url}
        # print(authorization_url)
        return success_response("Successful: redirect the user to the authorization url", 200, extra_data)


    @staticmethod
    def google_login_callback_app():
        # Check for CSRF attacks
        # if request.args.get('state') != session.pop('oauth_state', None):
        #     return 'Invalid state'

        google = OAuth2Session(GOOGLE_CLIENT_ID, redirect_uri=GOOGLE_LOGIN_REDIRECT_URI_APP)
        token = google.fetch_token(GOOGLE_TOKEN_URL, client_secret=GOOGLE_CLIENT_SECRET, authorization_response=request.url)

        # Use the token to make a request to the Google API to get user data
        response = google.get(GOOGLE_USER_INFO_URL)

        try:

            if response.status_code == 200:
                user_data = response.json()
                # Return the user's data (you can customize this response as needed)
                id = user_data['id']
                email = user_data['email']
                # user = get_trendit3_user_by_google_id(id)
                user = get_trendit3_user(email)
                print(user)
            
                if not user:
                    error_response('Google Account is incorrect or doesn\'t exist', 401)
                    return redirect(f'https://blaziod.github.io/login?error=Google_Account_is_incorrect_or_doesnt_exist')
                
                # # Check if user has enabled 2FA
                # user_settings = user.user_settings
                # user_security_setting = user_settings.security_setting
                # two_factor_method = user_security_setting.two_factor_method if user_security_setting else None
                
                # identity = {
                #     'username': user.username,
                #     'email': user.email,
                #     'two_factor_method': two_factor_method
                # }

                access_token = create_access_token(identity=user.id, expires_delta=timedelta(minutes=1440), additional_claims={'type': 'access'})

                db.session.close() # close the session
                msg = 'Logged in successfully'

                success_response(msg, 200)

                return redirect(f'https://blaziod.github.io/login?access_token={access_token}')
        
        except UnsupportedMediaType as e:
            db.session.close()
            log_exception(f"An UnsupportedMediaType exception occurred", e)
            error_response(f"{str(e)}", 415)
            
            return redirect(f'https://blaziod.github.io/login?error=UnsupportedMediaType')
            
        except Exception as e:
            db.session.close()
            log_exception(f"An exception occurred trying to login", e)
            error_response(f'An Unexpected error occurred processing the request.', 500)
            
            return redirect(f'https://blaziod.github.io/login?error=An_Unexpected_error_occurred_processing_the_request')


    @staticmethod
    def google_signup_app():
        google = OAuth2Session(GOOGLE_CLIENT_ID, redirect_uri=GOOGLE_SIGNUP_REDIRECT_URI_APP, scope=['profile', 'email'])
        authorization_url, state = google.authorization_url(GOOGLE_AUTHORIZATION_BASE_URL, access_type='offline') # offline for refresh token

        # Save the state to compare it in the callback
        session['oauth_state'] = state

        # return redirect(authorization_url)
        extra_data = {'authorization_url': authorization_url}
        # print(authorization_url)
        return success_response("Successful: redirect the user to the authorization url", 200, extra_data)
    

    @staticmethod
    def google_signup_callback_app():
        # Check for CSRF attacks
        # if request.args.get('state') != session.pop('oauth_state', None):
        #     return 'Invalid state'

        try:

            google = OAuth2Session(GOOGLE_CLIENT_ID, redirect_uri=GOOGLE_SIGNUP_REDIRECT_URI_APP)
            token = google.fetch_token(GOOGLE_TOKEN_URL, client_secret=GOOGLE_CLIENT_SECRET, authorization_response=request.url)

            # Use the token to make a request to the Google API to get user data
            response = google.get(GOOGLE_USER_INFO_URL)

            if response.status_code == 200:
                user_google_data = response.json()
                print(user_google_data)
                # Return the user's data (you can customize this response as needed)
                email = user_google_data['email'] # not using .get() here beause this compulsorily has to work
                # referral_code = user_data['referral_code']
                if not email:
                    error_response('Email is required', 400)
                    return redirect(f'https://blaziod.github.io/?error=Email_is_required')

                if Trendit3User.query.filter_by(email=email).first():
                    error_response('Email already taken', 409)
                    return redirect(f'https://blaziod.github.io/?error=User_already_exists')
                
                # if referral_code and not Trendit3User.query.filter_by(username=referral_code).first():
                #     return error_response('Referral code is invalid', 404)

                # first check if user is already a temporary user.
                # user = TempUser.query.filter_by(email=email).first()
                # if user:
                #     return success_response('User registered successfully', 201, {'user_data': user.to_dict()})
                
                # temp_user = TempUser(email=email)
                # user_data = temp_user.to_dict()
                # user_google_id = user_google_data['user_id']
                firstname = user_google_data.get('given_name', '')
                lastname = user_google_data.get('family_name', '')
                username = generate_random_string(12)

                while (Trendit3User.query.filter_by(username=username).first()):
                    username = generate_random_string(12)

                new_user = Trendit3User(email=email, username=username)
                new_user_profile = Profile(trendit3_user=new_user, firstname=firstname, lastname=lastname)
                new_user_address = Address(trendit3_user=new_user)
                new_membership = Membership(trendit3_user=new_user)
                new_user_wallet = Wallet(trendit3_user=new_user)
                new_user_setting = UserSettings(trendit3_user=new_user)
                role = Role.query.filter_by(name=RoleNames.CUSTOMER).first()
                if role:
                    new_user.roles.append(role)

                
                db.session.add_all([new_user, new_user_profile, new_user_address, new_membership, new_user_wallet, new_user_setting])
                # db.session.delete(temp_user)
                
                db.session.commit()

                user_data = new_user.to_dict()
            
                referral = ReferralHistory.query.filter_by(email=email).first()
                if referral:
                    referral.update(username=username, status='registered', date_joined=new_user.date_joined)
                
                # create access token.
                access_token = create_access_token(identity=new_user.id, expires_delta=timedelta(minutes=1440), additional_claims={'type': 'access'})
                
            
                
                # Send Welcome Email
                try:
                    send_other_emails(email, email_type='welcome') # send Welcome message to user's email
                except Exception as e:
                    log_exception(f"Error sending Email", e)
                    return error_response(f'An error occurred while sending the verification email: {str(e)}', 500)


                db.session.close()
                
                # TODO: Make asynchronous
                # if 'referral_code' in user_info:
                #     referral_code = user_info['referral_code']
                #     referrer = get_trendit3_user(referral_code)
                #     referral_history = ReferralHistory.create_referral_history(email=email, status='pending', trendit3_user=referrer, date_joined=new_user.date_joined)
                
                return redirect(f'https://blaziod.github.io/?access_token={access_token}')
            
            else:
                error_response('Error occurred processing the request. Response from google was not ok', 500)
                return redirect(f'https://blaziod.github.io/?error=Error_occurred_processing_the_request')
                
        except IntegrityError as e:
            db.session.rollback()
            log_exception('Integrity Error:', e)
            error_response(f'User already exists: {str(e)}', 409)
            return redirect(f'https://blaziod.github.io/?error=User_already_exists')
        
        except (DataError, DatabaseError) as e:
            db.session.rollback()
            log_exception('Database error occurred during registration', e)
            error_response('Error interacting with the database.', 500)
            return redirect(f'https://blaziod.github.io/?error=Error_interacting_with_the_database')
            
        except Exception as e:
            db.session.rollback()
            log_exception('An error occurred during registration', e)
            error_response(f'An error occurred while processing the request: {str(e)}', 500)
            return redirect(f'https://blaziod.github.io/?error=An_error_occurred_while_processing_the_request')
            
        finally:
            db.session.close()
