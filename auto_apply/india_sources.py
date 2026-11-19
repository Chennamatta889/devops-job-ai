"""India-focused public career discovery. No authentication or paid API."""
import json, re
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import quote, urlencode
from concurrent.futures import ThreadPoolExecutor
INDIA = re.compile(r"\b(india|hyderabad|secunderabad|bengaluru|bangalore|pune|mumbai|navi mumbai|chennai|gurgaon|gurugram|noida|delhi|kolkata|ahmedabad|kochi|cochin|trivandrum|thiruvananthapuram|coimbatore|mysore|mysuru|indore|jaipur|chandigarh|mohali|bhubaneswar|visakhapatnam|vizag|vadodara|nagpur|lucknow|surat|greater noida|telangana|karnataka|maharashtra|tamil nadu|kerala|gujarat|haryana|uttar pradesh|west bengal|andhra pradesh)\b",re.I)
ROLE = re.compile(r"\b(dev[- ]?ops|devsecops|site reliability|sre|cloud[- ]?ops|cloud (?:engineer|platform|infrastructure|operations|support|administrator)|platform (?:engineer|operations)|(?:it |cloud )?infrastructure (?:engineer|specialist|analyst)|(?:build|release|deployment|production support|production|systems|linux|observability|kubernetes) engineer|(?:devops|cloud|infrastructure) automation engineer|ci/cd engineer)\b",re.I)
TECH_CATEGORIES = (
    ("Cloud / DevOps / SRE", re.compile(r"\b(dev[- ]?ops|devsecops|site reliability|sre|cloud|platform engineer|infrastructure|kubernetes|release engineer|build engineer|observability)\b", re.I)),
    ("Data / AI / ML", re.compile(r"\b(data engineer|data scientist|data analyst|analytics engineer|machine learning|ml engineer|artificial intelligence|ai engineer|genai|generative ai|llm|nlp|computer vision|big data|etl|spark|databricks|snowflake)\b", re.I)),
    ("QA / Testing", re.compile(r"\b(qa|quality assurance|test engineer|testing|sdet|automation tester|software tester|performance test|manual tester)\b", re.I)),
    ("Cybersecurity", re.compile(r"\b(cyber|security engineer|security analyst|application security|appsec|soc analyst|penetration|pentest|iam engineer|identity engineer|information security|infosec)\b", re.I)),
    ("Enterprise Apps", re.compile(r"\b(sap|salesforce|servicenow|workday|oracle ebs|oracle fusion|dynamics 365|power platform|mulesoft|pega)\b", re.I)),
    ("IT / Support / Network", re.compile(r"\b(it support|technical support|support engineer|systems? administrator|network engineer|network administrator|database administrator|dba|desktop support|helpdesk|help desk|noc engineer|operations engineer)\b", re.I)),
    ("Product / Technical", re.compile(r"\b(product engineer|technical product|product manager|solutions? architect|solutions? engineer|technical architect|technical consultant)\b", re.I)),
    ("Software Engineering", re.compile(r"\b(software|developer|programmer|backend|back[- ]end|frontend|front[- ]end|full[- ]?stack|mobile|android|ios|java|\.net|dotnet|c#|python|golang|go developer|node(?:\.js)?|react|angular|php|ruby|scala)\b", re.I)),
)

def india_location(value):
    return bool(INDIA.search(str(value or "")))
def relevant_role(value):
    return bool(ROLE.search(str(value or "")))

def technology_category(value):
    title=str(value or "")
    for name,pattern in TECH_CATEGORIES:
        if pattern.search(title):
            return name
    return ""

def technology_role(value):
    return bool(technology_category(value))
def recent_posting(value,days=30):
    if not value:
        return False
    try:
        raw=str(value).strip().replace("Z","+00:00")
        dt=datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        now=datetime.now(timezone.utc)
        return now-timedelta(days=days) <= dt.astimezone(timezone.utc) <= now+timedelta(hours=6)
    except Exception:
        return False

def read(url):
    with urlopen(Request(url,headers={"User-Agent":"IndiaJobAgent/1.0","Accept":"application/json"}),timeout=18) as r:
        return json.load(r)
def recruitee(board, all_tech=False):
    data=read("https://"+quote(board)+".recruitee.com/api/offers/")
    offers=data.get("offers",[]) if isinstance(data,dict) else (data if isinstance(data,list) else [])
    jobs=[]
    for j in offers:
        if not isinstance(j,dict):
            continue
        title=str(j.get("title") or "").strip()
        if not title:
            continue
        if (technology_role(title) if all_tech else relevant_role(title)) is False:
            continue
        locations=j.get("locations") or j.get("location") or []
        if isinstance(locations,(str,dict)):
            locations=[locations]
        loc_bits=[]
        for loc in locations:
            if isinstance(loc,str):
                loc_bits.append(loc)
                continue
            if not isinstance(loc,dict):
                continue
            for key in ("full_address","name","city","state_name","country","country_code"):
                value=str(loc.get(key) or "").strip()
                if value and value not in loc_bits:
                    loc_bits.append(value)
        location=" | ".join(loc_bits)
        if not india_location(location):
            continue
        published=j.get("published_at") or j.get("created_at") or j.get("updated_at") or ""
        if all_tech and not recent_posting(published,30):
            continue
        slug=str(j.get("slug") or "").strip()
        careers_url=str(j.get("careers_url") or (("https://"+board+".recruitee.com/o/"+slug) if slug else "")).strip()
        apply_url=str(j.get("careers_apply_url") or ((careers_url+"/c/new") if careers_url else "")).strip()
        if not careers_url:
            continue
        description=" ".join(str(j.get(k) or "") for k in ("description","requirements","description_text"))
        jobs.append(dict(
            company=str(j.get("company_name") or board).strip(),
            title=title,
            location=location,
            description=description,
            url=careers_url,
            apply_url=apply_url,
            published=published,
            source="recruitee",
        ))
    return jobs

def ashby(board, all_tech=False):
    data=read("https://api.ashbyhq.com/posting-api/job-board/"+quote(board))
    jobs=[]
    for j in data.get("jobs",[]):
        loc=" | ".join([str(j.get("location",""))]+[str(x.get("location","")) for x in j.get("secondaryLocations",[])])
        country=str((j.get("address") or {}).get("postalAddress",{}).get("addressCountry",""))
        if country.lower() in ("in","india"): loc+=" | India"
        if not india_location(loc) or j.get("isListed") is False: continue
        if (technology_role(j.get("title")) if all_tech else relevant_role(j.get("title"))) is False: continue
        if all_tech and not recent_posting(j.get("publishedAt",""),30): continue
        jobs.append(dict(company=board,title=j["title"],location=loc,description=j.get("descriptionPlain") or j.get("descriptionHtml",""),url=j.get("jobUrl",""),apply_url=j.get("applyUrl",""),published=j.get("publishedAt",""),source="ashby"))
    return jobs
def smart(board, all_tech=False):
    base="https://api.smartrecruiters.com/v1/companies/"+quote(board)+"/postings"
    jobs=[]; seen=set()
    if all_tech:
        queries=(None,)
    else:
        queries=("DevOps","Cloud Engineer","Site Reliability","Platform Engineer","Infrastructure Engineer","Release Engineer")
    for q in queries:
        try:
            params={"country":"in","limit":100}
            if q: params["q"]=q
            items=read(base+"?"+urlencode(params)).get("content",[])
        except Exception:
            continue
        for j in items:
            ident=str(j.get("id",""))
            title=str(j.get("name",""))
            if not ident or ident in seen:
                continue
            if (technology_role(title) if all_tech else relevant_role(title)) is False:
                continue
            if all_tech and not recent_posting(j.get("releasedDate",""),30):
                continue
            seen.add(ident)
            loc=j.get("location") or {}
            if str(loc.get("country","")).lower() not in ("in","india") and not india_location(" ".join(str(loc.get(k,"")) for k in ("city","region"))):
                continue
            try:
                detail=read(base+"/"+quote(ident))
            except Exception:
                continue
            sections=(detail.get("jobAd") or {}).get("sections") or {}
            body=" ".join(str(sections.get(k,{}).get("text","")) for k in ("jobDescription","qualifications","additionalInformation"))
            if not body.strip():
                continue
            jobs.append(dict(
                company=(j.get("company") or {}).get("name",board),
                title=title,
                location=" | ".join([str(loc.get("city","")),str(loc.get("region","")),"India"]),
                description=body,
                url="https://jobs.smartrecruiters.com/"+quote(board)+"/"+quote(ident),
                published=j.get("releasedDate",""),
                source="smartrecruiters",
            ))
    return jobs

def discover(all_tech=False):
    boards=(
        [("ashby",b) for b in ("buspatrol","gradera","openobserve-careers","sarvam","encord","opendr","outmarket","uptimeai","dehazelabs","playpowerlabs","apas","demandbase","plane","sophos","triomics","ema","redis")]
        +[("smartrecruiters",b) for b in ("BoschGroup","Experian","ServiceNow","Nagarro1","ifs1","Sia","NielsenIQ","Eurofins","Xplor")]
        +[("recruitee",b) for b in ("metyisag","gsbsolutions1","brainsquare","deephealth","kcoverseaseducation","qualifyzegmbh","sgbindia","infoprolearning")]
    )
    def run(item):
        kind,board=item
        try:
            fetcher={"ashby":ashby,"smartrecruiters":smart,"recruitee":recruitee}[kind]
            rows=fetcher(board,all_tech=all_tech)
            print("India source:",kind,board,("technology jobs:" if all_tech else "target jobs:"),len(rows))
            return rows
        except Exception as exc:
            print("India source unavailable:",kind,board,type(exc).__name__)
            return []
    with ThreadPoolExecutor(max_workers=5) as pool:
        return [j for rows in pool.map(run,boards) for j in rows]
