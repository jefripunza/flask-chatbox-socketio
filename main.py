from flask import Flask, request, make_response, render_template, redirect
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS

import os
import time
import pickle
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
socketio = SocketIO(app, cors_allowed_origins='*')

# ===========================================================================
# ===========================================================================
# ===========================================================================

chat_history = {}
user_identity = {}

save_data_folder = 'save_data'
if not os.path.exists(save_data_folder):
    os.makedirs(save_data_folder)

chat_history_file = save_data_folder + '/chat_history.pickle'
user_identity_file = save_data_folder + '/user_identity.pickle'

# Check if pickle files exist, if not create empty ones
if not os.path.exists(chat_history_file):
    with open(chat_history_file, 'wb') as file:
        pickle.dump(chat_history, file)
else:
    with open(chat_history_file, 'rb') as file:
        chat_history = pickle.load(file)

if not os.path.exists(user_identity_file):
    with open(user_identity_file, 'wb') as file:
        pickle.dump(user_identity, file)
else:
    with open(user_identity_file, 'rb') as file:
        user_identity = pickle.load(file)


# Save chat history to pickle file
def save_chat_history():
    with open(chat_history_file, 'wb') as file:
        pickle.dump(chat_history, file)


# Save user identity to pickle file
def save_user_identity():
    with open(user_identity_file, 'wb') as file:
        pickle.dump(user_identity, file)


# ===========================================================================
# ===========================================================================
# ===========================================================================


@app.route('/')
def index():
    user_id = request.cookies.get('user_id')
    if user_id in user_identity:
        return render_template('index.html')
    else:
        response = make_response(render_template('identity.html'))
        if not user_id:
            user_id = str(uuid.uuid4())
            response.set_cookie('user_id', user_id)
        return response


@app.route('/save_identity', methods=['POST'])
def save_identity():
    user_id = request.cookies.get('user_id')
    name = request.form.get('name')
    phone_number = request.form.get('phone_number')
    user_identity[user_id] = {'user_id': user_id, 'name': name, 'phone_number': phone_number}
    with open(user_identity_file, 'wb') as file:
        pickle.dump(user_identity, file)
    return redirect('/')


@app.route('/admin')
def admin():
    response = make_response(render_template('admin.html'))
    user_id = request.cookies.get('admin_id')
    if not user_id:
        user_id = str(uuid.uuid4())
        response.set_cookie('admin_id', user_id)
    return response


# ===========================================================================
# ===========================================================================
# ===========================================================================


connected_users = set()


@socketio.on('connect', namespace='/ws/client')
def handle_connect():
    user_id = request.cookies.get('user_id')
    print("new user connect:", user_id)
    join_room(user_id)
    if user_id in connected_users:
        emit('connection_status', {"id": user_id, 'status': 'already_connected'})
    else:
        connected_users.add(user_id)
        # Inisialisasi user_identity dari pickle
        global user_identity
        with open(user_identity_file, 'rb') as file:
            user_identity = pickle.load(file)
        user_identity_values = [user for user in user_identity.values() if user['user_id'] in connected_users]
        emit('connected_clients', user_identity_values, broadcast=True, namespace='/ws/admin')
        emit('connection_status', {"id": user_id, 'status': 'connected'})
        # Kirim kembali chat history terakhir ke user
        emit('last_chat', chat_history.get(user_id, []))


@socketio.on('disconnect', namespace='/ws/client')
def handle_disconnect():
    user_id = request.cookies.get('user_id')
    leave_room(user_id)
    connected_users.remove(user_id)
    # Inisialisasi user_identity dari pickle
    global user_identity
    with open(user_identity_file, 'rb') as file:
        user_identity = pickle.load(file)
    user_identity_values = [user for user in user_identity.values() if user['user_id'] in connected_users]
    emit('connected_clients', user_identity_values, broadcast=True, namespace='/ws/admin')


@socketio.on('message', namespace='/ws/client')
def handle_message(receive):
    user_id = request.cookies.get('user_id')
    fix_receive = {
        "room": user_id,
        "sender": receive['sender'],
        "message": receive['message'],
    }
    emit('message', fix_receive, room=user_id)
    emit('admin_message', fix_receive, room=user_id, namespace='/ws/admin')
    # Save chat history
    if user_id in chat_history:
        chat_history[user_id].append(fix_receive)
    else:
        chat_history[user_id] = [fix_receive]
    save_chat_history()


# ===========================================================================
# ===========================================================================
# ===========================================================================

typing_users = set()


@socketio.on('typing_user', namespace='/ws/client')
def handle_typing_user(receive):
    user_id = request.cookies.get('user_id')
    # print("typing_user:", user_id, "typing:", receive["typing"])
    emit('typing_status', {"id": user_id, "typing": receive["typing"]}, room=user_id, namespace='/ws/admin')


@socketio.on('typing_admin', namespace='/ws/admin')
def handle_typing_admin(receive):
    admin_id = request.cookies.get('user_id')
    # print("typing_admin:", admin_id, "typing:", receive["typing"])
    emit('typing_status', {"id": admin_id, "typing": receive["typing"]}, room=receive['room'], namespace='/ws/client')


# ===========================================================================
# ===========================================================================
# ===========================================================================


@socketio.on('connect', namespace='/ws/admin')
def handle_admin_connect():
    user_id = request.cookies.get('admin_id')
    print("admin connected", user_id)
    # Inisialisasi user_identity dari pickle
    global user_identity
    with open(user_identity_file, 'rb') as file:
        user_identity = pickle.load(file)
    user_identity_values = [user for user in user_identity.values() if user['user_id'] in connected_users]
    emit('connected_clients', user_identity_values, broadcast=True, namespace='/ws/admin')
    # Kirim kembali chat history terakhir ke admin
    emit('last_chat', chat_history.get(user_id, []), namespace='/ws/admin')


@socketio.on('disconnect', namespace='/ws/admin')
def handle_admin_disconnect():
    print("admin disconnected")


@socketio.on('join_conversation', namespace='/ws/admin')
def handle_join_conversation(data):
    admin_id = request.cookies.get('admin_id')
    user_id = data['user_id']
    # Leave dari percakapan sebelumnya (jika ada)
    leave_previous_conversation(admin_id)
    join_room(user_id)
    print("admin_sid:", admin_id, "user_id:", user_id)
    emit('join_conversation', {'user_id': user_id, 'admin_id': admin_id}, room=user_id, namespace='/ws/client')
    # Kirim semua chat history terakhir dengan pengguna yang terkait
    emit('last_chat', chat_history.get(user_id, []), namespace='/ws/admin')


def leave_previous_conversation(admin_id):
    rooms = socketio.server.manager.rooms
    for room in rooms:
        if admin_id in rooms[room]:
            leave_room(room)


@socketio.on('admin_message', namespace='/ws/admin')
def handle_admin_message(receive):
    user_id = receive["room"]
    message = receive["message"]
    fix_receive = {
        "room": user_id,
        "sender": "admin",
        "message": message,
    }
    emit('admin_message', fix_receive, room=user_id, namespace='/ws/client')
    # Save chat history
    if user_id in chat_history:
        chat_history[user_id].append(fix_receive)
    else:
        chat_history[user_id] = [fix_receive]
    save_chat_history()


# ===========================================================================
# ===========================================================================
# ===========================================================================


if __name__ == '__main__':
    socketio.run(app)
