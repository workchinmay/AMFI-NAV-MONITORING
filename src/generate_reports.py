import glob
import os
import pandas as pd

PARSED_DIR = "data/parsed"
METADATA_LOG = "data/snapshot_metadata.csv"
OUT_EXCEL = "reports/amfi_response_summary.xlsx"


def main():
    os.makedirs("reports", exist_ok=True)
    files = sorted(glob.glob(f"{PARSED_DIR}/*.csv"))
    if not files:
        print("No parsed snapshot CSVs found yet.")
        return

    df_all = pd.concat([pd.read_csv(f, dtype={"scheme_code": str}) for f in files], ignore_index=True)
    df_all["is_requested_date_match"] = df_all["is_requested_date_match"].astype(str) == "True"

    # 1. Timestamp-wise Response & Fund Count Summary
    summary_by_time = (
        df_all.groupby(["capture_time_ist", "requested_nav_date"])
        .agg(
            total_funds_in_response=("scheme_code", "count"),
            funds_with_requested_date=("is_requested_date_match", "sum"),
            funds_with_older_date=("is_requested_date_match", lambda s: (~s).sum()),
        )
        .reset_index()
    )
    summary_by_time["updated_percentage"] = (
        (summary_by_time["funds_with_requested_date"] / summary_by_time["total_funds_in_response"]) * 100
    ).round(2)

    if os.path.exists(METADATA_LOG):
        meta = pd.read_csv(METADATA_LOG)
        summary_by_time = summary_by_time.merge(
            meta[["capture_time_ist", "tag", "http_status", "response_size_bytes", "sha256"]],
            on="capture_time_ist",
            how="left",
        )

    # 2. Breakdown by Returned NAV Date per Timestamp
    date_distribution = (
        df_all.groupby(["capture_time_ist", "requested_nav_date", "returned_nav_date"])
        .agg(fund_count=("scheme_code", "count"))
        .reset_index()
        .sort_values(["capture_time_ist", "fund_count"], ascending=[True, False])
    )

    # 3. AMC-wise Fund Count Summary (Latest Snapshot)
    latest_ts = df_all["capture_time_ist"].max()
    df_latest = df_all[df_all["capture_time_ist"] == latest_ts]
    amc_summary = (
        df_latest.groupby("amc")
        .agg(
            total_funds=("scheme_code", "count"),
            updated_funds=("is_requested_date_match", "sum"),
            delayed_funds=("is_requested_date_match", lambda s: (~s).sum()),
        )
        .reset_index()
        .sort_values(by="delayed_funds", ascending=False)
    )

    # 4. First-Appearance Timestamp
    updated_only = df_all[df_all["is_requested_date_match"]]
    first_appearance = (
        updated_only.groupby(["requested_nav_date", "scheme_code", "amc", "scheme_name"])
        .agg(first_seen_timestamp_ist=("capture_time_ist", "min"), nav=("nav", "first"))
        .reset_index()
    )

    with pd.ExcelWriter(OUT_EXCEL, engine="openpyxl") as writer:
        summary_by_time.to_excel(writer, sheet_name="1_Timestamp_Summary", index=False)
        date_distribution.to_excel(writer, sheet_name="2_NAV_Date_Breakdown", index=False)
        amc_summary.to_excel(writer, sheet_name="3_AMC_Summary", index=False)
        first_appearance.to_excel(writer, sheet_name="4_First_Appearance_Time", index=False)

    print(f"Generated summary report at: {OUT_EXCEL}")


if __name__ == "__main__":
    main()
