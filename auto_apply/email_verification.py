"""User-mediated job-application email verification; never read inboxes or solve CAPTCHA."""
import base64
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

WAIT_SECONDS=240

def wait_for_user_code(page, attempt_id, user_id, api, still_valid):
    """The only plaintext is in process memory and the user's own browser.
    The database stores a short-lived RSA-OAEP encrypted envelope.
    """
    headers, base_url, rest_get, rest_insert = api
    endpoint=base_url()+"/rest/v1/application_email_challenges"
    import requests
    import uuid
    challenge_id=str(uuid.uuid4())
    expiry=(datetime.now(timezone.utc)+timedelta(seconds=WAIT_SECONDS)).isoformat()
    def patch(params, values):
        r=requests.patch(endpoint,headers=headers({"Prefer":"return=representation"}),params=params,json=values,timeout=10)
        r.raise_for_status()
        return r.json()
    with tempfile.TemporaryDirectory(prefix="draftflow-email-") as directory:
        key=Path(directory)/"key.pem"
        subprocess.run(["openssl","genpkey","-algorithm","RSA","-pkeyopt","rsa_keygen_bits:2048","-out",str(key)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12)
        public=subprocess.run(["openssl","pkey","-in",str(key),"-pubout","-outform","DER"],check=True,capture_output=True,timeout=10).stdout
        row={"id":challenge_id,"user_id":user_id,"attempt_id":attempt_id,"public_key":base64.b64encode(public).decode("ascii"),"expires_at":expiry}
        # Clear any expired orphan left behind by an interrupted runner.
        patch({"attempt_id":"eq."+str(attempt_id),"status":"eq.WAITING","expires_at":"lt."+datetime.now(timezone.utc).isoformat()},{"status":"EXPIRED","encrypted_code":None})
        rest_insert("application_email_challenges",[row])
        print("Application email verification: waiting for candidate")
        deadline=time.monotonic()+WAIT_SECONDS
        final="EXPIRED"
        try:
            while time.monotonic()<deadline:
                if not still_valid(): final="CLOSED"; return None
                rows=rest_get("application_email_challenges",{"id":"eq."+challenge_id,"status":"eq.WAITING","select":"encrypted_code","limit":"1"})
                envelope=rows[0].get("encrypted_code") if len(rows)==1 else None
                if envelope:
                    claimed=patch({"id":"eq."+challenge_id,"status":"eq.WAITING","encrypted_code":"eq."+envelope,"expires_at":"gt."+datetime.now(timezone.utc).isoformat()},{"status":"RECEIVED","encrypted_code":None})
                    if not claimed: continue
                    final="CLOSED"
                    if not still_valid(): return None
                    ciphertext=base64.b64decode(envelope,validate=True)
                    decoded=subprocess.run(["openssl","pkeyutl","-decrypt","-inkey",str(key),"-pkeyopt","rsa_padding_mode:oaep","-pkeyopt","rsa_oaep_md:sha256","-pkeyopt","rsa_mgf1_md:sha256"],input=ciphertext,check=True,capture_output=True,timeout=10).stdout.decode("ascii")
                    if re.fullmatch(r"[A-Za-z0-9]{6,12}",decoded):
                        return decoded
                    return None
                page.wait_for_timeout(1500)
            return None
        finally:
            try:
                patch({"id":"eq."+challenge_id,"status":"in.(WAITING,RECEIVED)"},{"status":final,"encrypted_code":None})
            except Exception:
                print("Application verification cleanup: request expired or cleanup unavailable")
