import websocket
import requests
import uuid
import json
import urllib.request
import urllib.parse
import random
import datetime
from PIL import Image
import io
import os
import copy
from utils import generate_timestamped_filename
import comfyui_api_utils
import time
import logging

logger = logging.getLogger(__name__)


class ComfyUiAPI:
    def __init__(self, server_address, img_temp_folder, workflow_path, node_id_ksampler, node_id_image_load, node_id_text_input):
        self.server_address = server_address
        self.img_temp_folder = img_temp_folder
        self.node_id_ksampler = node_id_ksampler
        self.node_id_image_load = node_id_image_load
        self.node_id_text_input = node_id_text_input
        self.session = requests.Session()  # conexão HTTP reutilizável

        # Carrega workflow uma vez e usa cópia depois
        with open(workflow_path, "r", encoding="utf-8") as f:
            self.workflow_template = json.load(f)

    def queue_prompt(self, prompt: dict, client_id: str) -> dict:
        payload = {"prompt": prompt, "client_id": client_id}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(f"http://{self.server_address}/prompt", data=data)
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read())

    def get_image(self, filename: str, subfolder: str, folder_type: str) -> bytes:
        params = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type})
        with urllib.request.urlopen(f"http://{self.server_address}/view?{params}") as response:
            return response.read()

    def get_history(self, prompt_id: str) -> dict:
        with urllib.request.urlopen(f"http://{self.server_address}/history/{prompt_id}") as response:
            return json.loads(response.read())

    def get_images_old(self, ws, prompt: dict, client_id: str) -> dict:
        prompt_id = self.queue_prompt(prompt, client_id)['prompt_id']
        output_images = {}

        while True:
            message_raw = ws.recv()
            if isinstance(message_raw, str):
                message = json.loads(message_raw)
                if message['type'] == 'executing':
                    data = message['data']
                    if data['node'] is None and data['prompt_id'] == prompt_id:
                        break
            else:
                continue  # skip previews (binary)

        history_data = self.get_history(prompt_id)[prompt_id]
        for node_id, node_output in history_data['outputs'].items():
            if 'images' in node_output:
                output_images[node_id] = [
                    self.get_image(img['filename'], img['subfolder'], img['type'])
                    for img in node_output['images']
                ]

        return output_images

    def upload_file(self, file, subfolder: str = "", overwrite: bool = False) -> str:
        try:
            files = {"image": file}
            data = {"overwrite": "true"} if overwrite else {}

            if subfolder:
                data["subfolder"] = subfolder

            response = self.session.post(f"http://{self.server_address}/upload/image", files=files, data=data)

            if response.status_code == 200:
                response_data = response.json()
                path = response_data["name"]
                if response_data.get("subfolder"):
                    path = f"{response_data['subfolder']}/{path}"
                return path
            else:
                logger.warning(f"[Upload Error] {response.status_code} - {response.reason}")
                return None
        except Exception as e:
            logger.warning(f"[Upload Exception] {e}")
            return None

    def save_image(self, images: dict) -> str:
        for node_id, image_list in images.items():
            for image_data in image_list:
                with Image.open(io.BytesIO(image_data)) as image:
                    image_filename = generate_timestamped_filename(self.img_temp_folder, "kingsday", "png")
                    image.save(image_filename, optimize=True)
                    return image_filename  # Retorna apenas a primeira imagem

    def prepare_prompt(self, is_king=True):
        king_prompt = "king wearing a golden crown, male, 1boy"
        queen_prompt = "queen wearing a golden crown, female, 1girl, woman, diamond earings and necklaces"

        gender_prompt = king_prompt if is_king else queen_prompt

        input_prompt_text = f"""30 years of age, {gender_prompt}, gold and red ornaments, 
         european red coat with white fur, renascence, inside a castle, old paintings on the walls, 
         large windows with red curtains, blurry background, photo, photorealistic, realism"""

        return input_prompt_text

    def get_images(self, prompt, client_id, server_address):
        prompt_id, aws_alb_cookie = comfyui_api_utils.queue_prompt(prompt, client_id, server_address)
        output_images = {}

        logger.debug("Generation started.")
        while True:
            history = comfyui_api_utils.get_history(prompt_id, server_address, aws_alb_cookie)
            if len(history) == 0:
                logger.debug("Generation not ready, sleep 1s ...")
                time.sleep(1)
                continue
            else:
                logger.debug("Generation finished.")
                break

        history = history[prompt_id]
        for node_id in history['outputs']:
            node_output = history['outputs'][node_id]
            if 'images' in node_output and node_output['images'][0]['type'] == 'output':
                images_output = []
                for image in node_output['images']:
                    image_data = comfyui_api_utils.get_image(image['filename'], image['subfolder'], image['type'],
                                                             server_address, aws_alb_cookie)
                    images_output.append(image_data)
                output_images[node_id] = images_output
        return output_images, prompt_id

    def generate_image(self, image_path: str, is_king=True) -> str:
        timing = {}
        client_id = str(uuid.uuid4())  # Garante isolamento por requisição

        start_time = datetime.datetime.now()
        with open(image_path, "rb") as f:
            #comfyui_path_image = self.upload_file(f, "", True)
            comfyui_path_image = comfyui_api_utils.upload_image(image_path=image_path,
                                                                server_address=self.server_address)

        timing["upload"] = datetime.datetime.now()

        input_prompt_text = self.prepare_prompt(is_king)

        prompt = copy.deepcopy(self.workflow_template)
        prompt[self.node_id_ksampler]["inputs"]["seed"] = random.randint(1, 1_000_000_000)
        prompt[self.node_id_image_load]["inputs"]["image"] = comfyui_path_image
        prompt[self.node_id_text_input]["inputs"]["text"] = input_prompt_text

        #ws = websocket.WebSocket()
        #ws.connect(f"ws://{self.server_address}/ws?clientId={client_id}")
        timing["start_execution"] = datetime.datetime.now()

        images, prompt_id = self.get_images(prompt, client_id, server_address=self.server_address)
        #images = self.get_images(ws, prompt, client_id)

        timing["execution_done"] = datetime.datetime.now()
        #ws.close()

        image_file_path = self.save_image(images)
        timing["save"] = datetime.datetime.now()

        logger.info(f"Timing Info for image: {image_path} => {image_file_path}")
        logger.info(f"Upload time:        {(timing['upload'] - start_time).total_seconds()}s")
        logger.info(f"Execution wait:     {(timing['start_execution'] - timing['upload']).total_seconds()}s")
        logger.info(f"Processing time:    {(timing['execution_done'] - timing['start_execution']).total_seconds()}s")
        logger.info(f"Saving time:        {(timing['save'] - timing['execution_done']).total_seconds()}s")
        logger.info(f"Total:              {(timing['save'] - start_time).total_seconds()}s")
        #watermark_file_path = 'static/assets/logo_amstel.png'

        logger.debug(f"Saved image path: {image_file_path}")
        assert image_file_path is not None, "Erro: Caminho da imagem gerada está vazio!"

        #if not os.path.exists(watermark_file_path):
        #    raise FileNotFoundError(f"Marca d'água não encontrada em: {watermark_file_path}")

        #self.add_watermark_image(image_file_path, watermark_file_path)
        return image_file_path

    def add_watermark_image(self, base_image_path: str, watermark_path: str) -> None:
        base_image = Image.open(base_image_path).convert("RGBA")
        watermark = Image.open(watermark_path).convert("RGBA")

        # Redimensiona a marca se for maior que a imagem base
        if watermark.width > base_image.width:
            ratio = base_image.width / watermark.width * 0.5  # Reduz para 50% da largura, por exemplo
            new_size = (int(watermark.width * ratio), int(watermark.height * ratio))
            watermark = watermark.resize(new_size, Image.Resampling.LANCZOS)

        # Posição: inferior central
        position = (
            (base_image.width - watermark.width) // 2,
            base_image.height - watermark.height - 10
        )

        # Combina as imagens
        composite = Image.new("RGBA", base_image.size)
        composite = Image.alpha_composite(composite, base_image)
        composite.paste(watermark, position, watermark)  # Usa o canal alpha da marca

        # Salva por cima (ou pode salvar em outro caminho)
        composite.convert("RGB").save(base_image_path, "PNG")


if __name__ == '__main__':
    import parameters as param

    api = ComfyUiAPI(
        server_address=param.STABLE_SWARM_API_SERVER,
        img_temp_folder='static/outputs',
        workflow_path=param.WORKFLOW_PATH,
        node_id_ksampler=param.WORKFLOW_NODE_ID_KSAMPLER,
        node_id_image_load=param.WORKFLOW_NODE_ID_IMAGE_LOAD,
        node_id_text_input=param.WORKFLOW_NODE_ID_TEXT_INPUT
    )

    #input_image = r"C:\Users\Win 11\Downloads\maekiko.png"
    input_image = r"C:\Users\Win 11\Downloads\dudu_3x4.jpg"
    image_path = api.generate_image(input_image, is_king=True)