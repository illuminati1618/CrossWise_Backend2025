import jwt
from flask import Blueprint, request, jsonify, current_app, Response, g
from flask_restful import Api, Resource  # used for REST API building
from datetime import datetime
from __init__ import app
from api.jwt_authorize import token_required
from model.user import User

# Create a Blueprint for the user API
user_api = Blueprint('user_api', __name__, url_prefix='/api')

# Create an Api object and associate it with the Blueprint
# API docs: https://flask-restful.readthedocs.io/en/latest/api.html
api = Api(user_api)

class UserAPI:
    """
    Define the API endpoints for the User model.
    """
    class _BULK_CRUD(Resource):
        """
        Users API operation for bulk Create and Read.
        """

        def post(self):
            """
            Handle bulk user creation by sending POST requests to the single user endpoint.
            """
            users = request.get_json()

            if not isinstance(users, list):
                return {'message': 'Expected a list of user data'}, 400

            results = {'errors': [], 'success_count': 0, 'error_count': 0}

            with current_app.test_client() as client:
                for user in users:
                    # Set a default password as we don't have it for bulk creation
                    user["password"] = app.config['DEFAULT_PASSWORD']

                    # Simulate a POST request to the single user creation endpoint
                    response = client.post('/api/user', json=user)

                    if response.status_code == 200:
                        results['success_count'] += 1
                    else:
                        results['errors'].append(response.get_json())
                        results['error_count'] += 1

            return jsonify(results)
        
        @token_required()
        def get(self):
            """
            Retrieve all users.
            """
            current_user = g.current_user
            users = User.query.all()  # extract all users from the database

            # Prepare a JSON list of user dictionaries
            json_ready = []
            for user in users:
                user_data = user.read()
                if current_user.role == 'Admin' or current_user.id == user.id:
                    user_data['access'] = ['rw']  # read-write access control
                else:
                    user_data['access'] = ['ro']  # read-only access control
                json_ready.append(user_data)

            return jsonify(json_ready)

    class _CRUD(Resource):
        """
        Users API operation for Create, Read, Update, Delete.
        """

        def post(self):
            body = request.get_json()
            name = body.get('name')
            if name is None or len(name) < 2:
                return {'message': 'Name is missing, or is less than 2 characters'}, 400

            uid = body.get('uid')
            if uid is None or len(uid) < 2:
                return {'message': 'User ID is missing, or is less than 2 characters'}, 400

            email = body.get('email', '')   # Optional
            phone = body.get('phone', '')   # Optional
            followers = body.get('followers', '')

            user_obj = User(name=name, uid=uid, email=email, phone=phone, followers=followers)

            user = user_obj.create(body)
            if not user:
                return {'message': f'Processed {name}, either a format error or User ID {uid} is duplicate'}, 400

            return jsonify(user.read())

        
        @token_required()
        def get(self):
            """
            Return the current user and return as a JSON object.
            """
            user = g.current_user
            user_data = user.read()
            return jsonify(user_data)

        @token_required()
        def put(self):
            """
            Update a user.
            """
            current_user = g.current_user
            body = request.get_json()

            # Admin-specific update handling
            if current_user.role == 'Admin':
                uid = body.get('uid')
                if uid is None or uid == current_user.uid:
                    user = current_user  # Admin is updating themselves
                else:
                    user = User.query.filter_by(_uid=uid).first()
                    if user is None:
                        return {'message': f'User {uid} not found'}, 404
            else:
                user = current_user  # Non-admin can only update themselves

            # Check if followers exist before updating
            if 'followers' in body:
                new_followers = body['followers'].split(',')
                valid_followers = []
                for follower in new_followers:
                    follower = follower.strip()
                    if User.query.filter_by(_uid=follower).first():
                        valid_followers.append(follower)
                    else:
                        return {'message': f'Follower {follower} does not exist'}, 400
                body['followers'] = ', '.join(valid_followers)

            # Update the user object with the new data
            user.update(body)

            return jsonify(user.read())

        @token_required("Admin")
        def delete(self):
            """
            Delete a user.
            """
            body = request.get_json()
            uid = body.get('uid')
            user = User.query.filter_by(_uid=uid).first()
            if user is None:
                return {'message': f'User {uid} not found'}, 404
            json = user.read()
            user.delete()
            return f"Deleted user: {json}", 204  # use 200 to test with Postman

    class _Security(Resource):
        """
        Security-related API operations.
        """

        def post(self):
            """
            Authenticate a user and generate a JWT token.
            """
            try:
                body = request.get_json()
                if not body:
                    return {
                        "message": "Please provide user details",
                        "data": None,
                        "error": "Bad request"
                    }, 400

                # Get Data
                uid = body.get('uid')
                if uid is None:
                    return {'message': 'User ID is missing'}, 401
                password = body.get('password')
                if not password:
                    return {'message': 'Password is missing'}, 401

                # Find user
                user = User.query.filter_by(_uid=uid).first()

                if user is None or not user.is_password(password):
                    return {'message': "Invalid user id or password"}, 401

                # Generate token
                token = jwt.encode(
                    {"_uid": user._uid},
                    current_app.config["SECRET_KEY"],
                    algorithm="HS256"
                )
                resp = Response(f"Authentication for {user._uid} successful")
                resp.set_cookie(
                    current_app.config["JWT_TOKEN_NAME"],
                    token,
                    max_age=3600,
                    secure=True,
                    httponly=True,
                    path='/',
                    samesite='None'  # This is the key part for cross-site requests
                )
                return resp
            except Exception as e:
                return {
                    "error": "Something went wrong",
                    "message": str(e)
                }, 500

        @token_required()
        def delete(self):
            """
            Invalidate the current user's token by setting its expiry to 0.
            """
            current_user = g.current_user
            try:
                # Generate a token with practically 0 age
                token = jwt.encode(
                    {"_uid": current_user._uid, "exp": datetime.utcnow()},
                    current_app.config["SECRET_KEY"],
                    algorithm="HS256"
                )

                # Prepare a response indicating the token has been invalidated
                resp = Response("Token invalidated successfully")
                resp.set_cookie(
                    current_app.config["JWT_TOKEN_NAME"],
                    token,
                    max_age=0,  # Immediately expire the cookie
                    secure=True,
                    httponly=True,
                    path='/',
                    samesite='None'
                )
                return resp
            
            except Exception as e:
                return {
                    "message": "Failed to invalidate token",
                    "error": str(e)
                }, 500
    class _ID(Resource):  # Individual identification API operation
        @token_required()
        def get(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user
            ''' Return the current user as a json object '''
            return jsonify(current_user.read())
        
    class _Followers(Resource):
        @token_required()
        def get(self):
            """
            Return the followers of the authenticated user as a JSON object.
            """
            current_user = g.current_user
            followers = current_user.followers
            if not followers:
                return {'message': 'No followers found for this user'}, 404
            return jsonify(followers)

    class _Following(Resource):
        @token_required()
        def get(self):
            """
            Return the users that the authenticated user is following as a JSON object.
            """
            current_user = g.current_user
            following = User.query.filter(User._followers.contains(current_user.uid)).all()
            following_list = [user.uid for user in following]
            if not following_list:
                return {'message': 'No users found that you are following'}, 404
            return jsonify(following_list)
    
    
    
    
    class _MutualConnections(Resource):
        @token_required()
        def get(self):
            """
            Return the mutual connections of the authenticated user as a JSON object.
            """
            current_user = g.current_user
            followers = [f.strip() for f in current_user.followers.split(',')] if current_user.followers else []
            mutual_connections = {}

            for follower_uid in followers:
                follower = User.query.filter_by(_uid=follower_uid).first()
                if follower and follower.followers:
                    follower_followers = [f.strip() for f in follower.followers.split(',')]
                    for mutual_follower_uid in follower_followers:
                        if mutual_follower_uid in followers and mutual_follower_uid != current_user.uid:
                            if follower_uid not in mutual_connections:
                                mutual_connections[follower_uid] = []
                            mutual_connections[follower_uid].append(mutual_follower_uid)

            return jsonify(mutual_connections)
# Register the API resources with the Blueprint
api.add_resource(UserAPI._ID, '/id')
api.add_resource(UserAPI._BULK_CRUD, '/users')
api.add_resource(UserAPI._CRUD, '/user')
api.add_resource(UserAPI._Security, '/authenticate')
api.add_resource(UserAPI._Followers, '/followers')
api.add_resource(UserAPI._Following, '/following')
api.add_resource(UserAPI._MutualConnections, '/mutual_connections')

