from pathlib import Path
import re

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Lab Data Catalog", page_icon="📊", layout="wide")

EXCEL_CANDIDATES = [
    "데이터 정리_ 서버 탐색 및 cross-check 작업.xlsx",
]

STATUS_LABELS = {1.0: "✅ Yes", 0.5: "⚠️ Partial", 0.0: "❌ No"}
STATUS_COLORS = {1.0: "green", 0.5: "orange", 0.0: "red"}
# Customize this order to control which temporal endings appear first.
TEMPORAL_LAST_LETTER_PRIORITY = [
    # "s", "n", "h", "d", "w", "m", "y",
    "초", "분", "간" ,")", "일", "주", "월","계", "년",
]


def split_tokens(raw: str) -> list[str]:
    if not raw:
        return []
    tokens = str(raw).split(",")
    cleaned = [t.strip() for t in tokens if t and t.strip()]
    return cleaned


def parse_period_value(period: str) -> tuple[str, str, str]:
    raw = str(period).strip()
    if not raw:
        return "missing", "", ""

    normalized = raw.replace("–", "~").replace("—", "~")
    if "~" in normalized:
        left, right = normalized.split("~", 1)
        return "range", left.strip(), right.strip()

    comma_parts = [p.strip() for p in normalized.split(",") if p.strip()]
    if len(comma_parts) >= 2:
        return "list", comma_parts[0], comma_parts[-1]

    return "single", normalized, normalized


def unique_tokens(series: pd.Series) -> list[str]:
    values = set()
    for items in series:
        if isinstance(items, list):
            for token in items:
                if token:
                    values.add(token)
    return sorted(values)


def sort_by_suffix(values: list[str]) -> list[str]:
    # Sort by last letter first, then by numeric value.
    def temporal_sort_key(token: str) -> tuple[str, float, str]:
        text = str(token).strip().lower()
        if not text:
            return (len(TEMPORAL_LAST_LETTER_PRIORITY), len(TEMPORAL_LAST_LETTER_PRIORITY), float("inf"), "", "")

        number_match = re.search(r"-?\d+(?:\.\d+)?", text)
        number_value = float(number_match.group(0)) if number_match else float("inf")
        letters_only = [ch for ch in text if ch.isalpha()]
        last_letter = letters_only[-1] if letters_only else ""
        second_last_letter = letters_only[-2] if len(letters_only) >= 2 else ""

        try:
            last_rank = TEMPORAL_LAST_LETTER_PRIORITY.index(last_letter)
        except ValueError:
            last_rank = len(TEMPORAL_LAST_LETTER_PRIORITY)

        try:
            second_last_rank = TEMPORAL_LAST_LETTER_PRIORITY.index(second_last_letter)
        except ValueError:
            second_last_rank = len(TEMPORAL_LAST_LETTER_PRIORITY)

        suffix_key = "".join(letters_only)[::-1] if letters_only else text[::-1]
        return (last_rank, second_last_rank, number_value, suffix_key, text)

    return sorted(values, key=temporal_sort_key)


@st.cache_data
def load_data() -> pd.DataFrame:
    base = Path(__file__).resolve().parent
    excel_path = next((base / f for f in EXCEL_CANDIDATES if (base / f).exists()), None)
    if excel_path is None:
        st.error("Excel file not found. Place it in the same folder as app.py.")
        return pd.DataFrame()
    try:
        df = pd.read_excel(excel_path)
    except ImportError:
        st.error("Missing dependency: run `pip install openpyxl`")
        return pd.DataFrame()

    if "category.1" in df.columns:
        df = df.drop(columns=["category.1"])

    df["data_availability"] = pd.to_numeric(df["data_availability"], errors="coerce").fillna(0)
    df["page_accessibility"] = pd.to_numeric(df["page_accessibility"], errors="coerce").fillna(0)

    df["person_in_charge"] = df["person_in_charge"].fillna("Unassigned")
    df["data_sensitivity"] = df["data_sensitivity"].fillna("Unknown")
    df["category"] = df["category"].fillna("Uncategorized")

    if "spatial_unit" not in df.columns:
        if "unit_spatial" in df.columns:
            df["spatial_unit"] = df["unit_spatial"]
        else:
            df["spatial_unit"] = ""
    if "temporal_unit" not in df.columns:
        if "unit_temporal" in df.columns:
            df["temporal_unit"] = df["unit_temporal"]
        else:
            df["temporal_unit"] = ""

    text_cols = ["name", "about", "region", "spatial_unit", "temporal_unit", "period", "site_link",
                 "page_accessibility_detail", "data_availability_detail", "server_route"]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna("")

    df["unit_spatial"] = df["spatial_unit"].astype(str)
    df["unit_temporal"] = df["temporal_unit"].astype(str)
    df["unit_spatial_tokens"] = df["unit_spatial"].apply(split_tokens)
    df["unit_temporal_tokens"] = df["unit_temporal"].apply(split_tokens)

    period_df = df["period"].apply(parse_period_value).apply(pd.Series)
    period_df.columns = ["period_type", "period_start", "period_end"]
    df = pd.concat([df, period_df], axis=1)
    df["period_tokens"] = df["period"].apply(
        lambda p: split_tokens(str(p).replace("~", ",").replace("–", ",").replace("—", ","))
    )

    filled_fields = ["name", "about", "region", "spatial_unit", "temporal_unit", "period", "site_link", "person_in_charge"]
    filled_count = sum(
        (df[c] != "") & (df[c] != "Unassigned") for c in filled_fields if c in df.columns
    )
    df["completeness"] = (filled_count / len(filled_fields) * 100).round(0).astype(int)
    return df


df = load_data()
if df.empty:
    st.stop()

# ── Sidebar filters ──────────────────────────────────────────────────────────
st.sidebar.header("🔍 Filters")

sel_category = st.sidebar.multiselect(
    "Category", sorted(df["category"].unique()), default=sorted(df["category"].unique())
)
sel_person = st.sidebar.multiselect(
    "Person in Charge", sorted(df["person_in_charge"].unique()), default=sorted(df["person_in_charge"].unique())
)
sel_sensitivity = st.sidebar.multiselect(
    "Data Sensitivity", sorted(df["data_sensitivity"].unique()), default=sorted(df["data_sensitivity"].unique())
)
sel_availability = st.sidebar.multiselect(
    "Data Availability", sorted(df["data_availability"].unique()), default=sorted(df["data_availability"].unique()),
    format_func=lambda v: STATUS_LABELS.get(v, str(v)),
)

fdf = df[
    df["category"].isin(sel_category)
    & df["person_in_charge"].isin(sel_person)
    & df["data_sensitivity"].isin(sel_sensitivity)
    & df["data_availability"].isin(sel_availability)
]

# ── Header ────────────────────────────────────────────────────────────────────
st.title("📊 Lab Data Catalog & Tracker")
st.caption(f"Showing **{len(fdf)}** of {len(df)} datasets")

# ── Top KPI row ──────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total", len(fdf))
k2.metric("Fully Available", int((fdf["data_availability"] == 1.0).sum()))
k3.metric("Partially Available", int((fdf["data_availability"] == 0.5).sum()))
k4.metric("Not Available", int((fdf["data_availability"] == 0.0).sum()))
k5.metric("Unassigned", int((fdf["person_in_charge"] == "Unassigned").sum()))

st.divider()

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_overview, tab_explorer, tab_catalog, tab_progress, tab_actions = st.tabs(
    ["🏠 Overview", "🧭 Unit/Region/Period", "🗂️ Catalog", "📈 Progress & Gaps", "✅ Action Items"]
)

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  TAB 1 — Overview: what kind of data do we have?                           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
with tab_overview:
    st.subheader("What kind of data do we have?")

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("##### Datasets by Category")
        cat_counts = fdf["category"].value_counts().reset_index()
        cat_counts.columns = ["Category", "Count"]
        st.bar_chart(cat_counts, x="Category", y="Count", horizontal=True)

    with col_right:
        st.markdown("##### Datasets by Region")
        region_counts = fdf[fdf["region"] != ""]["region"].value_counts().head(15).reset_index()
        region_counts.columns = ["Region", "Count"]
        st.bar_chart(region_counts, x="Region", y="Count", horizontal=True)

    st.markdown("---")
    st.markdown("##### Category × Region Coverage")
    if not fdf.empty:
        matrix = pd.pivot_table(
            fdf[fdf["region"] != ""], values="name", index="category",
            columns="region", aggfunc="count", fill_value=0,
        )
        st.dataframe(matrix, use_container_width=True)
        st.caption("Cell = number of datasets. Zeros reveal gaps in coverage.")

    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### Public vs Private")
        sens = fdf["data_sensitivity"].value_counts().reset_index()
        sens.columns = ["Sensitivity", "Count"]
        st.bar_chart(sens, x="Sensitivity", y="Count")
    with col_b:
        st.markdown("##### How data is obtained")
        methods = fdf[fdf["data_availability_detail"] != ""]["data_availability_detail"].value_counts().reset_index()
        methods.columns = ["Method", "Count"]
        st.bar_chart(methods, x="Method", y="Count")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  TAB 2 — Unit/Region/Period Explorer                                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
with tab_explorer:
    st.subheader("Unit / Region / Period Explorer")
    st.caption("Unit is split into spatial unit and temporal unit. Period is parsed by '~' (range) and ',' (list).")

    e1, e2, e3, e4 = st.columns(4)
    with e1:
        spatial_options = ["All"] + unique_tokens(fdf["unit_spatial_tokens"])
        selected_spatial = st.selectbox("Spatial Unit", spatial_options)
    with e2:
        temporal_options = ["All"] + sort_by_suffix(unique_tokens(fdf["unit_temporal_tokens"]))
        selected_temporal = st.selectbox("Temporal Unit", temporal_options)
    with e3:
        region_options = ["All"] + sorted([r for r in fdf["region"].dropna().unique().tolist() if r != ""])
        selected_region = st.selectbox("Region", region_options)
    with e4:
        period_options = ["All"] + unique_tokens(fdf["period_tokens"])
        selected_period = st.selectbox("Period Item", period_options)

    explorer_df = fdf.copy()
    if selected_spatial != "All":
        explorer_df = explorer_df[explorer_df["unit_spatial_tokens"].apply(lambda x: selected_spatial in x)]
    if selected_temporal != "All":
        explorer_df = explorer_df[explorer_df["unit_temporal_tokens"].apply(lambda x: selected_temporal in x)]
    if selected_region != "All":
        explorer_df = explorer_df[explorer_df["region"] == selected_region]
    if selected_period != "All":
        explorer_df = explorer_df[explorer_df["period_tokens"].apply(lambda x: selected_period in x)]

    spatial_exp = explorer_df.explode("unit_spatial_tokens").rename(
        columns={"unit_spatial_tokens": "spatial_token"}
    )
    spatial_exp = spatial_exp[spatial_exp["spatial_token"].notna() & (spatial_exp["spatial_token"] != "")]

    temporal_exp = explorer_df.explode("unit_temporal_tokens").rename(
        columns={"unit_temporal_tokens": "temporal_token"}
    )
    temporal_exp = temporal_exp[temporal_exp["temporal_token"].notna() & (temporal_exp["temporal_token"] != "")]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Datasets", len(explorer_df))
    m2.metric("Spatial Units", explorer_df["unit_spatial"].nunique())
    m3.metric("Temporal Units", explorer_df["unit_temporal"].nunique())
    m4.metric("Regions", explorer_df["region"].replace("", pd.NA).dropna().nunique())

    
    st.markdown("##### Dataset Details for Current Selection")
    explorer_cols = [
        "category",
        "name",
        "region",
        "spatial_unit",
        "temporal_unit",
        "unit_spatial",
        "unit_temporal",
        "period",
        "period_type",
        "period_start",
        "period_end",
        "person_in_charge",
    ]
    st.dataframe(explorer_df[explorer_cols], use_container_width=True, hide_index=True)

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Spatial Unit Distribution")
        spatial_dist = spatial_exp["spatial_token"].value_counts().reset_index()
        spatial_dist.columns = ["Spatial Unit", "Count"]
        st.bar_chart(spatial_dist, x="Spatial Unit", y="Count", horizontal=True)
    with c2:
        st.markdown("##### Temporal Unit Distribution")
        temporal_dist = temporal_exp.groupby("temporal_token", as_index=False).size()
        temporal_dist.columns = ["Temporal Unit", "Count"]
        temporal_order = sort_by_suffix(temporal_dist["Temporal Unit"].tolist())
        temporal_dist["Temporal Unit"] = pd.Categorical(
            temporal_dist["Temporal Unit"], categories=temporal_order, ordered=True
        )
        temporal_dist = temporal_dist.sort_values("Temporal Unit")
        temporal_dist["Temporal Unit"] = temporal_dist["Temporal Unit"].astype(str)
        st.bar_chart(temporal_dist, x="Temporal Unit", y="Count", horizontal=True)

    st.markdown("---")
    c3, c4 = st.columns(2)
    with c3:
        st.markdown("##### Spatial Unit × Region")
        unit_region = pd.pivot_table(
            spatial_exp[spatial_exp["region"] != ""],
            values="name",
            index="spatial_token",
            columns="region",
            aggfunc="count",
            fill_value=0,
        )
        st.dataframe(unit_region, use_container_width=True)
    with c4:
        st.markdown("##### Temporal Unit × Period Type")
        temporal_period = pd.pivot_table(
            temporal_exp,
            values="name",
            index="temporal_token",
            columns="period_type",
            aggfunc="count",
            fill_value=0,
        )
        temporal_period = temporal_period.reindex(sort_by_suffix(list(temporal_period.index)))
        st.dataframe(temporal_period, use_container_width=True)

    


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  TAB 3 — Catalog: full searchable table                                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
with tab_catalog:
    st.subheader("Full Data Catalog")

    search = st.text_input("🔎 Search by name or description", "")
    if search:
        mask = (
            fdf["name"].str.contains(search, case=False, na=False)
            | fdf["about"].str.contains(search, case=False, na=False)
        )
        display_df = fdf[mask]
    else:
        display_df = fdf

    show_df = display_df.copy()
    show_df["availability"] = show_df["data_availability"].map(STATUS_LABELS)
    show_df["accessibility"] = show_df["page_accessibility"].map(STATUS_LABELS)

    catalog_cols = [
        "category", "name", "about", "region", "spatial_unit", "temporal_unit", "period",
        "data_sensitivity", "availability", "data_availability_detail",
        "accessibility", "page_accessibility_detail",
        "site_link", "server_route", "person_in_charge",
    ]
    st.dataframe(
        show_df[catalog_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "site_link": st.column_config.LinkColumn("Site Link", display_text="Open"),
            "name": st.column_config.TextColumn("Name", width="medium"),
            "about": st.column_config.TextColumn("About", width="large"),
        },
    )
    st.caption(f"{len(display_df)} datasets shown")

    csv = display_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 Download as CSV", csv, "lab_data_catalog.csv", "text/csv")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  TAB 4 — Progress & Gaps: what's been done, what's missing?                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
with tab_progress:
    st.subheader("What's been done vs. what's missing?")

    st.markdown("##### Overall Readiness")
    total = len(fdf)
    if total > 0:
        avail_full = int((fdf["data_availability"] == 1.0).sum())
        avail_partial = int((fdf["data_availability"] == 0.5).sum())
        avail_none = int((fdf["data_availability"] == 0.0).sum())
        access_full = int((fdf["page_accessibility"] == 1.0).sum())
        access_partial = int((fdf["page_accessibility"] == 0.5).sum())
        access_none = int((fdf["page_accessibility"] == 0.0).sum())
        assigned = int((fdf["person_in_charge"] != "Unassigned").sum())
        has_link = int((fdf["site_link"] != "").sum())

        readiness = pd.DataFrame({
            "Field": [
                "Data Available", "Data Partially Available", "Data Not Available",
                "Page Accessible", "Page Partially Accessible", "Page Not Accessible",
                "Person Assigned", "Has Link",
            ],
            "Count": [
                avail_full, avail_partial, avail_none,
                access_full, access_partial, access_none,
                assigned, has_link,
            ],
            "Pct": [
                f"{v * 100 / total:.0f}%" for v in [
                    avail_full, avail_partial, avail_none,
                    access_full, access_partial, access_none,
                    assigned, has_link,
                ]
            ],
        })
        st.dataframe(readiness, use_container_width=True, hide_index=True)

    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Availability by Category")
        avail_cat = fdf.groupby("category")["data_availability"].mean().reset_index()
        avail_cat.columns = ["Category", "Avg Availability"]
        avail_cat["Avg Availability"] = (avail_cat["Avg Availability"] * 100).round(0)
        st.bar_chart(avail_cat, x="Category", y="Avg Availability")
        st.caption("100 = all fully available, 0 = none available")

    with c2:
        st.markdown("##### Ownership by Person")
        owner_counts = fdf["person_in_charge"].value_counts().reset_index()
        owner_counts.columns = ["Person", "Datasets"]
        st.dataframe(owner_counts, use_container_width=True, hide_index=True)
        st.bar_chart(owner_counts, x="Person", y="Datasets")

    st.markdown("---")
    st.markdown("##### Completeness Scores (metadata fill rate)")
    comp_df = fdf[["name", "category", "person_in_charge", "completeness"]].sort_values("completeness")
    st.dataframe(comp_df, use_container_width=True, hide_index=True)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  TAB 5 — Action Items: what needs to be done next?                         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
with tab_actions:
    st.subheader("What needs to be done?")

    def get_issues(row: pd.Series) -> list[str]:
        issues = []
        if row["person_in_charge"] == "Unassigned":
            issues.append("🔴 No owner assigned")
        if row["data_availability"] == 0.0:
            issues.append("🔴 Data not available")
        elif row["data_availability"] == 0.5:
            issues.append("🟡 Data only partially available")
        if row["page_accessibility"] == 0.0:
            issues.append("🔴 Page not accessible")
        elif row["page_accessibility"] == 0.5:
            issues.append("🟡 Page partially accessible")
        if row["site_link"] == "":
            issues.append("🟠 Missing link")
        if row["region"] == "":
            issues.append("⚪ Missing region")
        if row["period"] == "":
            issues.append("⚪ Missing period")
        if row["spatial_unit"] == "":
            issues.append("⚪ Missing spatial unit")
        if row["temporal_unit"] == "":
            issues.append("⚪ Missing temporal unit")
        return issues

    action_rows = []
    for _, row in fdf.iterrows():
        issues = get_issues(row)
        if issues:
            action_rows.append({
                "Category": row["category"],
                "Name": row["name"],
                "Region": row["region"],
                "Owner": row["person_in_charge"],
                "Availability": STATUS_LABELS.get(row["data_availability"], "?"),
                "Issues": " · ".join(issues),
                "Issue Count": len(issues),
            })

    if not action_rows:
        st.success("All datasets are complete — nothing to do!")
    else:
        action_df = pd.DataFrame(action_rows).sort_values("Issue Count", ascending=False)

        st.markdown(f"**{len(action_df)}** datasets need attention out of {len(fdf)} shown.")

        severity = st.radio(
            "Filter by severity", ["All", "🔴 Critical only", "🟡 Warnings+Critical"],
            horizontal=True,
        )
        if severity == "🔴 Critical only":
            action_df = action_df[action_df["Issues"].str.contains("🔴")]
        elif severity == "🟡 Warnings+Critical":
            action_df = action_df[action_df["Issues"].str.contains("🔴|🟡")]

        st.dataframe(
            action_df[["Category", "Name", "Region", "Owner", "Availability", "Issues"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Name": st.column_config.TextColumn("Name", width="medium"),
                "Issues": st.column_config.TextColumn("Issues", width="large"),
            },
        )

        st.markdown("---")
        st.markdown("##### Summary of all issues")
        all_issues = []
        for issues_str in action_df["Issues"]:
            all_issues.extend(issues_str.split(" · "))
        issue_summary = pd.Series(all_issues).value_counts().reset_index()
        issue_summary.columns = ["Issue", "Count"]
        st.dataframe(issue_summary, use_container_width=True, hide_index=True)
