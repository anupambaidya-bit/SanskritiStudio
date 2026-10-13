"""WhatsApp sending, behind one small interface.

Pick a provider with the WHATSAPP_PROVIDER environment variable:

    console  (default) – nothing is sent; messages are printed and saved to the
                         admin "Messages" log. Login codes are shown on screen.
    twilio             – Twilio WhatsApp API. Needs TWILIO_ACCOUNT_SID,
                         TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM (e.g. 14155238886).
    meta               – WhatsApp Business Cloud API (Meta). Needs
                         META_WA_TOKEN and META_WA_PHONE_NUMBER_ID.

Every provider exposes send(to, body, media_url=None, media_type=None) and returns
(ok: bool, error: str | None). Phone numbers are digits with country code, no '+'.
"""
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request


class ConsoleProvider:
    name = "console"

    def send(self, to, body, media_url=None, media_type=None):
        extra = f"  [media: {media_url}]" if media_url else ""
        print(f"\n--- WhatsApp to +{to} ---\n{body}{extra}\n", flush=True)
        return True, None


class TwilioProvider:
    name = "twilio"

    def __init__(self):
        self.sid = os.environ["TWILIO_ACCOUNT_SID"]
        self.token = os.environ["TWILIO_AUTH_TOKEN"]
        self.sender = os.environ["TWILIO_WHATSAPP_FROM"].lstrip("+")

    def send(self, to, body, media_url=None, media_type=None):
        data = {"From": f"whatsapp:+{self.sender}", "To": f"whatsapp:+{to}", "Body": body}
        if media_url:
            data["MediaUrl"] = media_url
        req = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
            data=urllib.parse.urlencode(data).encode(),
            method="POST",
        )
        auth = base64.b64encode(f"{self.sid}:{self.token}".encode()).decode()
        req.add_header("Authorization", f"Basic {auth}")
        return _call(req)


class MetaCloudProvider:
    name = "meta"

    def __init__(self):
        self.token = os.environ["META_WA_TOKEN"]
        self.phone_id = os.environ["META_WA_PHONE_NUMBER_ID"]
        self.version = os.environ.get("META_WA_API_VERSION", "v20.0")

    def send(self, to, body, media_url=None, media_type=None):
        if media_url and media_type in ("image", "video"):
            payload = {"messaging_product": "whatsapp", "to": to, "type": media_type,
                       media_type: {"link": media_url, "caption": body}}
        else:
            payload = {"messaging_product": "whatsapp", "to": to, "type": "text",
                       "text": {"body": body, "preview_url": True}}
        req = urllib.request.Request(
            f"https://graph.facebook.com/{self.version}/{self.phone_id}/messages",
            data=json.dumps(payload).encode(),
            method="POST",
        )
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json")
        return _call(req)


def _call(req):
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return True, None
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"
    except Exception as e:  # network errors etc.
        return False, str(e)[:500]


PROVIDERS = {"console": ConsoleProvider, "twilio": TwilioProvider, "meta": MetaCloudProvider}


def get_provider():
    name = os.environ.get("WHATSAPP_PROVIDER", "console").strip().lower()
    return PROVIDERS.get(name, ConsoleProvider)()
