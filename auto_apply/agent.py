"""Scheduled job matcher and opt-in email application agent (stdlib only)."""
import csv, hashlib, json, os, re, smtplib, ssl, subprocess, sys
from email.message import EmailMessage
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import quote, urlparse
from html import unescape
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "ledger.json"
ROLES = r"\b(devops|site reliability|sre|cloud (?:engineer|platform|infrastructure)|platform engineer|release engineer)\b"
SKILLS = ["aws","azure","jenkins","kubernetes","openshift","docker","terraform","linux","python","ci/cd","jfrog","git","dynatrace","splunk","ansible","prometheus","grafana","helm","argocd","gcp","datadog","bash","github actions"]
def clean(s):
    return unescape(re.sub(r"<[^>]+>", " ", str(s or ""))).lower()
def has(s, term):
    return bool(re.search(r"(?<![\w])"+re.escape(term)+r"(?![\w])", s))
def match(job, profile):
    title, body, loc = map(clean, (job.get("title"),job.get("description"),job.get("location")))
    if not re.search(ROLES,title) or re.search(r"\b(senior|sr\.?|lead|principal|staff|manager|architect|intern)\b",title):
        return 0, [], [], "role"
    if not any(has(loc,x.lower()) for x in profile["locations"]):
        return 0, [], [], "location"
    years = re.findall(r"(\d+)\s*(?:\+|[-–]\s*\d+)?\s*(?:years|yrs)\b",body)
    if years and max(map(int,years))>profile["max_required_years"]:
        return 0, [], [], "experience"
    required = [s for s in SKILLS if has(body,s)]
    own = set(x.lower() for x in profile["skills"])
    matched = [s for s in required if s in own]
    missing = [s for s in required if s not in own]
    score = round(100*len(matched)/len(required)) if len(required)>=3 else 0
    return score, matched, missing, "matched" if years else "experience unclear"
def get_jobs():
    jobs = json.loads(os.getenv("JOB_FEED_JSON","").strip() or "[]")
    if not isinstance(jobs,list): raise ValueError("JOB_FEED_JSON must be an array")
    defaults = {"greenhouse": "crashplan,razorpaysoftwareprivatelimited,singlestore,toradex,conviva,pointwild,neweratech,machinify-india,merqube,axicorpfinancialservicesptyltd,insurityindia,backbase", "lever": "smart-working-solutions,pditechnologies,ttecdigital,zeta,brightedge,keyloop,hevodata,brillio-2"}
    sources = []
    for kind in defaults:
        value = os.getenv(kind.upper()+"_BOARDS","").strip() or defaults[kind]
        sources.extend((kind,b.strip()) for b in value.split(",") if re.fullmatch(r"[a-zA-Z0-9_-]+",b.strip()))
    def fetch(source):
        kind, board = source
        try:
            url = ("https://boards-api.greenhouse.io/v1/boards/"+quote(board)+"/jobs?content=true" if kind=="greenhouse" else "https://api.lever.co/v0/postings/"+quote(board)+"?mode=json")
            with urlopen(url,timeout=25) as r:
                data=json.load(r)
            found=[]
            for j in (data["jobs"] if kind=="greenhouse" else data):
                if kind=="greenhouse":
                    found.append(dict(id=str(j["id"]),company=board,title=j["title"],description=j.get("content",""),location=j.get("location",{}).get("name",""),url=j.get("absolute_url",""),source=kind))
                else:
                    found.append(dict(id=str(j["id"]),company=board,title=j.get("text",""),description=j.get("descriptionPlain","")+" "+ " ".join(x.get("text","")+" "+x.get("content","") for x in j.get("lists",[])),location=j.get("categories",{}).get("location",""),url=j.get("hostedUrl",""),source=kind))
            print("Source:",kind,board,"jobs:",len(found))
            return found
        except Exception as e:
            print("Board unavailable:",kind,board,type(e).__name__,file=sys.stderr)
            return []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for found in pool.map(fetch,sources):
            jobs.extend(found)
    if not jobs: print("No jobs discovered. Configure GREENHOUSE_BOARDS or JOB_FEED_JSON.")
    return jobs
def key(j):
    identity = str(j.get("company","")).strip().lower()+"|"+str(j.get("title","")).strip().lower()+"|"+str(j.get("location","")).strip().lower()
    return hashlib.sha256(identity.encode()).hexdigest()
def persist(ledger):
    STATE.write_text(json.dumps(ledger,indent=2,sort_keys=True)+"\n")
    if os.getenv("GITHUB_ACTIONS")=="true":
        subprocess.run(["git","add",str(STATE)],check=True)
        subprocess.run(["git","commit","-m","Update application ledger"],check=True)
        subprocess.run(["git","push"],check=True)
def email_apply(j,profile,resume):
    address=j["application_email"]
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",address): raise ValueError("Invalid address")
    msg=EmailMessage()
    msg["From"]=os.environ["SMTP_USER"]
    msg["To"]=address
    msg["Subject"]="Application: "+str(j["title"]).replace("\n"," ").replace("\r"," ")
    msg.set_content("Dear Hiring Team,\n\nI would like to apply for the "+str(j["title"])+" position. My resume is attached for your consideration. I would welcome the opportunity to discuss how my experience aligns with your requirements.\n\nRegards,\n"+profile["name"])
    msg.add_attachment(resume,maintype="application",subtype="pdf",filename="Resume.pdf")
    with smtplib.SMTP_SSL("smtp.gmail.com",465,context=ssl.create_default_context(),timeout=30) as smtp:
        smtp.login(os.environ["SMTP_USER"],os.environ["SMTP_APP_PASSWORD"])
        refused=smtp.send_message(msg)
        if refused: raise RuntimeError("Recipient refused")
def main():
    import base64
    profile=json.loads(os.environ["PROFILE_JSON"])
    ledger=json.loads(STATE.read_text()) if STATE.exists() else {}
    auto=os.getenv("AUTO_APPLY","false").lower()=="true"
    resume=base64.b64decode(os.getenv("RESUME_BASE64","") or (os.getenv("RESUME_PART_1","")+os.getenv("RESUME_PART_2","")),validate=True) if auto else b""
    if auto and (not resume.startswith(b"%PDF-") or not os.getenv("SMTP_USER") or not os.getenv("SMTP_APP_PASSWORD")):
        raise ValueError("Auto mode requires PDF resume and SMTP credentials")
    jobs=get_jobs()
    ranked=sorted(((match(j,profile),j) for j in jobs),key=lambda x:x[0][0],reverse=True)
    count=0; rows=[]; seen=set()
    for (score,matched,missing,reason),j in ranked:
        k=key(j)
        if k in seen: continue
        seen.add(k)
        if score<profile.get("minimum_match",80): continue
        status=ledger.get(k,"review_portal")
        eligible=reason=="matched" and j.get("application_email") and j.get("email_application_authorized") is True and j.get("source") not in ("greenhouse","lever")
        if k not in ledger and eligible:
            status="ready_email"
            if auto and count<min(int(profile.get("max_per_run",5)),10):
                ledger[k]="reserved"; persist(ledger); count+=1
                try:
                    email_apply(j,profile,resume)
                    ledger[k]="sent"; status="sent"
                except Exception:
                    ledger[k]="uncertain_manual_review"; status=ledger[k]
                persist(ledger)
        rows.append([j.get("company"),j.get("title"),j.get("location"),score,", ".join(matched),", ".join(missing),reason,status,j.get("url")])
    with (ROOT/"matches.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["company","title","location","skill_match","matched","missing","experience","status","url"]); w.writerows(rows)
    print(f"Scanned {len(jobs)} jobs; {len(rows)} matches; {count} attempted email applications.")
if __name__=="__main__": main()
