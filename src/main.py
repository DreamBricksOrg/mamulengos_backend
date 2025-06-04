from flask_socketio import SocketIO, emit, join_room
from flask import Flask, url_for, send_file, render_template, redirect, request, abort, jsonify

import parameters
import utils
from log_sender import init_csv, csv_filename, backup_filename, process_csv_and_send_logs, save_csv
from qrcodeaux import generate_qr_code
from udp_sender import UDPSender
import uuid
import os
import time
import shutil
import random
from apscheduler.schedulers.background import BackgroundScheduler
import threading
#from stable_swarm_api import StableSwarmAPI
from caixa.mamulengos_backend.src.api.comfyui import ComfyUiAPI

app = Flask(__name__)
app.secret_key = 'dbsupersecretkey'
socketio = SocketIO(app)

udp_sender = UDPSender(port=parameters.UDP_PORT)

valid_links = {}

MAX_LINKS = 5

IMAGE_BASE_FOLDER = os.path.join(app.root_path, 'static', 'download_images')

init_csv(csv_filename)
init_csv(backup_filename)

#ss_api = StableSwarmAPI(parameters.STABLE_SWARM_API_URL, parameters.STABLE_SWARM_BASE_FOLDER)
ss_api = ComfyUiAPI(parameters.STABLE_SWARM_API_SERVER,
                    parameters.IMAGE_TEMP_FOLDER,
                    parameters.WORKFLOW_PATH,
                    parameters.WORKFLOW_NODE_ID_KSAMPLER,
                    parameters.WORKFLOW_NODE_ID_IMAGE_LOAD)

def remove_old_folders():
    current_time = time.time()
    directory = 'static/download_images'
    minutes = 10

    for foldername in os.listdir(directory):
        folder_path = os.path.join(directory, foldername)

        if os.path.isdir(folder_path):
            creation_time = os.path.getctime(folder_path)
            time_difference = (current_time - creation_time) / 60

            if time_difference > minutes:

                shutil.rmtree(folder_path)
                print(f'A pasta "{foldername}" foi excluída.')
            else:
                print(f'A pasta "{foldername}" foi criada há menos de {minutes} minutos.')


# scheduler = BackgroundScheduler()
# scheduler.add_job(remove_old_folders, 'interval', minutes=2)
# scheduler.start()

threading.Thread(target=process_csv_and_send_logs, args=(csv_filename, backup_filename), daemon=True).start()


@app.route('/')
def index():
    return redirect(url_for("cta"))


@app.route('/alive')
def alive():
    return "Alive"


@app.route("/cta", methods=['GET', 'POST'])
def cta():
    if request.method == "POST":
        print("Start application")
        return redirect(url_for('terms'))
    return render_template("cta.html")


@app.route('/generateqr', methods=['GET'])
def generate():
    if len(valid_links) >= MAX_LINKS:
        valid_links.clear()
        print("Lista de links esvaziada para evitar sobrecarga.")

    link_id = str(uuid.uuid4())
    link = url_for('terms', link_id=link_id, _external=True)

    valid_links[link_id] = True

    qr_img = generate_qr_code(link)

    return send_file(qr_img, mimetype='image/png')


@app.route('/qrcode-images', methods=['GET'])
def qrcode_images():
    cod = request.args.get('cod')
    if not cod:
        abort(400, description="O parâmetro 'cod' é obrigatório.")

    url = f"{parameters.BASE_URL}/show_images/{cod}"

    img_bytes = generate_qr_code(url)

    socketio.emit('render_images', {'cod': cod}, room=cod, namespace='/')

    return send_file(img_bytes, mimetype='image/png')


@app.route('/download-images')
def download_images():
    cod = request.args.get('cod')
    folder_path = os.path.join(IMAGE_BASE_FOLDER, cod)

    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
        abort(404, description="Folder not found.")

    image_files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]

    if not image_files:
        abort(404, description="No images found.")

    image_urls = [url_for('serve_image', cod=cod, filename=image, _external=True) for image in image_files]

    return jsonify(image_urls)


@app.route('/images/<cod>/<filename>')
def serve_image(cod, filename):
    folder_path = os.path.join(IMAGE_BASE_FOLDER, cod)
    file_path = os.path.join(folder_path, filename)

    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        abort(404, description="Image not found.")

    return send_file(file_path, mimetype='image/jpeg', as_attachment=True, download_name=filename)


@app.route('/show_images/<cod>')
def show_images(cod):
    images_dir = os.path.join(app.static_folder, 'download_images', cod)

    if not os.path.exists(images_dir):
        abort(404)

    image_files = [f for f in os.listdir(images_dir) if f.endswith(('.png', '.jpg', '.jpeg', '.gif'))]

    image_paths = [url_for('static', filename=f'download_images/{cod}/{image_file}') for image_file in image_files]

    udp_sender.send(f"SCAN:{cod}\n")
    save_csv("ESCANEOU_QRCODE")

    return render_template('download-images.html', image_paths=image_paths, cod=cod)


@app.route('/show_images_carousel/<cod>')
def show_images_carousel(cod):
    images_dir = os.path.join(app.static_folder, 'download_images', cod)

    if not os.path.exists(images_dir):
        abort(404)

    image_files = [f for f in os.listdir(images_dir) if f.endswith(('.png', '.jpg', '.jpeg', '.gif'))]

    image_paths = [url_for('static', filename=f'download_images/{cod}/{image_file}') for image_file in image_files]
    save_csv("MOSTROU_FOTOS")

    return render_template('download-images-carousel.html', image_paths=image_paths, cod=cod)


@app.route('/terms')
def terms():
    timer = parameters.TIMER_TERMS
    print(timer)
    return render_template('terms.html', timer=timer)


@app.route('/accept', methods=['POST'])
def accept():
    random_number = random.randint(1, 99999)
    udp_sender.send(f"INI:{random_number:05d}\n")
    return redirect(url_for('play', cod=random_number))


@app.route('/play/<cod>')
def play(cod):
    return render_template('play.html', cod=cod)


@app.route('/logs/timeout/<status>')
def send_log(status):
    save_csv(status)
    return redirect(url_for('cta'))


@app.route('/logs/finish/<status>/<additional_send>')
def finish(status, additional_send):
    save_csv(status, additional_send)
    return redirect(url_for('cta'))


def process_image(path_to_image, config_idx, out_folder):
    if not os.path.isfile(path_to_image):
        return "ERROR"

    photo = os.path.basename(path_to_image)
    out_image_filename = ss_api.generate_image(path_to_image)
    out_photo = f'cfg{config_idx:02d}_{photo.replace(".jpg", ".png")}'
    move_to_filename = os.path.join(out_folder, out_photo)

    shutil.copy(out_image_filename, move_to_filename)

    print(move_to_filename)
    print(f"UDP Sending: {move_to_filename}" )
    udp_sender.send(f"GENERATED:{move_to_filename}\n")


@app.route('/ai/<path_to_image>')
def generate_ai(path_to_image):
    config_idx = parameters.CONFIG_INDEX
    path_to_image = str(path_to_image).replace("@", "\\")

    out_folder = os.path.dirname(path_to_image)

    if not os.path.isfile(path_to_image):
        return "ERROR"

    time.sleep(0.3)
    thread = threading.Thread(target=process_image, args=(path_to_image, config_idx, out_folder))
    thread.start()

    return "PROCESSING"

@app.route('/error')
def error():
    return render_template("error.html")


@socketio.on('connect')
def handle_connect():
    print('Cliente conectado')


@socketio.on('disconnect')
def handle_disconnect():
    print('Cliente desconectado')


@socketio.on('join')
def on_join(data):
    cod = data['cod']
    join_room(cod)
    emit('status', {'msg': f'Você entrou na sala {cod}'}, room=cod)


if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', allow_unsafe_werkzeug=True, port=5000)
