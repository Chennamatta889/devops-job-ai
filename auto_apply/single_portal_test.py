import base64
import io
import json
import os
from pathlib import Path

from pypdf import PdfReader
from portal import portal_apply

ROOT = Path(__file__).resolve().parent

def decode_resume():
    part1=os.getenv("RESUME_PART_1","")
    part2=os.getenv("RESUME_PART_2","")
    raw=(part1+part2) if part1 and part2 else os.getenv("RESUME_BASE64","")
    try:
        pdf=base64.b64decode("".join(raw.split()),validate=True)
    except Exception:
        return b""
    if not pdf.startswith(b"%PDF-"):
        return b""
    try:
        reader=PdfReader(io.BytesIO(pdf))
        if not reader.pages:
            return b""
        for page in reader.pages:
            page.extract_text()
    except Exception:
        return b""
    return pdf

def main():
    profile=json.loads(os.getenv("PROFILE_JSON","{}"))
    pdf=decode_resume()
    job={
        "source":"ashby",
        "company":os.getenv("TARGET_COMPANY","Sophos"),
        "title":os.getenv("TARGET_TITLE","Site Reliability Engineer /Cloud"),
        "location":os.getenv("TARGET_LOCATION","India"),
        "url":os.environ["TARGET_URL"],
        "apply_url":os.environ["TARGET_URL"],
    }
    result={
        "company":job["company"],
        "title":job["title"],
        "location":job["location"],
        "url":job["url"],
        "resume_valid":bool(pdf),
        "status":"portal_review_invalid_resume" if not pdf else "not_run",
        "missing_fields":[],
        "stage":"",
        "confirmation":None,
        "final_host":"",
        "final_path":"",
    }
    if pdf:
        diagnostic={}
        status=portal_apply(job,profile,pdf,diagnostic)
        result.update({
            "status":status,
            "missing_fields":diagnostic.get("missing_fields",[]),
            "stage":diagnostic.get("stage",""),
            "confirmation":diagnostic.get("confirmation"),
            "final_host":diagnostic.get("final_host",""),
            "final_path":diagnostic.get("final_path",""),
        })
    (ROOT/"single-portal-test.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("Single portal test status:",result["status"])
    print("Resume valid:",result["resume_valid"])
    print("Missing required fields:",len(result["missing_fields"]))

if __name__=="__main__":
    main()
