from flask import Flask, request, make_response, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS

import time
import uuid
from flask.logging import logging
from dotenv import load_dotenv

load_dotenv()


class LogFilter(logging.Filter):
    def filter(self, record):
        return not any(keyword in record.getMessage() for keyword in ["/socket.io", "transport"])


logging.getLogger("werkzeug").addFilter(LogFilter())

app = Flask(__name__)
CORS(app, origins='*')
app.config['SECRET_KEY'] = 'secret_key'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = False
socketio = SocketIO(app)


@app.route('/')
def index():
    response = make_response(render_template('index.html'))
    user_id = request.cookies.get('user_id')
    if not user_id:
        user_id = str(uuid.uuid4())
        response.set_cookie('user_id', user_id)
    return response


@socketio.on('connect', namespace='/ws/client')
def handle_connect():
    user_id = request.cookies.get('user_id')
    print("new user connect:", user_id)
    join_room(user_id)


@socketio.on('disconnect', namespace='/ws/client')
def handle_disconnect():
    user_id = request.cookies.get('user_id')
    leave_room(user_id)


typing_users = set()


@socketio.on('message', namespace='/ws/client')
def handle_message(receive):
    user_id = request.cookies.get('user_id')
    print("cookie:", user_id, "| message:", receive)
    emit('message', receive, room=user_id)
    message = receive["message"]
    if message in ["ping", "hi", "hai", "halo", "mantap"] and user_id not in typing_users:
        typing_users.add(user_id)
        emit('typing_status', {"id": user_id, "typing": True}, room=user_id)
        time.sleep(2)
        typing_users.remove(user_id)
        emit('typing_status', {"id": user_id, "typing": False}, room=user_id)
        if message == "ping":
            emit('message', {"message": "Pong!", "sender": "server"}, room=user_id)
        elif message in ["hi", "hai", "hei", "halo", "hallo" "helo", "hello"]:
            emit('message', {"message": "Hai!", "sender": "server"}, room=user_id)
        elif message == "mantap":
            emit('message', {"message": "Jiwa!", "sender": "server"}, room=user_id)


if __name__ == '__main__':
    socketio.run(app)
