"""Read only recent LinkedIn/Naukri/Indeed job-alert emails from Gmail."""
import os, re, imaplib, email, ssl
from email import policy
from email.utils import parseaddr
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, parse_qs, unquote
from datetime import datetime, timedelta, timezone
from india_sources import relevant_role, india_location

DOMAINS=("linkedin.com","naukri.com","indeed.com")
def domain_matches(host, domain):
    return host==domain or host.endswith("."+domain)
def platform(url):
    u=urlsplit(url)
    if u.scheme!="https" or u.username or u.password: return ""
    host=u.hostname or ""
    if domain_matches(host,"linkedin.com") and re.search(r"/jobs/view/(?:[^/]*-)?\d+/?$",u.path):
        return "linkedin_alert"
    if domain_matches(host,"naukri.com") and u.path.startswith("/job-listings-"):
        return "naukri_alert"
    if domain_matches(host,"indeed.com") and u.path.rstrip("/") in ("/viewjob","/rc/clk","/pagead/clk") and re.fullmatch(r"[a-fA-F0-9]{16}",parse_qs(u.query).get("jk",[""])[0]):
        return "indeed_alert"
    return ""
class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current=None
        self.rows=[]
    def handle_starttag(self,tag,attrs):
        if tag=="a": self.current=[dict(attrs).get("href",""),[]]
    def handle_data(self,data):
        if self.current: self.current[1].append(data)
    def handle_endtag(self,tag):
        if tag=="a" and self.current:
            self.rows.append((self.current[0]," ".join(self.current[1])))
            self.current=None
def parse_alert(content, subject, origin):
    p=Links()
    p.feed(content)
    jobs=[]; seen=set()
    for url,label in p.rows:
        try:
            u=urlsplit(url)
            if u.scheme=="https" and any(domain_matches(u.hostname or "",d) for d in DOMAINS):
                for k in ("url","redirectUrl","redirect","target","destination"):
                    nested=parse_qs(u.query).get(k,[])
                    if len(nested)==1 and platform(nested[0])==origin:
                        url=nested[0]; break
            src=platform(url)
        except ValueError: continue
        if src!=origin: continue
        title=" ".join(label.split())
        if not relevant_role(title):
            slug=urlsplit(url).path.rsplit("/",1)[-1].replace("-"," ")
            if not relevant_role(slug): continue
            title=slug[:180]
        if len(title)>200: continue
        u=urlsplit(url)
        if src=="indeed_alert":
            canonical="https://in.indeed.com/viewjob?jk="+parse_qs(u.query)["jk"][0].lower()
        else: canonical=urlunsplit((u.scheme,u.netloc,u.path,"",""))
        if canonical in seen: continue
        seen.add(canonical)
        # Do not infer exact location or skill requirements from an email's subject/search criteria.
        location=title if india_location(title) else "Unverified location"
        jobs.append(dict(company="",title=title,location=location,description="",url=canonical,source=src))
    return jobs
def discover_alerts():
    user=os.getenv("SMTP_USER",""); password=os.getenv("SMTP_APP_PASSWORD","")
    if not user or not password: return []
    results=[]
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com",993,ssl_context=ssl.create_default_context(),timeout=30) as box:
            box.login(user,password.replace(" ",""))
            status,_=box.select('"[Gmail]/All Mail"',readonly=True)
            if status!="OK": return []
            since=(datetime.now(timezone.utc)-timedelta(days=7)).strftime("%d-%b-%Y")
            for domain,origin in [("linkedin.com","linkedin_alert"),("naukri.com","naukri_alert"),("indeed.com","indeed_alert")]:
                typ,ids=box.uid("search",None,"SINCE",since,"FROM",'"'+domain+'"')
                if typ!="OK": continue
                selected=(ids[0] or b"").split()[-40:]
                print("Alert messages found:",origin,len(selected))
                for uid in selected:
                    typ,data=box.uid("fetch",uid,"(BODY.PEEK[])")
                    if typ!="OK": continue
                    for item in data:
                        if not isinstance(item,tuple): continue
                        message=email.message_from_bytes(item[1],policy=policy.default)
                        sender=parseaddr(str(message.get("From","")))[1].lower().rsplit("@",1)[-1]
                        if not domain_matches(sender,domain): continue
                        for part in message.walk():
                            if part.get_content_type()=="text/html" and part.get_content_disposition()!="attachment":
                                results.extend(parse_alert(part.get_content(),str(message.get("Subject","")),origin))
    except Exception as exc:
        print("Gmail job alerts unavailable:",type(exc).__name__)
    print("LinkedIn/Naukri/Indeed alert links:",len(results))
    return results
