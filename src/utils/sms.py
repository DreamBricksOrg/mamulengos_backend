import requests
import phonenumbers
import structlog
from phonenumbers import NumberParseException

from core.config import settings


log = structlog.get_logger()

api_url = settings.SMS_API_URL
api_key = settings.SMS_API_KEY

def send_sms_message(message: str, destination_number: str) -> bool:
    """
    Envia um SMS usando a API `smsdev.com.br`.
    """
    if not api_key or not api_url:
        log.error("sms.config_missing", api_url=api_url, api_key=bool(api_key))
        raise RuntimeError("API_KEY ou API_URL não configurados.")

    try:
        formatted = format_to_e164(destination_number)
        payload = {"key": api_key, "type": 9, "number": formatted, "msg": message}
        resp = requests.post(api_url, json=payload, timeout=10)
        data = resp.json()
        if resp.status_code == 200 and data.get("status") == "success":
            log.info("sms.sent", to=formatted)
            return True
        else:
            log.error("sms.failure", to=formatted, response=data)
            return False
    except Exception as e:
        log.error("sms.exception", to=destination_number, error=str(e))
        return False


def send_sms_download_message(message_url: str, destination_number: str) -> bool:
    """
    Envia SMS com link para download.
    """
    body = (
        "Seu Mamulengo ficou pronto: \n"
        f"{message_url}"
    )
    return send_sms_message(body, destination_number)


def format_to_e164(phone_number: str, country_code: str = "BR") -> str:
    """
    Formata o número de telefone para o padrão internacional E.164.
    """
    try:
        parsed = phonenumbers.parse(phone_number, country_code)
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError("Número de telefone inválido.")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except NumberParseException as e:
        log.error("sms.format_error", number=phone_number, error=str(e))
        raise
