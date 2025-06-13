import uuid
import json
import random
import datetime
import io
import copy
import urllib.request
import urllib.parse
import requests
import websocket
import structlog

from PIL import Image

from core.config import settings
from utils.files import generate_timestamped_filename

log = structlog.get_logger()


class ComfyUiAPI:
    def __init__(
        self,
        server_address: str,
        img_temp_folder: str,
        workflow_path: str,
        node_id_ksampler: str,
        node_id_image_load: str,
        node_id_text_input: str,
    ):
        self.server_address = server_address
        self.img_temp_folder = img_temp_folder
        self.node_id_ksampler = node_id_ksampler
        self.node_id_image_load = node_id_image_load
        self.node_id_text_input = node_id_text_input
        self.session = requests.Session()

        with open(workflow_path, "r", encoding="utf-8") as f:
            self.workflow_template = json.load(f)

    def queue_prompt(self, prompt: dict, client_id: str) -> dict:
        """
        Envia o prompt para a ComfyUI via endpoint HTTP /prompt
        Retorna o JSON com o prompt_id.
        """
        payload = {"prompt": prompt, "client_id": client_id}
        data = json.dumps(payload).encode("utf-8")
        url = f"http://{self.server_address}/prompt"
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read())

    def get_image(self, filename: str, subfolder: str, folder_type: str) -> bytes:
        """
        Faz o streaming de bytes de uma imagem gerada pelo ComfyUI
        via endpoint HTTP /view?filename=...&subfolder=...&type=...
        """
        params = urllib.parse.urlencode(
            {"filename": filename, "subfolder": subfolder, "type": folder_type}
        )
        url = f"http://{self.server_address}/view?{params}"
        with urllib.request.urlopen(url) as response:
            return response.read()

    def get_history(self, prompt_id: str) -> dict:
        """
        Consulta o histórico de execuções do prompt por prompt_id
        via HTTP GET em /history/{prompt_id}
        """
        url = f"http://{self.server_address}/history/{prompt_id}"
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read())

    def get_images(
        self, ws: websocket.WebSocket, prompt: dict, client_id: str
    ) -> dict:
        """
        Mantém o WebSocket aberto até a execução do workflow terminar.
        Retorna um dicionário {node_id: [bytes das imagens]}. 
        """
        queue_response = self.queue_prompt(prompt, client_id)
        prompt_id = queue_response.get("prompt_id")

        if not prompt_id:
            raise RuntimeError("Não foi possível obter prompt_id ao enfileirar prompt.")

        output_images: dict = {}
        while True:
            message_raw = ws.recv()
            if isinstance(message_raw, str):
                message = json.loads(message_raw)
                if (
                    message.get("type") == "executing"
                    and message.get("data", {}).get("node") is None
                    and message.get("data", {}).get("prompt_id") == prompt_id
                ):
                    break
            else:
                continue

        history_data = self.get_history(prompt_id).get(prompt_id, {})
        for node_id, node_output in history_data.get("outputs", {}).items():
            if node_output.get("images"):
                output_images[node_id] = []
                for img in node_output["images"]:
                    img_bytes = self.get_image(
                        img["filename"], img["subfolder"], img["type"]
                    )
                    output_images[node_id].append(img_bytes)

        return output_images

    def upload_file(self, file_obj, subfolder: str = "", overwrite: bool = False) -> str:
        """
        Upload de arquivo (imagem) para o ComfyUI via endpoint /upload/image
        Retorna o path no servidor ComfyUI (subfolder/filename) ou None em caso de erro.
        """
        try:
            files = {"image": file_obj}
            data = {"overwrite": "true"} if overwrite else {}
            if subfolder:
                data["subfolder"] = subfolder

            url = f"http://{self.server_address}/upload/image"
            response = self.session.post(url, files=files, data=data)
            if response.status_code == 200:
                response_data = response.json()
                path = response_data.get("name")
                if response_data.get("subfolder"):
                    path = f"{response_data['subfolder']}/{path}"
                return path
            else:
                log.info(
                    "[Upload Error]",
                    status_code=response.status_code,
                    reason=response.reason,
                )
                return None
        except Exception as e:
            log.info("[Upload Exception]", error=str(e))
            return None

    def save_image(self, images: dict) -> str:
        """
        Recebe o dicionário de imagens (bytes) retornado por get_images.
        Salva a primeira imagem disponível em uma pasta temporária e retorna o caminho do arquivo salvo.
        """
        for node_id, image_list in images.items():
            for image_data in image_list:
                image = Image.open(io.BytesIO(image_data))
                filename = generate_timestamped_filename(
                    self.img_temp_folder, prefix="mamulengos", extension="png"
                )
                image.save(filename, optimize=True)
                return filename

        raise RuntimeError("Nenhuma imagem encontrada para salvar.")

    def generate_image(self, image_path: str) -> str:
        """
        Fluxo completo para gerar imagem:
        1. Faz upload da imagem de entrada
        2. Constrói o prompt a partir do template (configura nós)
        3. Abre WebSocket e aguarda término da execução
        4. Salva a primeira imagem retornada e retorna o caminho salvo
        """
        timing = {}
        client_id = str(uuid.uuid4())
        start_time = datetime.datetime.now()

        with open(image_path, "rb") as f:
            comfyui_path = self.upload_file(f, subfolder="", overwrite=True)
        timing["upload"] = datetime.datetime.now()

        if not comfyui_path:
            raise RuntimeError("Falha ao fazer upload da imagem para ComfyUI.")

        # king_prompt = (
        #     "king wearing a golden crown, male, 1boy"
        # )
        # queen_prompt = (
        #     "queen wearing a golden crown, female, 1girl, woman, diamond earings and necklaces"
        # )
        # gender_prompt = king_prompt if is_king else queen_prompt

        # input_prompt_text = (
        #     f"30 years of age, {gender_prompt}, gold and red ornaments, "
        #     "european red coat with white fur, renascence, inside a castle, old "
        #     "paintings on the walls, large windows with red curtains, blurry background, "
        #     "photo, photorealistic, realism"
        # )

        prompt = copy.deepcopy(self.workflow_template)
        # prompt[self.node_id_ksampler]["inputs"]["seed"] = random.randint(1, 1_000_000_000)
        prompt[self.node_id_image_load]["inputs"]["image"] = comfyui_path
        # prompt[self.node_id_text_input]["inputs"]["text"] = input_prompt_text

        ws_url = f"ws://{self.server_address}/ws?clientId={client_id}"
        ws = websocket.WebSocket()
        ws.connect(ws_url)
        timing["start_execution"] = datetime.datetime.now()

        images = self.get_images(ws, prompt, client_id)
        timing["execution_done"] = datetime.datetime.now()
        ws.close()

        image_file_path = self.save_image(images)
        timing["save"] = datetime.datetime.now()

        log.info("[Timing Info]")
        log.info("Upload time:        %ss", (timing["upload"] - start_time).total_seconds())
        log.info(
            "Execution wait:     %ss",
            (timing["start_execution"] - timing["upload"]).total_seconds(),
        )
        log.info(
            "Processing time:    %ss",
            (timing["execution_done"] - timing["start_execution"]).total_seconds(),
        )
        log.info(
            "Saving time:        %ss",
            (timing["save"] - timing["execution_done"]).total_seconds(),
        )
        log.info("Total:              %ss", (timing["save"] - start_time).total_seconds())

        log.info("[DEBUG] Saved image path: %s", image_file_path)
        if not image_file_path:
            raise RuntimeError("Erro: Caminho da imagem gerada está vazio!")

        return image_file_path

    def add_watermark_image(self, base_image_path: str, watermark_path: str) -> None:
        """
        Adiciona marca d'água à imagem gerada pelo ComfyUI.
        Insere o watermark no centro inferior da imagem.
        """
        base_image = Image.open(base_image_path).convert("RGBA")
        watermark = Image.open(watermark_path).convert("RGBA")

        if watermark.width > base_image.width:
            ratio = (base_image.width / watermark.width) * 0.5
            new_size = (int(watermark.width * ratio), int(watermark.height * ratio))
            watermark = watermark.resize(new_size, Image.Resampling.LANCZOS)

        position = (
            (base_image.width - watermark.width) // 2,
            base_image.height - watermark.height - 10,
        )

        composite = Image.new("RGBA", base_image.size)
        composite = Image.alpha_composite(composite, base_image)
        composite.paste(watermark, position, watermark)

        composite.convert("RGB").save(base_image_path, "PNG")

    def generate_image_buffer(self, file_obj) -> str:
        """
        Fluxo completo para gerar imagem a partir de um file-like:
        1. Faz upload da imagem de entrada (BytesIO ou similar)
        2. Constrói o prompt a partir do template
        3. Abre WebSocket e aguarda término da execução
        4. Salva a primeira imagem retornada e retorna o caminho salvo
        """
        timing = {}
        client_id = str(uuid.uuid4())
        start_time = datetime.datetime.now()

        # upload usando o file-like em memória
        comfyui_path = self.upload_file(file_obj, subfolder="", overwrite=True)
        timing["upload"] = datetime.datetime.now()

        if not comfyui_path:
            raise RuntimeError("Falha ao fazer upload da imagem para ComfyUI.")

        # monta o prompt
        prompt = copy.deepcopy(self.workflow_template)
        prompt[self.node_id_image_load]["inputs"]["image"] = comfyui_path

        # conecta WebSocket com o client_id correto
        ws_url = f"ws://{self.server_address}/ws?clientId={client_id}"
        ws = websocket.WebSocket()
        ws.connect(ws_url)
        timing["start_execution"] = datetime.datetime.now()

        # aguarda execução e coleta imagens
        images = self.get_images(ws, prompt, client_id)
        timing["execution_done"] = datetime.datetime.now()
        ws.close()

        # salva a imagem resultante em disco
        image_file_path = self.save_image(images)
        timing["save"] = datetime.datetime.now()

        # logs de timing
        log.info("[Timing Info]")
        log.info("Upload time:        %ss", (timing["upload"] - start_time).total_seconds())
        log.info("Execution wait:     %ss", (timing["start_execution"] - timing["upload"]).total_seconds())
        log.info("Processing time:    %ss", (timing["execution_done"] - timing["start_execution"]).total_seconds())
        log.info("Saving time:        %ss", (timing["save"] - timing["execution_done"]).total_seconds())
        log.info("Total:              %ss", (timing["save"] - start_time).total_seconds())

        log.info("[DEBUG] Saved image path: %s", image_file_path)
        if not image_file_path:
            raise RuntimeError("Erro: Caminho da imagem gerada está vazio!")

        return image_file_path