"""
app.py — 개별 기업 50일 이격도 트래커 (Streamlit 웹앱)

실행:
    pip install finance-datareader streamlit plotly
    streamlit run app.py

브라우저에서 기업명을 검색하면 해당 종목의
  · 현재 이격도 + 구간(과열/경계/정상/과열해소)
  · 주가 & 50일 이동평균 차트
  · 50일 이격도 추이 + 임계선
  · 최근 기록 표
가 참고 웹사이트와 동일한 방식으로 표시됩니다.
"""

import streamlit as st
import plotly.graph_objects as go

import disparity as dz

st.set_page_config(page_title="개별 기업 50일 이격도", page_icon="📊", layout="wide")

st.title("📊 개별 기업 50일 이격도 트래커")
st.caption("이격도 = 현재가 ÷ 50일 이동평균 × 100  ·  데이터: FinanceDataReader(KRX)")

# ── 캐싱: 무거운 호출은 캐시로 ───────────────────────────────
load_listing = st.cache_data(ttl=60 * 60 * 12)(dz.load_listing)
search_company = st.cache_data(ttl=60 * 60 * 12)(dz.search_company)
get_price = st.cache_data(ttl=60 * 30)(dz.get_price)

# ── 사이드바: 검색 & 옵션 ────────────────────────────────────
with st.sidebar:
    st.header("🔍 종목 검색")
    query = st.text_input("기업명 또는 종목코드", value="디아이")
    window = st.number_input("이동평균 기간(일)", min_value=5, max_value=240, value=50, step=5)
    period_label = st.selectbox("표시 기간", ["3M", "6M", "1Y", "2Y", "5Y"], index=3)
    adaptive = st.checkbox("종목별 보정 임계값 사용", value=True,
                           help="고정 130/105 대신 이 종목의 과거 이격도 분포(백분위)로 임계값을 자동 조정")

period_years = {"3M": 0.25, "6M": 0.5, "1Y": 1.0, "2Y": 2.0, "5Y": 5.0}[period_label]
period_days = {"3M": 63, "6M": 126, "1Y": 252, "2Y": 504, "5Y": 1260}[period_label]

# ── 검색 결과에서 종목 선택 ──────────────────────────────────
if not query.strip():
    st.info("왼쪽에서 기업명을 입력하세요.")
    st.stop()

candidates = search_company(query)
if candidates.empty:
    st.error(f"'{query}' 에 해당하는 종목을 찾지 못했습니다.")
    st.stop()

labels = [f"{r['Name']} ({r['Code']})" + (f" · {r.get('Market','')}" if 'Market' in r else "")
          for _, r in candidates.iterrows()]
pick = st.selectbox("종목 선택", labels, index=0)
sel = candidates.iloc[labels.index(pick)]
code, name = str(sel["Code"]), str(sel["Name"])

# ── 데이터 로드 & 계산 ───────────────────────────────────────
try:
    price = get_price(code, years=max(period_years, 5.0))   # 보정용으로 충분히 길게
    res = dz.compute_disparity(price["Close"], window=int(window)).dropna()
except Exception as e:
    st.error(f"데이터를 불러오지 못했습니다: {e}")
    st.stop()

ma_col = f"MA{int(window)}"

# 임계값 결정
if adaptive:
    th = dz.compute_adaptive_thresholds(res["Disparity"])
else:
    th = dz.DEFAULT_THRESHOLDS

res["Zone"] = res["Disparity"].apply(lambda d: dz.classify_zone(d, th))

# 표시 구간만 자르기
view = res.tail(period_days)
latest = res.iloc[-1]

# ── 상단 요약 카드 ───────────────────────────────────────────
zone_color = {"과열": "🔴", "경계": "🟠", "정상": "🟢", "과열해소": "🔵"}
c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{name} 현재가", f"{latest['Close']:,.0f}")
c2.metric(f"{int(window)}일 이동평균", f"{latest[ma_col]:,.0f}")
c3.metric("이격도", f"{latest['Disparity']:.1f}")
c4.metric("구간", f"{zone_color.get(latest['Zone'],'')} {latest['Zone']}")

st.caption(
    f"임계값({'종목 보정' if adaptive else '고정'}): "
    f"과열 ≥ {th['overheat']} · 경계 ≥ {th['caution']} · 과열해소 ≤ {th['normal']}"
)

# ── 차트 1: 주가 & 이동평균 ──────────────────────────────────
st.subheader(f"주가 & {int(window)}일 이동평균")
fig1 = go.Figure()
fig1.add_trace(go.Scatter(x=view.index, y=view["Close"], name="종가", line=dict(width=1.5)))
fig1.add_trace(go.Scatter(x=view.index, y=view[ma_col], name=f"{int(window)}일선",
                          line=dict(width=1.5, dash="dot")))
fig1.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                   legend=dict(orientation="h"), hovermode="x unified")
st.plotly_chart(fig1, use_container_width=True)

# ── 차트 2: 이격도 추이 + 임계선 ─────────────────────────────
st.subheader(f"{int(window)}일 이격도 추이")
fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=view.index, y=view["Disparity"], name="이격도",
                          line=dict(width=1.6)))
fig2.add_hline(y=th["overheat"], line=dict(color="red", dash="dash"),
               annotation_text=f"과열 {th['overheat']}")
fig2.add_hline(y=th["normal"], line=dict(color="royalblue", dash="dash"),
               annotation_text=f"과열해소 {th['normal']}")
fig2.add_hline(y=100, line=dict(color="gray", width=0.7))
fig2.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                   hovermode="x unified")
st.plotly_chart(fig2, use_container_width=True)

# ── 최근 기록 표 ─────────────────────────────────────────────
st.subheader("최근 기록")
tbl = view.tail(15).iloc[::-1].copy()
tbl.index = tbl.index.strftime("%Y-%m-%d")
tbl = tbl.rename(columns={"Close": "종가", ma_col: f"{int(window)}일선",
                          "Disparity": "이격도", "Zone": "구간"})
tbl["종가"] = tbl["종가"].map(lambda x: f"{x:,.0f}")
tbl[f"{int(window)}일선"] = tbl[f"{int(window)}일선"].map(lambda x: f"{x:,.0f}")
tbl["이격도"] = tbl["이격도"].map(lambda x: f"{x:.1f}")
st.dataframe(tbl, use_container_width=True)

st.caption("※ 정보 제공용이며 투자 권유가 아닙니다. 투자 판단의 책임은 본인에게 있습니다.")
