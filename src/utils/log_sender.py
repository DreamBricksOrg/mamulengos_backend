import csv
import time
import requests
import threading
import os
import structlog

from datetime import datetime, timezone


log = structlog.get_logger()

LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')


class LogSender:
    csv_filename = os.path.join(LOG_DIR, 'datalogs.csv')
    backup_filename = os.path.join(LOG_DIR, 'datalogs_backup.csv')

    def __init__(self, log_api, project_id, upload_delay=120):
        self.project_id = project_id
        self.log_api = log_api
        self.upload_delay = upload_delay
        self._init_csv(self.csv_filename)
        self._init_csv(self.backup_filename)
        threading.Thread(target=self._process_csv_and_send_logs, daemon=True).start()

    @staticmethod
    def _init_csv(filename):
        try:
            with open(filename, mode='x', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['status', 'project', 'additional', 'timePlayed'])
            log.info("csv_initialized", file=filename)
        except FileExistsError:
            log.debug("csv_already_exists", file=filename)

    def log(self, status, additional=''):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(self.csv_filename, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([status, self.project_id, additional, now])
        log.info("log_appended", status=status, project=self.project_id, timePlayed=now)

    def _send_log(self, status, project, additional, timePlayed):
        url = f"{self.log_api}/datalog/upload"
        payload = {
            'status': status,
            'project': project,
            'additional': additional,
            'timePlayed': timePlayed
        }
        try:
            r = requests.post(url, data=payload)
            if r.status_code == 200:
                log.info("log_sent", **payload)
                return True
            else:
                log.warning("log_send_failed", status_code=r.status_code, **payload)
                return False
        except Exception as e:
            log.error("log_send_error", error=str(e), **payload)
            return False

    def _process_csv_and_send_logs(self):
        while True:
            keep, backup = [], []
            with open(self.csv_filename, mode="r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if self._send_log(**row):
                        backup.append(row)
                    else:
                        keep.append(row)

            with open(self.csv_filename, mode="w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["status","project","additional","timePlayed"])
                writer.writeheader()
                writer.writerows(keep)

            with open(self.backup_filename, mode="a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["status","project","additional","timePlayed"])
                writer.writerows(backup)

            log.info("batch_processed", sent=len(backup), kept=len(keep))

            time.sleep(self.upload_delay)