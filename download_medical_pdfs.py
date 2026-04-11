"""
download_medical_pdfs.py
========================
Downloads free, publicly available medical PDFs from trusted sources
and saves them to the data/ folder for Pinecone ingestion.

Run: conda run -n medibot python download_medical_pdfs.py

After running, execute: python store_index.py  (to rebuild the Pinecone index)
"""

import os
import urllib.request
import time

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(SCRIPT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ── Free Medical PDFs ─────────────────────────────────────────────────────────
# All sources are public-domain or openly licensed. These URLs are stable.
PDFS = [
    {
        "name": "WHO_Essential_Medicines_2023.pdf",
        "url":  "https://www.who.int/docs/default-source/essential-medicines/2023-eml-emlc-expert-committee-report/annex-1-eml-2023-eng.pdf",
        "desc": "WHO Model Essential Medicines List 2023"
    },
    {
        "name": "CDC_Diabetes_FactSheet.pdf",
        "url":  "https://www.cdc.gov/diabetes/pdfs/data/statistics/national-diabetes-statistics-report.pdf",
        "desc": "CDC National Diabetes Statistics Report"
    },
    {
        "name": "NHLBI_High_Blood_Pressure.pdf",
        "url":  "https://www.nhlbi.nih.gov/files/docs/public/heart/hbp_low.pdf",
        "desc": "NHLBI — Understanding and Controlling High Blood Pressure"
    },
    {
        "name": "NHLBI_Heart_Health.pdf",
        "url":  "https://www.nhlbi.nih.gov/files/docs/public/heart/hbp_amer.pdf",
        "desc": "NHLBI — Heart Health Guide"
    },
    {
        "name": "NIMH_Depression_Guide.pdf",
        "url":  "https://www.nimh.nih.gov/sites/default/files/documents/health/publications/depression/depression.pdf",
        "desc": "NIMH — Depression: What You Need to Know"
    },
    {
        "name": "NIMH_Anxiety_Guide.pdf",
        "url":  "https://www.nimh.nih.gov/sites/default/files/documents/health/publications/anxiety-disorders/anxiety-disorders.pdf",
        "desc": "NIMH — Anxiety Disorders booklet"
    },
    {
        "name": "CDC_Asthma_Guide.pdf",
        "url":  "https://www.cdc.gov/asthma/pdfs/AsthmaActionPlan508.pdf",
        "desc": "CDC Asthma Action Plan"
    },
    {
        "name": "WHO_FirstAid_Guide.pdf",
        "url":  "https://www.who.int/docs/default-source/integrated-health-services/first-aid/first-aid-manual.pdf",
        "desc": "WHO First Aid Manual"
    },
]

# ── Headers to avoid 403 blocks ───────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def download_pdf(name: str, url: str, desc: str) -> bool:
    dest = os.path.join(DATA_DIR, name)

    if os.path.exists(dest):
        size_kb = os.path.getsize(dest) // 1024
        print(f"  [SKIP]  {name} already exists ({size_kb} KB)")
        return True

    print(f"  [DOWN]  {desc}")
    print(f"          → {url}")
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()

        if len(data) < 1000:
            print(f"  [WARN]  Response too small ({len(data)} bytes) — likely an error page. Skipping.")
            return False

        with open(dest, "wb") as f:
            f.write(data)

        size_kb = len(data) // 1024
        print(f"  [OK]    Saved {name} ({size_kb} KB)")
        return True

    except Exception as e:
        print(f"  [FAIL]  Could not download {name}: {e}")
        return False


def main():
    print("\n" + "=" * 65)
    print("  MediBot — Free Medical PDF Downloader")
    print("=" * 65)
    print(f"  Saving PDFs to: {DATA_DIR}\n")

    success, failed = 0, 0
    for entry in PDFS:
        ok = download_pdf(entry["name"], entry["url"], entry["desc"])
        if ok:
            success += 1
        else:
            failed += 1
        time.sleep(1)   # Be polite — don't hammer servers

    print("\n" + "=" * 65)
    print(f"  Downloaded:  {success}/{len(PDFS)} PDFs")
    if failed:
        print(f"  Failed:      {failed} PDFs (check URLs or internet connection)")
    print("\n  NEXT STEP: Run  python store_index.py  to rebuild the Pinecone index")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
