from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st


st.set_page_config(page_title="台股 Coverage Explorer", layout="wide")

DEFAULT_ROOT_CANDIDATES = [
    Path("."),
    Path("./My-TW-Coverage-master"),
    Path("./My-TW-Coverage"),
]


@dataclass
class Report:
    path: Path
    sector: str
    ticker: str
    company: str
    title: str
    raw_text: str
    plain_text: str
    sections: Dict[str, str]
    wikilinks: List[str]


WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
TITLE_RE = re.compile(r"^#\s*(.*?)$", re.MULTILINE)
META_RE = re.compile(r"\*\*(板塊|產業|市值|企業價值):\*\*\s*(.+)")


def clean_markdown(text: str) -> str:
    text = WIKILINK_RE.sub(r"\1", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def normalize_header(header: str) -> str | None:
    header = header.strip()
    header = header.replace("\u3000", " ")
    header = header.replace("\ufeff", "")
    header = header.strip()

    header_clean = header.replace(" ", "")

    if "業務簡介" in header_clean:
        return "業務簡介"
    if "供應鏈位置" in header_clean:
        return "供應鏈位置"
    if "主要客戶及供應商" in header_clean:
        return "主要客戶及供應商"
    if "財務概況" in header_clean:
        return "財務概況"

    return None


def extract_sections(text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    current_key = None
    buffer: List[str] = []

    lines = text.splitlines()

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("## "):
            # 👉 存前一段
            if current_key is not None:
                sections[current_key] = "\n".join(buffer).strip()

            raw_header = stripped[3:].strip()
            key = normalize_header(raw_header)

            # 🔥 關鍵：如果不是我們要的 section → 忽略
            if key is None:
                current_key = None
                buffer = []
                continue

            current_key = key
            buffer = []

        else:
            if current_key is not None:
                buffer.append(line)

    # 👉 收尾
    if current_key is not None:
        sections[current_key] = "\n".join(buffer).strip()

    return sections

def parse_title(text: str, fallback: str) -> str:
    m = TITLE_RE.search(text)
    if m:
        return clean_markdown(m.group(1))
    return fallback


def parse_report(md_path: Path, sector: str) -> Report:
    raw = md_path.read_text(encoding="utf-8")
    stem = md_path.stem

    if "_" in stem:
        ticker, company = stem.split("_", 1)
    else:
        ticker, company = "", stem

    return Report(
        path=md_path,
        sector=sector,
        ticker=ticker,
        company=company,
        title=parse_title(raw, company),
        raw_text=raw,
        plain_text=clean_markdown(raw),
        sections=extract_sections(raw),
        wikilinks=sorted(set(WIKILINK_RE.findall(raw))),
    )


def load_reports(root_dir_str: str):
    root_dir = Path(root_dir_str)
    reports_dir = root_dir / "Pilot_Reports"
    if not reports_dir.exists():
        raise FileNotFoundError(f"找不到資料夾：{reports_dir}")

    reports: List[Report] = []
    for sector_dir in sorted([p for p in reports_dir.iterdir() if p.is_dir()]):
        for md in sorted(sector_dir.glob("*.md")):
            try:
                reports.append(parse_report(md, sector_dir.name))
            except Exception:
                continue

    rows = []
    for r in reports:
        meta = {k: v for k, v in META_RE.findall(r.raw_text)}
        rows.append(
            {
                "sector": r.sector,
                "ticker": r.ticker,
                "company": r.company,
                "title": r.title,
                "path": str(r.path),
                "wikilink_count": len(r.wikilinks),
                "board": meta.get("板塊", ""),
                "industry": meta.get("產業", ""),
                "market_cap": meta.get("市值", ""),
                "enterprise_value": meta.get("企業價值", ""),
                "search_blob": f"{r.company} {r.ticker} {r.sector} {r.plain_text}".lower(),
            }
        )

    df = pd.DataFrame(rows)
    return reports, df



def load_network(root_dir_str: str):
    graph_path = Path(root_dir_str) / "network" / "graph_data.json"
    if not graph_path.exists():
        return {}

    data = json.loads(graph_path.read_text(encoding="utf-8"))
    neighbors: Dict[str, List[dict]] = {}

    for link in data.get("links", []):
        s = link.get("source")
        t = link.get("target")
        w = link.get("weight", 0)

        neighbors.setdefault(s, []).append({"name": t, "weight": w})
        neighbors.setdefault(t, []).append({"name": s, "weight": w})

    for key, vals in neighbors.items():
        vals.sort(key=lambda x: x["weight"], reverse=True)

    return {"neighbors": neighbors, "nodes": data.get("nodes", [])}



def load_themes(root_dir_str: str):
    themes_dir = Path(root_dir_str) / "themes"
    out = {}
    if not themes_dir.exists():
        return out

    for md in sorted(themes_dir.glob("*.md")):
        out[md.stem] = md.read_text(encoding="utf-8")

    return out


def guess_root() -> str:
    for candidate in DEFAULT_ROOT_CANDIDATES:
        if (candidate / "Pilot_Reports").exists():
            return str(candidate.resolve())
    return str(Path(".").resolve())


def metric_card(label: str, value: str):
    st.markdown(
        f"""
        <div style="padding:14px 16px;border:1px solid #e5e7eb;border-radius:14px;background:#fafafa;">
            <div style="font-size:0.9rem;color:#6b7280;">{label}</div>
            <div style="font-size:1.1rem;font-weight:700;word-break:break-word;">{value or "-"}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def login_gate():
    st.title("🔐 Login")
    password = st.text_input("Password", type="password")

    if password != "114514":
        st.warning("請輸入正確密碼")
        st.stop()

    st.success("登入成功")


def show_report(report: Report, row: pd.Series, network_data: dict):
    st.subheader(f"{report.ticker} {report.company}")
    st.caption(f"{report.sector} ｜ {report.path}")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("板塊", row.get("board", ""))
    with c2:
        metric_card("產業", row.get("industry", ""))
    with c3:
        metric_card("市值", row.get("market_cap", ""))
    with c4:
        metric_card("企業價值", row.get("enterprise_value", ""))

    tabs = st.tabs(["總覽", "業務簡介", "供應鏈", "客戶/供應商", "財務", "Wikilinks / 關聯"])

    with tabs[0]:
        st.markdown(clean_markdown(report.raw_text))

    with tabs[1]:
        st.markdown(clean_markdown(report.sections.get("業務簡介", "尚無資料")))

    with tabs[2]:
        st.markdown(clean_markdown(report.sections.get("供應鏈位置", "尚無資料")))

    with tabs[3]:
        st.markdown(clean_markdown(report.sections.get("主要客戶及供應商", "尚無資料")))

    with tabs[4]:
        fin = report.sections.get("財務概況", "")
        if fin:
            st.markdown(fin)
        else:
            st.error("沒有抓到財務區塊")
            st.write("目前抓到的 sections：", list(report.sections.keys()))
            st.write("所有二級標題：")
            all_h2 = [line.strip() for line in report.raw_text.splitlines() if line.strip().startswith("## ")]
            st.write(all_h2)

    with tabs[5]:
        st.write(f"Wikilinks 數量：{len(report.wikilinks)}")
        if report.wikilinks:
            st.caption("點下面可複製名字再去搜尋")
            st.write("、 ".join(report.wikilinks[:120]))

        related = network_data.get("neighbors", {}).get(report.company, [])
        if related:
            st.markdown("### 圖譜關聯（依共現強度排序）")
            rel_df = pd.DataFrame(related[:30])
            rel_df.columns = ["關聯節點", "權重"]
            st.dataframe(rel_df, use_container_width=True, hide_index=True)
        else:
            st.info("這家公司沒有在 graph_data.json 中找到對應節點，或目前未建立 network 資料。")


def show_search_results(filtered: pd.DataFrame, reports_map: Dict[str, Report], network_data: dict):
    if filtered.empty:
        st.warning("沒有找到符合條件的公司。")
        return

    st.write(f"找到 {len(filtered)} 筆")
    st.dataframe(
        filtered[["ticker", "company", "sector", "industry", "wikilink_count"]],
        use_container_width=True,
        hide_index=True,
    )

    options = [f"{r.ticker} {r.company}｜{r.sector}" for _, r in filtered.iterrows()]
    selected = st.selectbox("選一家公司查看完整內容", options, index=0)
    ticker = selected.split(" ", 1)[0]
    row = filtered[filtered["ticker"] == ticker].iloc[0]
    show_report(reports_map[row["path"]], row, network_data)


def main():
    login_gate()

    st.title("台股 Coverage Explorer")
    st.caption("用比較像 app 的方式瀏覽 My-TW-Coverage 資料庫")

    with st.sidebar:
        st.header("設定")
        root_dir = st.text_input("專案根目錄", value=guess_root())
        st.caption("這個路徑底下要看得到 Pilot_Reports、network、themes")

    try:
        reports, df = load_reports(root_dir)
    except Exception as e:
        st.error(f"讀取失敗：{e}")
        st.stop()

    network_data = load_network(root_dir)
    themes = load_themes(root_dir)
    reports_map = {str(r.path): r for r in reports}

    mode = st.sidebar.radio("功能", ["公司瀏覽", "關鍵字搜尋", "主題瀏覽", "資料概覽"])

    if mode == "公司瀏覽":
        sectors = ["全部"] + sorted(df["sector"].dropna().unique().tolist())
        sector = st.sidebar.selectbox("產業分類", sectors)
        sub_df = df if sector == "全部" else df[df["sector"] == sector]
        company_options = sub_df.sort_values(["sector", "ticker"])
        labels = [f"{r.ticker} {r.company}｜{r.sector}" for _, r in company_options.iterrows()]
        selected = st.sidebar.selectbox("公司", labels)
        ticker = selected.split(" ", 1)[0]
        row = company_options[company_options["ticker"] == ticker].iloc[0]
        show_report(reports_map[row["path"]], row, network_data)

    elif mode == "關鍵字搜尋":
        st.subheader("搜尋公司 / 技術 / 客戶 / 供應鏈關鍵字")
        keyword = st.text_input("輸入關鍵字", placeholder="例如：CoWoS、台積電、液冷散熱、Apple")
        sector_filter = st.multiselect("限制產業（可不選）", sorted(df["sector"].unique().tolist()))
        min_links = st.slider("最少 wikilink 數量", 0, int(df["wikilink_count"].max()), 0)

        filtered = df.copy()
        if sector_filter:
            filtered = filtered[filtered["sector"].isin(sector_filter)]
        filtered = filtered[filtered["wikilink_count"] >= min_links]
        if keyword.strip():
            kw = keyword.strip().lower()
            filtered = filtered[filtered["search_blob"].str.contains(re.escape(kw), regex=True, na=False)]
        filtered = filtered.sort_values(["wikilink_count", "ticker"], ascending=[False, True])
        show_search_results(filtered, reports_map, network_data)

    elif mode == "主題瀏覽":
        st.subheader("themes 資料夾內容")
        if not themes:
            st.info("找不到 themes 內容。你可以先跑：python scripts/build_themes.py")
        else:
            theme_name = st.selectbox("主題", sorted(themes.keys()))
            st.markdown(themes[theme_name])

    elif mode == "資料概覽":
        total_companies = len(df)
        total_sectors = df["sector"].nunique()
        total_links = int(df["wikilink_count"].sum())

        c1, c2, c3 = st.columns(3)
        with c1:
            metric_card("公司數", f"{total_companies:,}")
        with c2:
            metric_card("產業數", f"{total_sectors:,}")
        with c3:
            metric_card("總 Wikilinks", f"{total_links:,}")

        st.markdown("### 各產業公司數")
        sector_counts = df.groupby("sector").size().sort_values(ascending=False).reset_index(name="companies")
        st.bar_chart(sector_counts.set_index("sector"))

        st.markdown("### Wikilink 最多的公司")
        top = df.sort_values("wikilink_count", ascending=False).head(30)
        st.dataframe(
            top[["ticker", "company", "sector", "wikilink_count"]],
            use_container_width=True,
            hide_index=True,
        )

        if network_data.get("nodes"):
            st.markdown("### network 節點類型")
            node_df = pd.DataFrame(network_data["nodes"])
            if not node_df.empty and "category" in node_df.columns:
                cat = node_df.groupby("category").size().reset_index(name="count")
                st.dataframe(cat, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.caption("資料來源：My-TW-Coverage (MIT License)")


if __name__ == "__main__":
    main()