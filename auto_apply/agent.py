"""Scheduled job matcher and opt-in email application agent (stdlib only)."""
import csv, hashlib, json, os, re, smtplib, ssl, subprocess, sys
from email.message import EmailMessage
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import quote, urlparse
from html import unescape
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from india_sources import india_location, relevant_role, discover
from job_alerts import discover_alerts

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "ledger.json"
ROLES = r"\b(devops|devsecops|site reliability|sre|cloud (?:engineer|platform|infrastructure|operations)|platform engineer|release engineer)\b"
SKILLS = ["aws","azure","jenkins","kubernetes","openshift","docker","terraform","linux","python","ci/cd","jfrog","git","dynatrace","splunk","ansible","prometheus","grafana","helm","argocd","gcp","datadog","bash","github actions"]
def clean(s):
    return unescape(re.sub(r"<[^>]+>", " ", str(s or ""))).lower()
def has(s, term):
    return bool(re.search(r"(?<![\w])"+re.escape(term)+r"(?![\w])", s))
def match(job, profile):
    title, body, loc = map(clean, (job.get("title"),job.get("description"),job.get("location")))
    if not relevant_role(title) or re.search(r"\b(senior|sr\.?|lead|principal|staff|manager|architect|intern|director|head)\b",title):
        return 0, [], [], "role"
    if not india_location(loc):
        return 0, [], [], "location"
    years = re.findall(r"(\d+)\s*(?:\+|[-–—]\s*\d+)?\s*(?:years|yrs)\b",body)
    if years and max(map(int,years))>profile["max_required_years"]:
        return 0, [], [], "experience"
    aliases={"aws":["amazon web services"],"azure":["microsoft azure"],"kubernetes":["k8s","eks","aks"],"openshift":["ocp","red hat openshift"],"ci/cd":["cicd","ci cd","continuous integration","continuous delivery","continuous deployment"],"jfrog":["artifactory"],"gcp":["google cloud"],"argocd":["argo cd"]}
    required = [s for s in SKILLS if any(has(body,t) for t in [s]+aliases.get(s,[]))]
    own = set(str(x).lower() for x in profile["skills"])
    own.update(s for s, terms in aliases.items() if any(t in own for t in terms))
    matched = [s for s in required if s in own]
    missing = [s for s in required if s not in own]
    score = round(100*len(matched)/len(required)) if len(required)>=3 else 0
    return score, matched, missing, "matched" if years else "experience unclear"
def get_jobs():
    jobs = json.loads(os.getenv("JOB_FEED_JSON","").strip() or "[]")
    if not isinstance(jobs,list): raise ValueError("JOB_FEED_JSON must be an array")
    defaults = {"greenhouse":"crashplan,pointwild,conviva,toradex,razorpaysoftwareprivatelimited,singlestore,machinify-india,neweratech,workatbackbase,axicorpfinancialservicesptyltd,insurityindia,merqube,mfsgtechnologiesindia,rhythmx-ai,sonicwall,zscaler,cloudflare,grafanalabs,databricks,canonical,elastic,gitlab,mongodb,twilio,okta,mastercontrol,acquia,datadog,remote,toast,affirm,coinbase,asana,reddit,webflow,netlify,vercel,rubrik,druva,thoughtworks,branch,workato,celonis,pagerduty,cockroachlabs,chainguard","lever":"pditechnologies,smart-working-solutions,brightedge,zeta,ttecdigital,keyloop,hevodata,spotify,wealthsimple,contentsquare,brillio-2,shyftlabs"}
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
    print("Raw legacy board jobs:",len(jobs))
    jobs=[j for j in jobs if india_location(j.get("location")) and relevant_role(j.get("title"))]
    jobs.extend(discover())
    if not jobs: print("No India-based target jobs discovered.")
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
    actual_years=float(profile.get("max_required_years",3))
    profile["max_required_years"]=max(actual_years,4)
    profile["minimum_match"]=int(os.getenv("MINIMUM_MATCH","").strip() or "65")
    ledger=json.loads(STATE.read_text()) if STATE.exists() else {}
    auto=os.getenv("AUTO_APPLY","").strip().lower()!="false"
    raw=os.getenv("RESUME_BASE64","") or (os.getenv("RESUME_PART_1","")+os.getenv("RESUME_PART_2",""))
    try: resume=base64.b64decode("".join(raw.split()),validate=True)
    except Exception: resume=b""
    print("Resume PDF header valid:", resume.startswith(b"%PDF-"))
    if auto and (not resume.startswith(b"%PDF-") or not os.getenv("SMTP_USER") or not os.getenv("SMTP_APP_PASSWORD")):
        print("Email auto-apply disabled: missing PDF or SMTP configuration."); auto=False
    jobs=get_jobs()
    alerts=discover_alerts()
    with (ROOT/"platform-alerts.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["source","title","location","status","url"])
        seen_alerts=set()
        for j in alerts:
            if j["url"] in seen_alerts: continue
            seen_alerts.add(j["url"])
            title=j["title"]
            if title.startswith(("=","+","-","@","\t","\r")): title="'"+title
            loc=j["location"]
            if loc.startswith(("=","+","-","@","\t","\r")): loc="'"+loc
            w.writerow([j["source"],title,loc,"review_full_job_description_and_apply",j["url"]])
    print("Unique platform alert links for review:",len(seen_alerts))
    ranked=sorted(((match(j,profile),j) for j in jobs),key=lambda x:x[0][0],reverse=True)
    count=0; rows=[]; seen=set()
    from portal import portal_apply, portal_enabled
    portal_count=0
    portal_on=portal_enabled(profile,resume)
    print("Email enabled:",auto,"Portal enabled:",portal_on)
    print("Filter outcomes:",dict(Counter(reason for (score,matched,missing,reason),j in ranked)))
    confirmed=0
    email_sent=0
    for (score,matched,missing,reason),j in ranked:
        k=key(j)
        if k in seen: continue
        seen.add(k)
        if score<profile.get("minimum_match",65): continue
        real_profile=dict(profile,max_required_years=actual_years)
        if match(j,real_profile)[0]==0 and reason=="matched": reason="stretch experience - review only"
        status=ledger.get(k,"review_portal")
        if k not in ledger:
            if reason!="matched": status="review_"+reason.replace(" ","_")
            elif j.get("source")=="smartrecruiters": status="review_smartrecruiters_form"
            elif not portal_on and not auto: status="review_application_disabled"
            else: status="review_pending_channel"
        eligible=reason=="matched" and score>=65 and j.get("application_email") and j.get("email_application_authorized") is True and j.get("source") not in ("greenhouse","lever","ashby","smartrecruiters")
        if k not in ledger and eligible:
            status="ready_email"
            if auto and count<min(int(profile.get("max_per_run",5)),10):
                ledger[k]="reserved"; persist(ledger); count+=1
                try:
                    email_apply(j,profile,resume)
                    ledger[k]="sent"; status="sent"; email_sent+=1
                except Exception:
                    ledger[k]="uncertain_manual_review"; status=ledger[k]
                persist(ledger)
        if k not in ledger and portal_on and reason=="matched" and score>=80 and j.get("source") in ("greenhouse","lever","ashby") and portal_count<3:
            ledger[k]="portal_reserved"; persist(ledger); portal_count+=1
            status=portal_apply(j,profile,resume)
            if status=="portal_confirmed": confirmed+=1
            print("Portal outcome:",status)
            ledger[k]=status; persist(ledger)
        rows.append([j.get("company"),j.get("title"),j.get("location"),score,", ".join(matched),", ".join(missing),reason,status,j.get("url")])
    with (ROOT/"matches.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["company","title","location","skill_match","matched","missing","experience","status","url"]); w.writerows(rows)
    print(f"Scanned {len(jobs)} jobs; {len(rows)} matches; {count} attempted email applications; {portal_count} portal attempts; {email_sent} emails accepted by SMTP; {confirmed} portal confirmations.")
if __name__=="__main__": main()
