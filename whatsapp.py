"""WhatsApp sending, behind one small interface.

Pick a provider with the WHATSAPP_PROVIDER environment variable:

    console  (default) – nothing is sent; messages are printed and saved to the
                         admin "Messages" log. Login codes are shown on screen.
    twilio             – Twilio WhatsApp API. Needs TWILIO_ACCOUNT_SID,
                         TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM (e.g. 14155238886).
    meta               – WhatsApp Business Cloud API (Meta). Needs
                         META_WA_TOKEN and META_WA_PHONE_NUMBER_ID.
    msg91              – MSG91 WhatsApp, the same setup NyayaMitra uses. Needs MSG91_AUTH_KEY.
                         Login codes go out as the approved OTP template; other messages
                         go out as plain WhatsApp text (see MSG91Provider below).

Every provider exposes send(to, body, media_url=None, media_type=None) and returns
(ok: bool, error: str | None). Providers that need a special message for login codes
also have send_otp(to, code). Phone numbers are digits with country code, no '+'.
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


class MSG91Provider:
    """MSG91 WhatsApp Business API, configured like NyayaMitra's backend.

    Login codes use the approved authentication template (body + copy-code button).
    Defaults are NyayaMitra's WhatsApp number and template; set these to use a
    Sanskriti-specific number or template instead:
      MSG91_WA_NUMBER (integrated number), MSG91_OTP_TEMPLATE, MSG91_OTP_NAMESPACE, MSG91_OTP_LANG.

    Other messages (reminders, promotions) are sent as plain text/media session
    messages. WhatsApp only delivers those if the person messaged the number in the
    last 24 hours; otherwise MSG91 rejects them and the failure shows in Admin → Messages.
    """
    name = "msg91"
    BASE = "https://api.msg91.com/api/v5/whatsapp"

    def __init__(self):
        self.key = os.environ["MSG91_AUTH_KEY"]
        self.number = os.environ.get("MSG91_WA_NUMBER", "919606587058").lstrip("+")
        self.template = os.environ.get("MSG91_OTP_TEMPLATE", "nyayamitra_otp")
        self.namespace = os.environ.get("MSG91_OTP_NAMESPACE", "1c01bdcc_df87_445d_9d26_33917faeaa3d")
        self.lang = os.environ.get("MSG91_OTP_LANG", "en")

    def _post(self, path, payload):
        req = urllib.request.Request(f"{self.BASE}/{path}", data=json.dumps(payload).encode(), method="POST")
        req.add_header("authkey", self.key)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"
        except Exception as e:  # network errors etc.
            return False, str(e)[:500]
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        if isinstance(data, dict) and (data.get("type") == "error" or data.get("status") == "fail"):
            return False, raw[:500]
        return True, None

    def send_otp(self, to, code):
        payload = {
            "integrated_number": self.number,
            "content_type": "template",
            "payload": {
                "messaging_product": "whatsapp",
                "type": "template",
                "template": {
                    "name": self.template,
                    "language": {"code": self.lang, "policy": "deterministic"},
                    "namespace": self.namespace,
                    "to_and_components": [{
                        "to": [to],
                        "components": {
                            "body_1": {"type": "text", "value": code},
                            "button_1": {"subtype": "url", "type": "text", "value": code},
                        },
                    }],
                },
            },
        }
        return self._post("whatsapp-outbound-message/bulk/", payload)

    def send(self, to, body, media_url=None, media_type=None):
        payload = {"integrated_number": self.number, "recipient_number": to}
        if media_url and media_type in ("image", "video"):
            payload.update(content_type=media_type, attachment_url=media_url, caption=body)
        else:
            payload.update(content_type="text", text=body)
        return self._post("whatsapp-outbound-message/", payload)


def _call(req):
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return True, None
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"
    except Exception as e:  # network errors etc.
        return False, str(e)[:500]


PROVIDERS = {"console": ConsoleProvider, "twilio": TwilioProvider, "meta": MetaCloudProvider,
             "msg91": MSG91Provider}


def get_provider():
    name = os.environ.get("WHATSAPP_PROVIDER", "").strip().lower()
    if not name and os.environ.get("MSG91_AUTH_KEY"):
        name = "msg91"
    try:
        return PROVIDERS.get(name or "console", ConsoleProvider)()
    except KeyError as missing:
        # A provider was chosen but its keys aren't set: keep the site working in demo mode.
        print(f"WhatsApp provider '{name}' is missing {missing}; using console mode.", flush=True)
        return ConsoleProvider()
