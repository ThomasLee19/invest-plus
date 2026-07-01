"""
SEC EDGAR filings fetcher.

Pulls a small seed set of recent 10-K / 10-Q / 8-K filings (HTML, as filed)
per ticker from SEC EDGAR's submissions API, for the finance RAG corpus.

Run:
    python scripts/fetch_filings.py

Output:
    data/filings/<ticker>/<form>_<filingDate>_<accession>.htm
"""

import time
from pathlib import Path

import requests

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "filings"

# AAPL is the demo-query ticker used throughout the migration plan — kept first/prioritized.
TICKERS = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
}

# SEC requires a descriptive User-Agent identifying the app and a contact
# (format: "AppName email@example.com") or it will block/429 requests.
HEADERS = {"User-Agent": "InvestPlusResearch research@investplus.dev"}

# Most recent filing per form type, fetched per ticker.
WANTED_FORMS = ["10-K", "10-Q", "8-K"]
REQUEST_DELAY = 0.3


def fetch_submissions(cik: str) -> dict | None:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"  [submissions failed] {url} -> {e}")
        return None


def pick_recent_filings(submissions: dict) -> list[dict]:
    """Pick the most recent filing per wanted form type."""
    recent = submissions["filings"]["recent"]
    picked = {}
    for i, form in enumerate(recent["form"]):
        if form not in WANTED_FORMS or form in picked:
            continue
        picked[form] = {
            "form": form,
            "filingDate": recent["filingDate"][i],
            "accessionNumber": recent["accessionNumber"][i],
            "primaryDocument": recent["primaryDocument"][i],
        }
        if len(picked) == len(WANTED_FORMS):
            break
    return list(picked.values())


def fetch_filing_doc(cik: str, filing: dict, dest_dir: Path) -> bool:
    accn_nodash = filing["accessionNumber"].replace("-", "")
    cik_nolead = str(int(cik))
    doc_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_nolead}/"
        f"{accn_nodash}/{filing['primaryDocument']}"
    )
    ext = Path(filing["primaryDocument"]).suffix or ".htm"
    filename = f"{filing['form'].replace('/', '-')}_{filing['filingDate']}_{filing['accessionNumber']}{ext}"
    dest_path = dest_dir / filename

    if dest_path.exists():
        print(f"  [skip] {filename} already exists")
        return True

    try:
        resp = requests.get(doc_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [failed] {doc_url} -> {e}")
        return False

    dest_path.write_bytes(resp.content)
    print(f"  [ok] {filename} ({len(resp.content)} bytes)")
    return True


def main():
    print("=" * 60)
    print("SEC EDGAR filings fetcher")
    print(f"Tickers: {', '.join(TICKERS)}")
    print(f"Forms: {', '.join(WANTED_FORMS)}")
    print(f"Output dir: {OUTPUT_DIR}")
    print("=" * 60)

    total_ok, total_fail = 0, 0

    for ticker, cik in TICKERS.items():
        print(f"\n[{ticker}] CIK {cik}")
        submissions = fetch_submissions(cik)
        time.sleep(REQUEST_DELAY)
        if not submissions:
            total_fail += 1
            continue

        filings = pick_recent_filings(submissions)
        dest_dir = OUTPUT_DIR / ticker
        dest_dir.mkdir(parents=True, exist_ok=True)

        for filing in filings:
            ok = fetch_filing_doc(cik, filing, dest_dir)
            total_ok += 1 if ok else 0
            total_fail += 0 if ok else 1
            time.sleep(REQUEST_DELAY)

    print("\n" + "=" * 60)
    print(f"Done. Fetched {total_ok}, failed {total_fail}")
    print(f"Files saved under: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
