"""Read-only acknowledgment matching; no email bodies or identifiers persisted."""
import email, imaplib, os, re, ssl
from email import policy
from email.utils import parseaddr
from datetime import datetime, timedelta, timezone
from html import unescape

def normal(value):
    return re.sub(r"[^a-z0-9]+"," ",str(value or "").lower()).strip()
def ack_matches(subject, body, sender, job):
    title=normal(job.get("title"))
    company=normal(job.get("company"))
    if not title or not company: return False
    domain=parseaddr(sender)[1].lower().rsplit("@",1)[-1]
    if not domain or domain in ("gmail.com","outlook.com","yahoo.com","hotmail.com"): return False
    trusted=any(domain==d or domain.endswith("."+d) for d in ("ashbyhq.com","greenhouse.io","lever.co","smartrecruiters.com"))
    compact=lambda s:re.sub(r"[^a-z0-9]","",s)
    company_domain=compact(company) in compact(domain.split(".")[0]) if len(compact(company))>=5 else False
    if not (trusted or company_domain): return False
    text=normal(subject+" "+body)
    acknowledgment=bool(re.search(r"\b(?:thank you for applying|thanks for applying|(?:we have|we ve|we) received your application|your application (?:has been )?(?:successfully )?(?:received|submitted)|application confirmation)\b",text))
    rejection=bool(re.search(r"\b(?:could not submit|failed to submit|not received|incomplete application|delivery failure)\b",text))
    return acknowledgment and not rejection and title in text and (compact(company) in compact(text) or company_domain)
def read_acknowledgments():
    user=os.getenv("SMTP_USER",""); password=os.getenv("SMTP_APP_PASSWORD","")
    if not user or not password: return []
    rows=[]
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com",993,ssl_context=ssl.create_default_context(),timeout=25) as box:
            box.login(user,password.replace(" ",""))
            typ,_=box.select('"[Gmail]/All Mail"',readonly=True)
            if typ!="OK": return []
            since=(datetime.now(timezone.utc)-timedelta(days=7)).strftime("%d-%b-%Y")
            typ,ids=box.uid("search",None,"SINCE",since,"OR","SUBJECT",'"application"',"SUBJECT",'"applying"')
            if typ!="OK": return []
            for uid in (ids[0] or b"").split()[-100:]:
                typ,parts=box.uid("fetch",uid,"(BODY.PEEK[])")
                if typ!="OK": continue
                for item in parts:
                    if not isinstance(item,tuple): continue
                    msg=email.message_from_bytes(item[1],policy=policy.default)
                    body=msg.get_body(preferencelist=("plain","html"))
                    if body is None: continue
                    content=unescape(re.sub(r"<[^>]*>"," ",str(body.get_content())))[:24000]
                    auth=" ".join(str(v) for v in msg.get_all("Authentication-Results",[]))
                    if not re.search(r"\b(?:dkim|dmarc)=pass\b",auth,re.I): continue
                    rows.append((str(msg.get("Subject","")),content,str(msg.get("From",""))))
    except Exception as exc:
        print("Acknowledgment mailbox check unavailable:",type(exc).__name__)
    print("Authenticated acknowledgment candidates:",len(rows))
    return rows
