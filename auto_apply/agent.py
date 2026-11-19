"""Scheduled job matcher and opt-in email application agent (stdlib only)."""
import csv, hashlib, json, os, re, smtplib, ssl, subprocess, sys, io
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote, urlparse
from html import unescape
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from india_sources import india_location, relevant_role, technology_role, technology_category, discover
from reconcile import read_acknowledgments, ack_matches

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "ledger.json"
ROLES = r"\b(devops|devsecops|site reliability|sre|cloud (?:engineer|platform|infrastructure|operations)|platform engineer|release engineer)\b"
SKILLS = [
    "java","spring boot",".net","c#","python","javascript","typescript","react","angular","node.js","golang","php","ruby","scala",
    "android","ios","sql","postgresql","mysql","mongodb","redis","kafka","spark","databricks","snowflake","etl","power bi","tableau",
    "machine learning","tensorflow","pytorch","llm","genai","aws","azure","gcp","jenkins","github actions","kubernetes","openshift",
    "docker","terraform","ansible","linux","bash","ci/cd","jfrog","git","dynatrace","splunk","prometheus","grafana","helm","argocd",
    "datadog","selenium","playwright","cypress","appium","jmeter","postman","cybersecurity","iam","servicenow","salesforce","sap"
]
def clean(s):
    return unescape(re.sub(r"<[^>]+>", " ", str(s or ""))).lower()
def has(s, term):
    return bool(re.search(r"(?<![\w])"+re.escape(term)+r"(?![\w])", s))
def normalize_published(value):
    if value in (None,""):
        return ""
    if isinstance(value,(int,float)):
        number=float(value)
        if number>10_000_000_000:
            number/=1000
        try:
            return datetime.fromtimestamp(number,tz=timezone.utc).isoformat()
        except Exception:
            return ""
    raw=str(value).strip()
    if not raw:
        return ""
    try:
        dt=datetime.fromisoformat(raw.replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return ""

def published_within_days(value,days=30):
    published=normalize_published(value)
    if not published:
        return False
    try:
        dt=datetime.fromisoformat(published)
    except Exception:
        return False
    now=datetime.now(timezone.utc)
    return now-timedelta(days=days) <= dt <= now+timedelta(hours=6)

ATS_DOMAINS=(
    "greenhouse.io","lever.co","ashbyhq.com","smartrecruiters.com","myworkdayjobs.com","workdayjobs.com",
    "icims.com","taleo.net","successfactors.com","oraclecloud.com","eightfold.ai","jobvite.com",
    "recruitee.com","workable.com","bamboohr.com","freshteam.com","phenompeople.com"
)
PORTAL_DOMAINS=("linkedin.com","indeed.com","naukri.com","foundit.in","foundit.com")

def host_matches(host,domain):
    host=str(host or "").lower()
    return host==domain or host.endswith("."+domain)

def known_direct_apply_url(url):
    try:
        u=urlparse(unescape(str(url or "")).replace("&amp;","&"))
    except Exception:
        return ""
    if u.scheme!="https" or not u.hostname:
        return ""
    host=u.hostname.lower()
    if any(host_matches(host,d) for d in PORTAL_DOMAINS):
        return ""
    if any(host_matches(host,d) for d in ATS_DOMAINS):
        return u.geturl()
    return ""

def _jsonld_job(value):
    if isinstance(value,dict):
        kind=value.get("@type")
        kinds=kind if isinstance(kind,list) else [kind]
        if "JobPosting" in kinds:
            return value
        for nested in value.values():
            found=_jsonld_job(nested)
            if found:
                return found
    elif isinstance(value,list):
        for nested in value:
            found=_jsonld_job(nested)
            if found:
                return found
    return None

def enrich_alert_job(job):
    """Verify a portal-alert job and resolve a direct ATS URL when exposed publicly."""
    original=str(job.get("listing_url") or job.get("url") or "").strip()
    if not original:
        return None
    try:
        req=Request(original,headers={
            "User-Agent":"Mozilla/5.0 (compatible; DraftflowAIJobs/1.0)",
            "Accept":"text/html,application/xhtml+xml",
        })
        with urlopen(req,timeout=12) as response:
            html=response.read(1_500_000).decode("utf-8","ignore")
            final_url=response.geturl()
    except Exception:
        return None
    found=None
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',html,re.I|re.S):
        try:
            parsed=json.loads(unescape(raw).strip())
        except Exception:
            continue
        found=_jsonld_job(parsed)
        if found:
            break
    enriched=dict(job)
    if found:
        title=str(found.get("title") or enriched.get("title") or "").strip()
        company_obj=found.get("hiringOrganization") or {}
        company=str(company_obj.get("name") if isinstance(company_obj,dict) else "").strip()
        locations=found.get("jobLocation") or []
        if isinstance(locations,dict):
            locations=[locations]
        bits=[]
        for loc in locations:
            if not isinstance(loc,dict):
                continue
            addr=loc.get("address") or {}
            if isinstance(addr,dict):
                bits.extend(str(addr.get(k) or "").strip() for k in ("addressLocality","addressRegion","addressCountry"))
        location=" | ".join(x for x in bits if x)
        description=str(found.get("description") or "").strip()
        published=normalize_published(found.get("datePosted") or enriched.get("published"))
        if title:
            enriched["title"]=title
        if company:
            enriched["company"]=company
        if location:
            enriched["location"]=location
        if description:
            enriched["description"]=description
        if published:
            enriched["published"]=published
    candidates=[final_url]
    candidates.extend(re.findall(r'href=["\']([^"\']+)["\']',html,re.I))
    direct=""
    for candidate in candidates:
        direct=known_direct_apply_url(candidate)
        if direct:
            break
        try:
            u=urlparse(unescape(candidate).replace("&amp;","&"))
            from urllib.parse import parse_qs
            for key in ("url","redirectUrl","redirect","target","destination","applyUrl"):
                for nested in parse_qs(u.query).get(key,[]):
                    direct=known_direct_apply_url(nested)
                    if direct:
                        break
                if direct:
                    break
        except Exception:
            pass
        if direct:
            break
    enriched["listing_url"]=original
    if direct:
        enriched["url"]=direct
        enriched["direct_apply"]=True
    else:
        enriched["url"]=original
        enriched["direct_apply"]=False
    if not technology_role(enriched.get("title")):
        return None
    if not india_location(enriched.get("location")):
        return None
    if not published_within_days(enriched.get("published"),30):
        return None
    return enriched

def extract_experience_requirement(text):
    """Return a conservative min/max years requirement from public job text."""
    body=clean(text)
    patterns=(
        (r"\b(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s*(?:years|yrs)\b", "range"),
        (r"\b(\d{1,2})\s*\+\s*(?:years|yrs)\b", "plus"),
        (r"\b(?:minimum|min\.?|at least)\s*(?:of\s*)?(\d{1,2})\s*(?:years|yrs)\b", "plus"),
        (r"\b(\d{1,2})\s*(?:years|yrs)\s+(?:of\s+)?(?:relevant\s+|professional\s+|overall\s+|total\s+)?experience\b", "exact"),
    )
    for pattern,kind in patterns:
        m=re.search(pattern,body,re.I)
        if not m:
            continue
        lo=int(m.group(1))
        if lo>20:
            continue
        if kind=="range":
            hi=int(m.group(2))
            if hi<lo or hi>30:
                continue
            return {"min":lo,"max":hi,"label":f"{lo}-{hi} years"}
        if kind=="plus":
            return {"min":lo,"max":None,"label":f"{lo}+ years"}
        return {"min":lo,"max":lo,"label":f"{lo} years"}
    return {"min":None,"max":None,"label":"Not specified"}

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
    weights={"aws":3,"azure":3,"kubernetes":3,"openshift":3,"jenkins":3,"ci/cd":3,"terraform":3,"docker":2,"linux":2,"python":2,"gcp":3,"ansible":2,"prometheus":2,"grafana":2}
    score = round(100*sum(weights.get(s,1) for s in matched)/sum(weights.get(s,1) for s in required)) if len(required)>=3 else 0
    return score, matched, missing, "matched" if years else "experience unclear"
def aggregator_jobs():
    """Load optional approved aggregator/partner feed rows without accessing email."""
    raw=os.getenv("AGGREGATOR_JOB_FEED_JSON","").strip()
    if not raw:
        return []
    try:
        rows=json.loads(raw)
    except Exception:
        print("AGGREGATOR_JOB_FEED_JSON is invalid JSON",file=sys.stderr)
        return []
    if not isinstance(rows,list):
        return []
    allowed={"linkedin","indeed","naukri","foundit"}
    jobs=[]
    for row in rows:
        if not isinstance(row,dict):
            continue
        source=str(row.get("source","")).strip().lower()
        title=str(row.get("title","")).strip()
        location=str(row.get("location","")).strip()
        listing=str(row.get("listing_url") or row.get("url") or "").strip()
        direct=str(row.get("direct_apply_url") or "").strip()
        published=normalize_published(row.get("published") or row.get("published_at"))
        if source not in allowed or not title or not technology_role(title) or not india_location(location):
            continue
        if not published_within_days(published,30):
            continue
        if not listing:
            continue
        listing_parsed=urlparse(listing)
        if listing_parsed.scheme!="https" or not listing_parsed.hostname:
            continue
        if direct:
            direct_parsed=urlparse(direct)
            if direct_parsed.scheme!="https" or not direct_parsed.hostname:
                direct=""
        jobs.append({
            "company":str(row.get("company","")).strip() or "Company",
            "title":title,
            "location":location,
            "description":str(row.get("description","")),
            "url":listing,
            "listing_url":listing,
            "direct_apply_url":direct,
            "published":published,
            "source":source,
        })
    print("Approved aggregator feed jobs:",len(jobs))
    return jobs

def get_jobs():
    jobs = json.loads(os.getenv("JOB_FEED_JSON","").strip() or "[]")
    if not isinstance(jobs,list): raise ValueError("JOB_FEED_JSON must be an array")
    defaults = {"greenhouse":"crashplan,pointwild,conviva,toradex,razorpaysoftwareprivatelimited,singlestore,machinify-india,neweratech,workatbackbase,axicorpfinancialservicesptyltd,insurityindia,merqube,mfsgtechnologiesindia,rhythmx-ai,sonicwall,zscaler,cloudflare,grafanalabs,databricks,canonical,elastic,gitlab,mongodb,twilio,okta,mastercontrol,acquia,datadog,remote,toast,affirm,coinbase,asana,reddit,webflow,netlify,vercel,rubrik,druva,thoughtworks,branch,workato,celonis,pagerduty,cockroachlabs,chainguard,particle41llc,coherehealth","lever":"pditechnologies,smart-working-solutions,brightedge,zeta,ttecdigital,keyloop,hevodata,spotify,wealthsimple,contentsquare,brillio-2,shyftlabs,lingarogroup,mactores,zimperium"}
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
                    found.append(dict(id=str(j["id"]),company=board,title=j["title"],description=j.get("content",""),location=j.get("location",{}).get("name",""),url=j.get("absolute_url",""),published=normalize_published(j.get("updated_at") or j.get("created_at")),source=kind))
                else:
                    found.append(dict(id=str(j["id"]),company=board,title=j.get("text",""),description=j.get("descriptionPlain","")+" "+ " ".join(x.get("text","")+" "+x.get("content","") for x in j.get("lists",[])),location=j.get("categories",{}).get("location",""),url=j.get("hostedUrl",""),published=normalize_published(j.get("createdAt") or j.get("updatedAt")),source=kind))
            print("Source:",kind,board,"jobs:",len(found))
            return found
        except Exception as e:
            print("Board unavailable:",kind,board,type(e).__name__,file=sys.stderr)
            return []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for found in pool.map(fetch,sources):
            jobs.extend(found)
    print("Raw legacy board jobs:",len(jobs))
    jobs=[j for j in jobs if india_location(j.get("location")) and technology_role(j.get("title"))]
    jobs.extend(discover(all_tech=True))
    jobs.extend(aggregator_jobs())
    if not jobs: print("No India-based technology jobs discovered.")
    return jobs
def key(j):
    identity = str(j.get("company","")).strip().lower()+"|"+str(j.get("title","")).strip().lower()+"|"+str(j.get("location","")).strip().lower()
    return hashlib.sha256(identity.encode()).hexdigest()
def persist(ledger):
    STATE.write_text(json.dumps(ledger,indent=2,sort_keys=True)+"\n")
    if os.getenv("GITHUB_ACTIONS")=="true":
        subprocess.run(["git","add",str(STATE)],check=True)
        if subprocess.run(["git","diff","--cached","--quiet"]).returncode==0:
            return
        subprocess.run(["git","commit","-m","Update application ledger"],check=True)
        for attempt in range(3):
            pushed=subprocess.run(["git","push"],capture_output=True,text=True)
            if pushed.returncode==0:
                return
            print("Ledger push retry:",attempt+1,file=sys.stderr)
            rebased=subprocess.run(["git","pull","--rebase","origin","main"],capture_output=True,text=True)
            if rebased.returncode!=0:
                subprocess.run(["git","rebase","--abort"],capture_output=True)
                raise RuntimeError("Ledger rebase failed")
        raise RuntimeError("Ledger push failed after retries")
def publish_public_feed(jobs):
    """Publish a sanitized job-only feed for the public UI."""
    aliases={"aws":["amazon web services"],"azure":["microsoft azure"],"kubernetes":["k8s","eks","aks"],"openshift":["ocp","red hat openshift"],"ci/cd":["cicd","ci cd","continuous integration","continuous delivery","continuous deployment"],"jfrog":["artifactory"],"gcp":["google cloud"],"argocd":["argo cd"]}
    public=[]
    seen=set()
    for j in jobs:
        title=str(j.get("title","")).strip()
        location=str(j.get("location","")).strip()
        listing_url=str(j.get("listing_url") or j.get("url") or "").strip()
        direct_apply_url=str(j.get("direct_apply_url") or j.get("apply_url") or "").strip()
        url=direct_apply_url or listing_url
        if not title or not technology_role(title) or not india_location(location):
            continue
        parsed=urlparse(url)
        if parsed.scheme!="https" or not parsed.hostname:
            continue
        identity=(str(j.get("company","")).strip().lower(),title.lower(),location.lower(),listing_url or url)
        if identity in seen:
            continue
        seen.add(identity)
        published=normalize_published(j.get("published") or j.get("publishedAt") or j.get("created_at"))
        if not published_within_days(published,30):
            continue
        category=technology_category(title)
        body=clean(j.get("description",""))
        experience=extract_experience_requirement(j.get("description",""))
        skills=[]
        for skill in SKILLS:
            if any(has(body,t) for t in [skill]+aliases.get(skill,[])):
                skills.append(skill)
        source=str(j.get("source","career_site")).strip() or "career_site"
        direct_apply=bool(direct_apply_url) or source in {"greenhouse","lever","ashby","smartrecruiters"}
        public.append({
            "id":hashlib.sha256("|".join(identity).encode()).hexdigest()[:16],
            "title":title,
            "company":str(j.get("company","")).strip() or "Company",
            "location":location,
            "source":source,
            "category":category,
            "published":published,
            "url":url,
            "listing_url":listing_url or url,
            "direct_apply":direct_apply,
            "listing_url":str(j.get("listing_url") or "").strip(),
            "direct_apply":bool(j.get("direct_apply", j.get("source") in ("greenhouse","lever","ashby","smartrecruiters"))),
            "skills":skills[:12],
            "experience_min":experience["min"],
            "experience_max":experience["max"],
            "experience_label":experience["label"],
        })
    public.sort(key=lambda x:(x.get("published",""),x["title"].lower()),reverse=True)
    target=ROOT.parent/"data"/"jobs.json"
    target.parent.mkdir(parents=True,exist_ok=True)
    old=None
    try:
        old=json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        pass
    if isinstance(old,dict) and old.get("jobs")==public:
        print("Public job feed unchanged:",len(public))
        return
    payload={"generated_at_utc":datetime.now(timezone.utc).isoformat(),"count":len(public),"jobs":public}
    target.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("Public job feed updated:",len(public))
    if os.getenv("GITHUB_ACTIONS")=="true":
        subprocess.run(["git","add",str(target)],check=True)
        if subprocess.run(["git","diff","--cached","--quiet"]).returncode==0:
            return
        subprocess.run(["git","commit","-m","Refresh public job feed"],check=True)
        for attempt in range(3):
            pushed=subprocess.run(["git","push"],capture_output=True,text=True)
            if pushed.returncode==0:
                return
            print("Feed push retry:",attempt+1,file=sys.stderr)
            rebased=subprocess.run(["git","pull","--rebase","origin","main"],capture_output=True,text=True)
            if rebased.returncode!=0:
                subprocess.run(["git","rebase","--abort"],capture_output=True)
                raise RuntimeError("Feed rebase failed")
        raise RuntimeError("Feed push failed after retries")

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
    public_only=os.getenv("PUBLIC_FEED_ONLY","").strip().lower()=="true"
    if public_only:
        jobs=get_jobs()
        publish_public_feed(jobs)
        print("Public discovery-only refresh complete:",len(jobs))
        return
    profile=json.loads(os.environ["PROFILE_JSON"])
    actual_years=float(profile.get("experience_years",profile.get("max_required_years",3)))
    profile["max_required_years"]=max(actual_years,4)
    profile["minimum_match"]=0  # Skill score ranks jobs; never rejects them.
    ledger=json.loads(STATE.read_text()) if STATE.exists() else {}
    auto=os.getenv("AUTO_APPLY","").strip().lower()!="false"
    part1=os.getenv("RESUME_PART_1","")
    part2=os.getenv("RESUME_PART_2","")
    raw=(part1+part2) if part1 and part2 else os.getenv("RESUME_BASE64","")
    try: resume=base64.b64decode("".join(raw.split()),validate=True)
    except Exception: resume=b""
    print("Resume PDF header valid:", resume.startswith(b"%PDF-"))
    print("Resume decoded size in bytes:",len(resume))
    try:
        from pypdf import PdfReader
        if not resume.startswith(b"%PDF-") or not resume.rstrip().endswith(b"%%EOF"): raise ValueError("Incomplete PDF")
        pdf=PdfReader(io.BytesIO(resume))
        if not pdf.pages: raise ValueError("Empty PDF")
        for page in pdf.pages: page.extract_text()
        print("Resume PDF fully validated; pages:",len(pdf.pages))
    except Exception as exc:
        print("Resume validation failed:",type(exc).__name__,"Check complete RESUME_BASE64 or both RESUME_PART secrets.")
        resume=b""
    if auto and (not resume.startswith(b"%PDF-") or not os.getenv("SMTP_USER") or not os.getenv("SMTP_APP_PASSWORD")):
        print("Email auto-apply disabled: missing PDF or SMTP configuration."); auto=False
    jobs=get_jobs()
    alerts=discover_alerts()
    enriched_alerts=[]
    for alert in alerts:
        enriched=enrich_alert_job(alert)
        if enriched:
            enriched_alerts.append(enriched)
    print("Verified portal alert jobs added to public feed:",len(enriched_alerts))
    publish_public_feed(jobs+enriched_alerts)
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
    def priority(item):
        (score,matched,missing,reason),j=item
        return (score, j.get("published") or "")
    ranked=sorted(((match(j,profile),j) for j in jobs),key=priority,reverse=True)
    count=0; rows=[]; seen=set()
    from portal import portal_apply, portal_enabled
    portal_count=0
    portal_limit=max(1,min(int(profile.get("max_portal_per_run",10)),20))
    screening_report=[]
    portal_on=portal_enabled(profile,resume)
    # Retry legacy pre-submission failures once using the improved checks.
    # Never retry unknown outcomes or reservations automatically.
    if portal_on:
        ledger={k:v for k,v in ledger.items() if v not in ("portal_review_candidate_error","portal_review_human_verification","portal_review_choices","portal_review_unanswered_select","portal_review_unanswered_fields","portal_review_missing_screening_v3","portal_review_resume_sync","portal_review_form_sync_busy","portal_review_no_submit_operation","portal_uncertain_server_accepted")}
    print("Email enabled:",auto,"Portal enabled:",portal_on)
    print("Filter outcomes:",dict(Counter(reason for (score,matched,missing,reason),j in ranked)))
    confirmed=0
    reconciled=0
    acknowledgments=read_acknowledgments() if any(str(v).startswith(('portal_uncertain','portal_reserved')) for v in ledger.values()) else []
    email_sent=0
    audit=[]
    def audit_row(j,score,matched,missing,reason,status):
        audit.append([j.get("source",""),j.get("company",""),j.get("title",""),j.get("location",""),score,", ".join(matched),", ".join(missing),reason,status,j.get("published",""),j.get("url","")])
    for (score,matched,missing,reason),j in ranked:
        k=key(j)
        if k in seen:
            audit_row(j,score,matched,missing,reason,"duplicate_in_run"); continue
        seen.add(k)
        if reason in ("role","location","experience"):
            audit_row(j,score,matched,missing,reason,"filtered_"+reason); continue
        real_profile=dict(profile,max_required_years=actual_years)
        if match(j,real_profile)[3]=="experience" and reason=="matched": reason="stretch experience"
        can_apply=reason in ("matched","stretch experience","experience unclear")
        status=ledger.get(k,"review_portal")
        if str(status).startswith(("portal_uncertain","portal_reserved")) and any(ack_matches(*message,j) for message in acknowledgments):
            status="portal_confirmed_email"; ledger[k]=status; persist(ledger); reconciled+=1
        if k not in ledger:
            if not can_apply: status="review_"+reason.replace(" ","_")
            elif j.get("source")=="smartrecruiters": status="review_smartrecruiters_form"
            elif not portal_on and not auto: status="review_application_disabled"
            elif j.get("source") in ("greenhouse","lever","ashby") and portal_on: status="portal_eligible_waiting_limit"
            else: status="review_no_supported_application_channel"
        eligible=can_apply and j.get("application_email") and j.get("email_application_authorized") is True and j.get("source") not in ("greenhouse","lever","ashby","smartrecruiters")
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
        if k not in ledger and portal_on and can_apply and j.get("source") in ("greenhouse","lever","ashby") and portal_count<portal_limit:
            ledger[k]="portal_reserved"; persist(ledger); portal_count+=1
            diagnostic={}
            status=portal_apply(j,profile,resume,diagnostic)
            screening_report.append({"company":j.get("company"),"title":j.get("title"),"url":j.get("url"),"status":status,"missing_fields":diagnostic.get("missing_fields",[]),"stage":diagnostic.get("stage",""),"attempted_at_utc":diagnostic.get("attempted_at_utc"),"post_responses":diagnostic.get("post_responses",[]),"confirmation":diagnostic.get("confirmation"),"invalid_field_count":diagnostic.get("invalid_field_count"),"invalid_fields":diagnostic.get("invalid_fields",[]),"visible_alert_count":diagnostic.get("visible_alert_count"),"final_host":diagnostic.get("final_host"),"final_path":diagnostic.get("final_path")})
            if status=="portal_confirmed": confirmed+=1
            print("Portal outcome:",status)
            ledger[k]=status; persist(ledger)
        audit_row(j,score,matched,missing,reason,status)
        rows.append([j.get("company"),j.get("title"),j.get("location"),score,", ".join(matched),", ".join(missing),reason,status,j.get("url")])
    def cell(value):
        if isinstance(value,str) and value.lstrip().startswith(("=","+","-","@")): return "\x27"+value
        return value
    with (ROOT/"job-decisions.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["source","company","title","location","skill_match","matched","missing","experience","decision","published","url"]); w.writerows([cell(v) for v in row] for row in audit)
    with (ROOT/"matches.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["company","title","location","skill_match","matched","missing","experience","status","url"]); w.writerows([cell(v) for v in row] for row in rows)
    (ROOT/"screening-review.json").write_text(json.dumps(screening_report,indent=2,ensure_ascii=False))
    summary={"timestamp_utc":datetime.now(timezone.utc).isoformat(),"target_jobs":len(jobs),"matches":len(rows),"email_attempts":count,"portal_attempts":portal_count,"email_accepted":email_sent,"portal_confirmed":confirmed,"email_reconciled":reconciled,"decisions":dict(Counter(row[8] for row in audit)),"sources":dict(Counter(j.get("source","feed") for j in jobs))}
    (ROOT/"run-summary.json").write_text(json.dumps(summary,indent=2))
    print("Gmail reconciled applications:",reconciled)
    print("Decision outcomes:",summary["decisions"])
    print(f"Scanned {len(jobs)} jobs; {len(rows)} matches; {count} attempted email applications; {portal_count} portal attempts; {email_sent} emails accepted by SMTP; {confirmed} portal confirmations.")
if __name__=="__main__": main()
