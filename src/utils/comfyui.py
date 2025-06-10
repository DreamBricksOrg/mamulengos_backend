import urllib.parse
import requests
import json
import structlog

from typing import Optional, Tuple, Any
from fastapi import HTTPException

from core.config import settings


log = structlog.get_logger()

def queue_prompt(
    prompt: dict, client_id: str, server_address: Optional[str] = None
) -> Tuple[str, Optional[str]]:
    """
    Envia o prompt para o ComfyUI via HTTP POST em /prompt.
    Retorna uma tupla (prompt_id, aws_alb_cookie).

    :param prompt: Dicionário com os parâmetros do prompt.
    :param client_id: Identificador único do cliente para esta requisição.
    :param server_address: Endereço base do servidor ComfyUI (ex.: 'http://localhost:8188').
                           Se None, será usado settings.COMFYUI_API_SERVER.
    :raises HTTPException: Se o servidor retornar status != 200.
    """
    server = server_address or settings.COMFYUI_API_SERVER
    url = f"{server}/prompt"
    payload = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(payload).encode("utf-8")

    response = requests.post(url, data=data)
    if response.status_code != 200:
        log.info(
            "Falha ao enfileirar prompt",
            status_code=response.status_code,
            response_text=response.text,
        )
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Erro ao enfileirar prompt: {response.text}",
        )

    aws_alb_cookie = None
    if "Set-Cookie" in response.headers:
        aws_alb_cookie = response.headers["Set-Cookie"].split(";")[0]

    try:
        prompt_id = response.json().get("prompt_id")
    except ValueError:
        log.info("Resposta inválida ao enfileirar prompt", text=response.text)
        raise HTTPException(
            status_code=502, detail="Resposta inválida do servidor ComfyUI"
        )

    if not prompt_id:
        log.info("Nenhum prompt_id recebido", text=response.text)
        raise HTTPException(
            status_code=502, detail="Nenhum prompt_id retornado pelo ComfyUI"
        )

    return prompt_id, aws_alb_cookie


def check_input_image_ready(
    filename: str, server_address: Optional[str] = None
) -> bool:
    """
    Verifica se a imagem de entrada já existe no ComfyUI (endpoint /view).
    Retorna True se ela existir, False caso contrário.

    :param filename: Nome do arquivo a verificar.
    :param server_address: Endereço base do servidor ComfyUI.
    """
    server = server_address or settings.COMFYUI_API_SERVER
    params = {"filename": filename, "subfolder": "", "type": "input"}
    url_values = urllib.parse.urlencode(params)
    url = f"{server}/view?{url_values}"

    response = requests.get(url)
    if response.status_code == 200:
        log.info("Imagem de entrada pronta", filename=filename)
        return True

    log.info("Imagem de entrada não encontrada, precisa fazer upload", filename=filename)
    return False


def upload_image(
    image_path: str, server_address: Optional[str] = None, subfolder: str = ""
) -> str:
    """
    Realiza upload de uma imagem para o ComfyUI via POST em /upload/image.
    Retorna o path (subfolder/nome) armazenado no servidor.

    :param image_path: Caminho local do arquivo de imagem a ser enviado.
    :param server_address: Endereço base do servidor ComfyUI.
    :param subfolder: Subpasta no servidor onde deseja armazenar a imagem.
    :raises HTTPException: Se o servidor retornar status != 200.
    """
    server = server_address or settings.COMFYUI_API_SERVER
    url = f"{server}/upload/image"

    try:
        with open(image_path, "rb") as f:
            files = {"image": f}
            data = {}
            if subfolder:
                data["subfolder"] = subfolder

            response = requests.post(url, files=files, data=data)
    except FileNotFoundError:
        log.info("Arquivo de imagem não encontrado para upload", path=image_path)
        raise HTTPException(status_code=404, detail="Arquivo de imagem não encontrado")

    if response.status_code != 200:
        log.info(
            "Erro ao fazer upload da imagem",
            status_code=response.status_code,
            reason=response.reason,
        )
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Erro no upload da imagem: {response.text}",
        )

    response_data = response.json()
    path = response_data.get("name")
    sub = response_data.get("subfolder")
    if sub:
        path = f"{sub}/{path}"

    return path


def get_image(
    filename: str,
    subfolder: str,
    folder_type: str,
    server_address: Optional[str] = None,
    aws_alb_cookie: Optional[str] = None,
) -> bytes:
    """
    Obtém bytes de uma imagem gerada no ComfyUI via GET em /view.
    Retorna o conteúdo binário da imagem.

    :param filename: Nome do arquivo no servidor.
    :param subfolder: Subpasta no servidor onde está a imagem.
    :param folder_type: Tipo de pasta ('input' ou 'output').
    :param server_address: Endereço base do servidor ComfyUI.
    :param aws_alb_cookie: Cookie AWSALB para balanceamento de carga (opcional).
    :raises HTTPException: Se o servidor retornar status != 200.
    """
    server = server_address or settings.COMFYUI_API_SERVER
    params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(params)
    url = f"{server}/view?{url_values}"

    headers = {}
    if aws_alb_cookie:
        headers["Cookie"] = aws_alb_cookie

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        log.info(
            "Erro ao obter imagem",
            filename=filename,
            status_code=response.status_code,
            reason=response.reason,
        )
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Erro ao obter imagem: {response.text}",
        )

    return response.content


def get_history(
    prompt_id: str, server_address: Optional[str] = None, aws_alb_cookie: Optional[str] = None
) -> Any:
    """
    Recupera o histórico de execuções de um dado prompt_id via GET em /history/{prompt_id}.
    Retorna o JSON completo da resposta.
D
    :param prompt_id: Identificador do prompt gerado anteriormente.
    :param server_address: Endereço base do servidor ComfyUI.
    :param aws_alb_cookie: Cookie AWSALB para autenticação (opcional).
    :raises HTTPException: Se o servidor retornar status != 200.
    """
    server = server_address or settings.COMFYUI_API_SERVER
    url = f"{server}/history/{prompt_id}"

    headers = {}
    if aws_alb_cookie:
        headers["Cookie"] = aws_alb_cookie

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        log.info(
            "Erro ao obter histórico",
            prompt_id=prompt_id,
            status_code=response.status_code,
            reason=response.reason,
        )
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Erro ao obter histórico: {response.text}",
        )

    return response.json()


def get_queue_status(server_address: Optional[str] = None) -> Any:
    """
    Obtém o status atual da fila de prompts no ComfyUI via GET em /queue.
    Retorna o JSON da resposta.

    :param server_address: Endereço base do servidor ComfyUI.
    :raises HTTPException: Se o servidor retornar status != 200.
    """
    server = server_address or settings.COMFYUI_API_SERVER
    url = f"{server}/queue"

    response = requests.get(url)
    if response.status_code != 200:
        log.info(
            "Erro ao obter status da fila",
            status_code=response.status_code,
            reason=response.reason,
        )
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Erro ao obter status da fila: {response.text}",
        )

    return response.json()
