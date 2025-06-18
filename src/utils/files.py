import os
import io
import zipfile
import base64
import shutil
import time
import structlog

from datetime import datetime
from typing import Dict, Union
from collections import defaultdict

import matplotlib.pyplot as plt
from fastapi import HTTPException

from core.config import settings

log = structlog.get_logger()

def create_zip_of_images(folder_path: str) -> io.BytesIO:
    """
    Cria um buffer ZIP contendo todas as imagens (.png, .jpg, .jpeg) encontradas no caminho informado.
    
    :param folder_path: Caminho da pasta cujas imagens serão zipadas.
    :return: BytesIO já posicionado no início, pronto para ser retornado em uma resposta (StreamingResponse).
    :raises HTTPException: Se a pasta não existir ou não for acessível.
    """
    if not os.path.isdir(folder_path):
        log.info("create_zip_of_images: Pasta não encontrada", folder_path=folder_path)
        raise HTTPException(status_code=404, detail="Pasta não encontrada para criar ZIP")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith((".png", ".jpg", ".jpeg")):
                    file_path = os.path.join(root, file)
                    # Relpath garante a estrutura interna correta dentro do ZIP
                    arcname = os.path.relpath(file_path, folder_path)
                    zip_file.write(file_path, arcname)
    zip_buffer.seek(0)
    return zip_buffer


def generate_timestamped_filename(
    base_folder: str, prefix: str, extension: str
) -> str:
    """
    Gera um nome de arquivo com timestamp no formato:
    {base_folder}/{prefix}_YYYYMMDD_HHMMSS.{extension}

    :param base_folder: Pasta onde o arquivo será salvo.
    :param prefix: Prefixo que identifica o arquivo.
    :param extension: Extensão do arquivo (sem ponto).
    :return: Caminho completo para o novo arquivo.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}.{extension}"
    return os.path.join(base_folder, filename)


def read_last_n_lines(filename: str, n: int) -> str:
    """
    Lê as últimas n linhas de um arquivo de texto, sem carregar o arquivo inteiro em memória.
    
    :param filename: Caminho para o arquivo.
    :param n: Número de linhas finais a serem retornadas.
    :return: Uma string contendo as últimas n linhas separadas por '\n'.
    :raises HTTPException: Se o arquivo não existir ou não puder ser aberto.
    """
    if not os.path.isfile(filename):
        log.info("read_last_n_lines: Arquivo não encontrado", filename=filename)
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")

    try:
        with open(filename, "rb") as file:
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            buffer = bytearray()
            lines_found = 0
            block_size = 1024

            while file_size > 0 and lines_found <= n:
                read_size = min(block_size, file_size)
                file.seek(file_size - read_size)
                chunk = file.read(read_size)
                buffer = chunk + buffer
                lines_found = buffer.count(b"\n")
                file_size -= read_size

            last_lines = buffer.splitlines()[-n:]
            return b"\n".join(last_lines).decode("utf-8", errors="replace")
    except Exception as e:
        log.info("read_last_n_lines: Erro ao ler arquivo", error=str(e), filename=filename)
        raise HTTPException(status_code=500, detail="Erro ao ler o arquivo")


def count_files_in_directory(directory_path: str) -> int:
    """
    Conta quantos arquivos existem diretamente em um diretório (sem olhar subpastas).
    
    :param directory_path: Caminho da pasta alvo.
    :return: Quantidade de arquivos nessa pasta.
    :raises HTTPException: Se a pasta não existir ou não puder ser acessada.
    """
    if not os.path.isdir(directory_path):
        log.info("count_files_in_directory: Pasta não encontrada", directory=directory_path)
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
    return sum(1 for entry in os.scandir(directory_path) if entry.is_file())


def count_files_with_extension(directory_path: str, extension: str) -> int:
    """
    Conta arquivos em um diretório que terminem com a extensão dada (case-insensitive).
    
    :param directory_path: Caminho da pasta alvo.
    :param extension: Extensão a ser filtrada (com ou sem ponto).
    :return: Quantidade de arquivos com essa extensão.
    :raises HTTPException: Se a pasta não existir ou não puder ser acessada.
    """
    if not os.path.isdir(directory_path):
        log.info("count_files_with_extension: Pasta não encontrada", directory=directory_path)
        raise HTTPException(status_code=404, detail="Pasta não encontrada")

    ext = extension.lower().lstrip(".")
    return sum(
        1
        for entry in os.scandir(directory_path)
        if entry.is_file() and entry.name.lower().endswith(f".{ext}")
    )


def count_files_between_dates(
    directory_path: str, start_date: datetime, end_date: datetime
) -> int:
    """
    Conta arquivos cuja data de criação esteja entre start_date e end_date (inclusive).
    
    :param directory_path: Caminho da pasta alvo.
    :param start_date: Data/hora inicial.
    :param end_date: Data/hora final.
    :return: Quantidade de arquivos no intervalo.
    :raises HTTPException: Se a pasta não existir ou não puder ser acessada.
    """
    if not os.path.isdir(directory_path):
        log.info("count_files_between_dates: Pasta não encontrada", directory=directory_path)
        raise HTTPException(status_code=404, detail="Pasta não encontrada")

    count = 0
    for entry in os.scandir(directory_path):
        if entry.is_file():
            creation_time = datetime.fromtimestamp(entry.stat().st_ctime)
            if start_date <= creation_time <= end_date:
                count += 1
    return count


def count_files_by_hour(directory_path: str) -> Dict[datetime, int]:
    """
    Agrupa arquivos por hora de modificação, retornando um dicionário onde a chave é
    o início da hora (YYYY-MM-DD HH:00:00) e o valor é a quantidade de arquivos modificados nessa hora.
    
    :param directory_path: Caminho da pasta alvo.
    :return: Dicionário {datetime da hora: quantidade de arquivos}.
    :raises HTTPException: Se a pasta não existir ou não puder ser acessada.
    """
    if not os.path.isdir(directory_path):
        log.info("count_files_by_hour: Pasta não encontrada", directory=directory_path)
        raise HTTPException(status_code=404, detail="Pasta não encontrada")

    file_counts: Dict[datetime, int] = defaultdict(int)
    for entry in os.scandir(directory_path):
        if entry.is_file():
            mod_time = datetime.fromtimestamp(entry.stat().st_mtime)
            hour_bucket = mod_time.replace(minute=0, second=0, microsecond=0)
            file_counts[hour_bucket] += 1

    return dict(file_counts)


def generate_file_activity_plot_base64(
    file_activity: Dict[datetime, int], style: str = "bar"
) -> str:
    """
    Gera um gráfico (PNG) representando atividade de arquivos por hora e retorna
    a imagem codificada em Base64 (para exibição inline em HTML ou JSON).
    
    :param file_activity: Dicionário {datetime da hora: quantidade de arquivos}.
    :param style: 'bar' ou 'line' para tipo de gráfico. Padrão 'bar'.
    :return: String Base64 da imagem PNG, ou string vazia se não houver dados.
    """
    if not file_activity:
        return ""

    times = sorted(file_activity.keys())
    counts = [file_activity[t] for t in times]

    plt.figure(figsize=(12, 6))
    if style.lower() == "bar":
        plt.bar(times, counts, edgecolor="black")
    else:
        plt.plot(times, counts, marker="o", linestyle="-")

    plt.title("Files Modified Per Hour")
    plt.xlabel("Hour")
    plt.ylabel("Number of Files")
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()

    img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return img_base64

def remove_old_folders():
    """
    A cada execução, verifica em static/download_images subpastas criadas e remove
    aquelas com mais de 10 minutos.
    """
    while True:
        current_time = time.time()
        directory = os.path.join(settings.STATIC_DIR, "download_images")
        minutes = 10

        for foldername in os.listdir(directory):
            folder_path = os.path.join(directory, foldername)
            if os.path.isdir(folder_path):
                creation_time = os.path.getctime(folder_path)
                if (current_time - creation_time) / 60 > minutes:
                    shutil.rmtree(folder_path)
                    log.info('Pasta removida por tempo excedido', folder=foldername)
        time.sleep(60)