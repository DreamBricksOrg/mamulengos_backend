import os
from datetime import datetime
import zipfile
import io
from collections import defaultdict

import base64
import matplotlib.pyplot as plt


def create_zip_of_images(folder_path):
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:

        for root, dirs, files in os.walk(folder_path):
            for file in files:

                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    file_path = os.path.join(root, file)
                    zip_file.write(file_path, os.path.relpath(file_path, folder_path))

    zip_buffer.seek(0)

    return zip_buffer


def generate_timestamped_filename(base_folder: str, prefix: str, extension: str) -> str:
    """
    Generates a filename with the current timestamp in the format:
    {prefix}_YYYYMMDD_HHMMSS.{extension}

    Parameters:
    - base_folder (str): The folder where the file should be saved.
    - prefix (str): The prefix for the filename.
    - extension (str): The file extension (without the dot).

    Returns:
    - str: The full file path with the formatted filename.
    """
    # Get current date and time
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Construct the filename
    filename = f"{prefix}_{timestamp}.{extension}"

    # Return the full path
    return os.path.join(base_folder, filename)


def read_last_n_lines(filename: str, n: int) -> str:
    with open(filename, 'rb') as file:
        # goes to the end of the file
        file.seek(0, os.SEEK_END)
        file_size = file.tell()

        buffer = bytearray()
        lines_found = 0
        block_size = 1024

        # reads small blocks until the target number of lines is found
        while file_size > 0 and lines_found <= n:
            read_size = min(block_size, file_size)
            file.seek(file_size - read_size)
            buffer = file.read(read_size) + buffer
            lines_found = buffer.count(b'\n')
            file_size -= read_size

        # Now decode only once at the end
        return b'\n'.join(buffer.splitlines()[-n:]).decode('utf-8')


def count_files_in_directory(directory_path: str) -> int:
    return sum(1 for entry in os.scandir(directory_path) if entry.is_file())


def count_files_with_extension(directory_path: str, extension: str) -> int:
    extension = extension.lower().lstrip('.')  # Normalize extension (remove dot if given)
    return sum(
        1
        for entry in os.scandir(directory_path)
        if entry.is_file() and entry.name.lower().endswith(f'.{extension}')
    )


def count_files_between_dates(directory_path: str, start_date: datetime, end_date: datetime) -> int:
    result = 0

    for entry in os.scandir(directory_path):
        if entry.is_file():
            # Get file creation time
            creation_time = datetime.fromtimestamp(entry.stat().st_ctime)

            if start_date <= creation_time <= end_date:
                result += 1

    return result


def count_files_by_hour(directory_path: str) -> dict:
    file_counts = defaultdict(int)

    for entry in os.scandir(directory_path):
        if entry.is_file():
            # Get the modification time (can also use creation time if you prefer)
            mod_time = datetime.fromtimestamp(entry.stat().st_mtime)

            # Normalize to the start of the hour
            hour_bucket = mod_time.replace(minute=0, second=0, microsecond=0)

            file_counts[hour_bucket] += 1

    return dict(file_counts)


def generate_file_activity_plot_base64(file_activity: dict, style: str = "bar") -> str:
    if not file_activity:
        return ""

    times = sorted(file_activity.keys())
    counts = [file_activity[t] for t in times]

    plt.figure(figsize=(12, 6))

    if style == "bar":
        plt.bar(times, counts, color='skyblue', edgecolor='black')
    else:
        plt.plot(times, counts, marker='o', linestyle='-', color='royalblue')

    plt.title('Files Modified Per Hour')
    plt.xlabel('Hour')
    plt.ylabel('Number of Files')
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()

    img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    return img_base64


if __name__ == "__main__":
    pass

