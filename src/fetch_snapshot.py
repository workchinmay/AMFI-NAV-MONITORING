import argparse
import csv
import hashlib
import os
import time
from datetime import datetime, timedelta
import pytz
import requests

IST = pytz.timezone("Asia/Kolkata")
AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

RAW_DIR = "data/raw"
PARSED_DIR = "data/parsed"
METADATA_LOG = "data/snapshot_metadata.csv"


def get_target_nav_date(now_ist: datetime, override_date: str | None = None) -> str:
    if override_date:
        return override_date
    # 6:45 AM to 1:00 PM IST -> previous calendar day
    if now_ist.hour < 14:
        target = now_ist - timedelta(days=1)
    else:
        # 11:00 PM IST -> same calendar day
        target = now_ist
    return target.strftime("%d-%b-%Y")


def fetch_with_retries(url: str, retries: int = 3) -> requests.Response:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/plain,text/html,*/*",
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=45)
            resp.raise_for_status()
            return resp
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Unreachable")


def parse_amfi_text(raw_text: str, capture_ts_ist: str, requested_date: str) -> list[dict]:
    rows = []
    current_category = "Unknown"
    current_amc = "Unknown"

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue

        if ";" not in line:
            if "(" in line and line.endswith(")"):
                current_category = line
            else:
                current_amc = line
            continue

        parts = [p.strip() for p in line.split(";")]
        if parts[0].lower() == "scheme code":
            continue

        if len(parts) >= 8:
            scheme_code, isin_growth, isin_reinv, scheme_name, plan, option, nav_val, nav_date = parts[:8]
        elif len(parts) >= 6:
            scheme_code, isin_growth, isin_reinv, scheme_name, nav_val, nav_date = parts[:6]
            plan, option = "", ""
        else:
            continue

        rows.append({
            "capture_time_ist": capture_ts_ist,
            "requested_nav_date": requested_date,
            "scheme_code": scheme_code,
            "isin_growth": isin_growth,
            "isin_reinv": isin_reinv,
            "amc": current_amc,
            "category": current_category,
            "scheme_name": scheme_name,
            "plan": plan,
            "option": option,
            "nav": nav_val,
            "returned_nav_date": nav_date,
            "is_requested_date_match": str(nav_date.lower() == requested_date.lower()),
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description="Fetch and log AMFI NAV snapshot.")
    parser.add_argument("--override-date", type=str, default=None)
    parser.add_argument("--tag", type=str, default="scheduled")
    args = parser.parse_args()

    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(PARSED_DIR, exist_ok=True)

    now_ist = datetime.now(IST)
    capture_ts_str = now_ist.strftime("%Y-%m-%d %H:%M:%S %Z")
    file_stamp = now_ist.strftime("%Y-%m-%d_%H%M")
    requested_nav_date = get_target_nav_date(now_ist, args.override_date)

    resp = fetch_with_retries(AMFI_URL)
    raw_bytes = resp.content
    raw_text = resp.text

    sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
    response_size = len(raw_bytes)
    http_status = resp.status_code

    # Save exact raw AMFI response as plain .txt
    raw_filename = f"{RAW_DIR}/{file_stamp}_{args.tag}.txt"
    with open(raw_filename, "wb") as f:
        f.write(raw_bytes)

    parsed_rows = parse_amfi_text(raw_text, capture_ts_str, requested_nav_date)
    parsed_filename = f"{PARSED_DIR}/{file_stamp}_{args.tag}.csv"

    if parsed_rows:
        with open(parsed_filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(parsed_rows[0].keys()))
            writer.writeheader()
            writer.writerows(parsed_rows)

    matching_date_count = sum(1 for r in parsed_rows if r["is_requested_date_match"] == "True")

    meta_exists = os.path.exists(METADATA_LOG)
    with open(METADATA_LOG, "a", newline="", encoding="utf-8") as f:
        fieldnames = [
            "capture_time_ist",
            "tag",
            "requested_nav_date",
            "http_status",
            "response_size_bytes",
            "sha256",
            "total_schemes_received",
            "schemes_matching_requested_date",
            "raw_file",
            "parsed_file",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not meta_exists:
            writer.writeheader()
        writer.writerow({
            "capture_time_ist": capture_ts_str,
            "tag": args.tag,
            "requested_nav_date": requested_nav_date,
            "http_status": http_status,
            "response_size_bytes": response_size,
            "sha256": sha256_hash,
            "total_schemes_received": len(parsed_rows),
            "schemes_matching_requested_date": matching_date_count,
            "raw_file": raw_filename,
            "parsed_file": parsed_filename,
        })

    print(f"[{capture_ts_str}] Captured {len(parsed_rows)} schemes.")
    print(f"Saved plain raw text to: {raw_filename}")


if __name__ == "__main__":
    main()
