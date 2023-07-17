from flask import Flask, request, make_response, render_template, redirect, flash
from flask.logging import logging
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS

import os, json, datetime, uuid
from pymongo import MongoClient

from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.environ.get('DATABASE_URL'))
db = client[os.environ.get('DATABASE_NAME')]

# ===========================================================================
# for System
auto_increment = db['auto_increment']

# ===========================================================================
# for Admin
users = db['users']  # admin
users.create_index("id", unique=True)

admin_identity = db['admin_identity']  # admin cookies collection
admin_identity.create_index("admin_id", unique=True)

# ===========================================================================
# for Guest
user_identity = db['user_identity']
user_identity.create_index("user_id", unique=True)

chat_history = db['chat_history']
chat_history.create_index("message_id", unique=True)


# ===========================================================================
# ===========================================================================
# ===========================================================================


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


@app.template_filter('fromjson')
def fromjson_filter(value):
    try:
        data = json.loads(value)
        return data
    except json.JSONDecodeError:
        return None


def json_converter(obj):
    if isinstance(obj, datetime.datetime):
        return obj.__str__()


# Get next auto increment value from MongoDB
def get_next_auto_increment_value(sequence_name):
    sequence_document = auto_increment.find_one_and_update(
        {'_id': sequence_name},
        {'$inc': {'sequence_value': 1}},
        return_document=True,
        upsert=True
    )
    return sequence_document['sequence_value']


def leave_previous_conversation(id):
    rooms = socketio.server.manager.rooms
    for room in rooms:
        if id in rooms[room]:
            leave_room(room)


# ===========================================================================
# ===========================================================================
# ===========================================================================


@app.route('/')
def index():
    user_id = request.cookies.get('user_id')
    user_identity_data = user_identity.find_one({'user_id': user_id})
    if user_identity_data:
        if 'name' in user_identity_data:
            return render_template('index.html')  # halaman chatbox

    response = make_response(render_template('identity.html'))  # halaman isi identitas...
    if not user_id:
        user_id = str(uuid.uuid4())  # buatkan user_id
        response.set_cookie('user_id', user_id)
    if not user_identity_data:
        user_identity.insert_one({  # buatkan sementara, sebelum data complete...
            'user_id': user_id,
            'created_at': datetime.datetime.now()
        })
    return response


@app.route('/save_identity', methods=['POST'])
def save_identity():
    user_id = request.cookies.get('user_id')
    if not user_id:  # biasanya di hit langsung melalui API tanpa membuat cookie terlebih dahulu
        return make_response(json.dumps({
            "message": "please create cookie first! go to homepage..."
        }), 400)

    name = request.form.get('name')
    phone_number = request.form.get('phone_number')

    user_identity.update_one({'user_id': user_id}, {'$set': {  # penyempurnaan identitas, complete!
        'name': name,
        'phone_number': phone_number,
    }})
    return redirect('/')


@app.route('/admin')
def admin():
    admin_id = request.cookies.get('admin_id')
    admin_identity_data = admin_identity.find_one({'admin_id': admin_id})
    if admin_identity_data and 'id' in admin_identity_data:
        user_match = users.find_one({'id': admin_identity_data['id']})
        if user_match:
            return render_template('admin.html')  # logged
    response = make_response(render_template('admin-identity.html'))  # halaman isi identity admin...
    if not admin_id:
        admin_id = str(uuid.uuid4())
        response.set_cookie('admin_id', admin_id)
        admin_identity.insert_one({
            'admin_id': admin_id,
            'created_at': datetime.datetime.now(),
        })
    return response


@app.route('/admin_save_identity', methods=['POST'])
def admin_save_identity():
    admin_id = request.cookies.get('admin_id')
    if not admin_id:  # biasanya di hit langsung melalui API tanpa membuat cookie terlebih dahulu
        return make_response(json.dumps({
            "message": "please create cookie first! go to homepage..."
        }), 400)

    name = request.form.get('name')
    username = request.form.get('username')
    password = request.form.get('password')

    admin_exist = users.find_one({'username': username})
    if admin_exist:
        flash(str({
            "color": "text-red-500",
            "message": "username sudah terdaftar...",
        }))
        return redirect('/admin')

    id = get_next_auto_increment_value('users')
    users.insert_one({
        'id': id,
        'name': name,
        'username': username,
        'password': password,
        'created_at': datetime.datetime.now(),
    })
    admin_identity.update_one({'admin_id': admin_id}, {'$set': {  # penyempurnaan identitas, complete!
        'id': id,
    }})
    return redirect('/admin')


@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    admin_id = request.cookies.get('admin_id')
    admin_identity_data = admin_identity.find_one({'admin_id': admin_id})
    if admin_identity_data and 'id' in admin_identity_data:
        user_match = users.find_one({'id': admin_identity_data['id']})
        if user_match:
            return redirect('/admin')  # ngapain daftar, login lah...

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        is_login = users.find_one({
            'username': username,
            'password': password,
        })
        if not is_login:
            flash(str({
                "color": "text-red-500",
                "message": "username atau password salah...",
            }))
            return redirect('/admin_login')

        admin_identity.update_one({'admin_id': admin_id}, {'$set': {  # penyempurnaan identitas, complete!
            'id': is_login['id'],
        }})
        return redirect('/admin')

    return render_template('admin-login.html')


# ===========================================================================
# ===========================================================================
# ===========================================================================


connected_users = set()


def update_connections():
    user_identity_connects = [user for user in user_identity.find({
        'user_id': {'$in': list(connected_users)}
    }, {"_id": 0})]
    user_identity_connects = json.dumps(user_identity_connects, default=json_converter)
    user_identity_connects = json.loads(user_identity_connects)
    emit('connected_clients', user_identity_connects, broadcast=True, namespace='/ws/admin')


@socketio.on('connect', namespace='/ws/client')
def handle_connect():
    user_id = request.cookies.get('user_id')
    print("new user connect:", user_id)
    join_room(user_id)
    if user_id in connected_users:
        emit('connection_status', {"id": user_id, 'status': 'already_connected'})
    else:
        connected_users.add(user_id)
        update_connections()
        # Kirim kembali chat history terakhir ke user
        last_chat = list(chat_history.find({
            'room': user_id,
        }, {"_id": 0}))
        emit('last_chat', last_chat)


@socketio.on('disconnect', namespace='/ws/client')
def handle_disconnect():
    user_id = request.cookies.get('user_id')
    leave_room(user_id)
    connected_users.remove(user_id)
    update_connections()


@socketio.on('connect', namespace='/ws/admin')
def handle_admin_connect():
    user_id = request.cookies.get('admin_id')
    print("admin connected", user_id)
    update_connections()


@socketio.on('disconnect', namespace='/ws/admin')
def handle_admin_disconnect():
    print("admin disconnected")


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
    admin_id = request.cookies.get('admin_id')
    # print("typing_admin:", admin_id, "typing:", receive["typing"])
    emit('typing_status', {"id": admin_id, "typing": receive["typing"]}, room=receive['room'], namespace='/ws/client')


# ===========================================================================
# ===========================================================================
# ===========================================================================


@socketio.on('join_conversation', namespace='/ws/admin')
def handle_join_conversation(data):
    admin_id = request.cookies.get('admin_id')
    user_id = data['user_id']
    # Leave dari percakapan sebelumnya (jika ada)
    leave_previous_conversation(admin_id)
    join_room(user_id)
    print("join_conversation admin to user, admin_id:", admin_id, "user_id:", user_id)
    emit('join_conversation', {'user_id': user_id, 'admin_id': admin_id}, room=user_id, namespace='/ws/client')
    last_chat = list(chat_history.find({
        'room': user_id,
    }, {"_id": 0}))
    emit('last_chat', last_chat, namespace='/ws/admin')


@socketio.on('message', namespace='/ws/client')
def handle_message(receive):
    fix_receive = False
    user_id = request.cookies.get('user_id')
    type = receive["type"]
    if type == "text":
        message = receive["message"]
        fix_receive = {
            "message_id": str(uuid.uuid4()),
            "sender": "user",
            "room": user_id,
            "message": message,
            'created_at': datetime.datetime.now(),
        }

    if fix_receive:
        fix_receive = json.dumps(fix_receive, default=json_converter)
        fix_receive = json.loads(fix_receive)
        emit('message', fix_receive, room=user_id)
        emit('admin_message', fix_receive, room=user_id, namespace='/ws/admin')
        # Save chat history
        chat_history.insert_one(fix_receive)


@socketio.on('admin_message', namespace='/ws/admin')
def handle_admin_message(receive):
    fix_receive = False
    user_id = receive["room"]
    type = receive["type"]
    if type == "text":
        message = receive["message"]
        fix_receive = {
            "message_id": str(uuid.uuid4()),
            "sender": "admin",
            "room": user_id,
            "message": message,
            'created_at': datetime.datetime.now(),
        }

    if fix_receive:
        fix_receive = json.dumps(fix_receive, default=json_converter)
        fix_receive = json.loads(fix_receive)
        emit('admin_message', fix_receive, room=user_id, namespace='/ws/client')
        # Save chat history
        chat_history.insert_one(fix_receive)


# ===========================================================================
# ===========================================================================
# ===========================================================================


if __name__ == '__main__':
    socketio.run(app)
