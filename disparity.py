"""
disparity.py
개별 기업 50일 이격도(Disparity) 계산 코어 모듈.

이격도 = 종가 ÷ N일 이동평균 × 100   (기본 N = 50)

데이터 소스: FinanceDataReader (KRX 상장종목 + 일별 시세)
"""

from __future__ import annotations
import datetime as dt
import os
import pandas as pd
import FinanceDataReader as fdr


# ──────────────────────────────────────────────────────────────
# 1. 종목 검색 (이름 → 종목코드)
# ──────────────────────────────────────────────────────────────
_LISTING_CACHE: pd.DataFrame | None = None

# 저장소에 함께 올려둔 종목목록 CSV (Code, Name, Market).
# 클라우드(Streamlit Cloud 등)에서는 data.krx.co.kr 접근이 막히는 경우가 많아
# 실시간 fdr.StockListing("KRX") 가 실패한다. 그래서 이 파일을 우선 사용한다.
_LISTING_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "krx_listing.csv")


def load_listing() -> pd.DataFrame:
    """
    KRX(코스피+코스닥) 상장종목 목록을 반환한다. (Code, Name, Market)
    1순위: 저장소의 krx_listing.csv (네트워크 불필요 → 클라우드에서도 안전)
    2순위: 파일이 없으면 실시간 fdr.StockListing (로컬 개발용 폴백)
    """
    global _LISTING_CACHE
    if _LISTING_CACHE is not None:
        return _LISTING_CACHE

    if os.path.exists(_LISTING_CSV):
        df = pd.read_csv(_LISTING_CSV, dtype={"Code": str})
        df["Code"] = df["Code"].str.zfill(6)
    else:
        # 로컬 폴백 (KRX 접근이 되는 환경에서만 성공)
        df = fdr.StockListing("KRX")
        if "Code" not in df.columns and "Symbol" in df.columns:
            df = df.rename(columns={"Symbol": "Code"})
        df["Code"] = df["Code"].astype(str).str.zfill(6)

    _LISTING_CACHE = df
    return _LISTING_CACHE


def search_company(query: str, limit: int = 20) -> pd.DataFrame:
    """
    기업명 또는 종목코드 일부로 검색.
    반환: Code, Name, Market 을 포함한 후보 DataFrame.
    """
    listing = load_listing()
    q = query.strip()

    # 6자리 숫자면 코드로 간주
    if q.isdigit():
        mask = listing["Code"].astype(str).str.contains(q)
    else:
        mask = listing["Name"].str.contains(q, case=False, na=False)

    cols = [c for c in ["Code", "Name", "Market"] if c in listing.columns]
    return listing.loc[mask, cols].head(limit).reset_index(drop=True)


def resolve_code(query: str) -> tuple[str, str]:
    """검색 결과 중 첫 번째 종목의 (code, name) 을 돌려준다. (CLI용 편의 함수)"""
    res = search_company(query)
    if res.empty:
        raise ValueError(f"'{query}' 에 해당하는 종목을 찾지 못했습니다.")
    row = res.iloc[0]
    return str(row["Code"]), str(row["Name"])


# ──────────────────────────────────────────────────────────────
# 2. 시세 조회
# ──────────────────────────────────────────────────────────────
def get_price(code: str, years: float = 2.0) -> pd.DataFrame:
    """
    종목코드의 일별 OHLCV 를 조회.
    이동평균 워밍업(앞쪽 50거래일)을 확보하기 위해 요청기간보다 약 90일 더 가져온다.
    """
    end = dt.date.today()
    start = end - dt.timedelta(days=int(years * 365) + 100)
    df = fdr.DataReader(code, start.isoformat(), end.isoformat())
    if df.empty:
        raise ValueError(f"코드 {code} 의 시세 데이터가 비어 있습니다.")
    return df


# ──────────────────────────────────────────────────────────────
# 3. 이격도 계산
# ──────────────────────────────────────────────────────────────
# 코스피 지수 기준 디폴트 임계값(이그전 이론). 개별 종목은 보통 더 변동성이 커서
# 아래 compute_adaptive_thresholds() 로 종목별 보정값을 쓰는 것을 권장.
DEFAULT_THRESHOLDS = {"overheat": 130.0, "caution": 120.0, "normal": 105.0}


def compute_disparity(close: pd.Series, window: int = 50) -> pd.DataFrame:
    """종가 시리즈로부터 N일 이동평균과 이격도를 계산."""
    ma = close.rolling(window=window, min_periods=window).mean()
    disparity = close / ma * 100
    out = pd.DataFrame(
        {"Close": close, f"MA{window}": ma, "Disparity": disparity}
    )
    return out


def classify_zone(value: float, th: dict = DEFAULT_THRESHOLDS) -> str | None:
    """이격도 값을 4개 구간으로 분류."""
    if value is None or pd.isna(value):
        return None
    if value >= th["overheat"]:
        return "과열"
    if value >= th["caution"]:
        return "경계"
    if value >= th["normal"]:
        return "정상"
    return "과열해소"


def compute_adaptive_thresholds(disparity: pd.Series) -> dict:
    """
    종목 고유의 과거 이격도 분포(백분위수)로 임계값을 보정.
      - 과열  = 95th 백분위
      - 경계  = 85th
      - 과열해소 = 15th
    개별 종목은 지수보다 변동성이 커서 고정 130/105 가 잘 맞지 않을 때 유용.
    """
    v = disparity.dropna()
    if v.empty:
        return DEFAULT_THRESHOLDS
    return {
        "overheat": round(float(v.quantile(0.95)), 1),
        "caution": round(float(v.quantile(0.85)), 1),
        "normal": round(float(v.quantile(0.15)), 1),
    }


def build(code: str, years: float = 2.0, window: int = 50) -> pd.DataFrame:
    """코드 → 이격도 테이블(Close, MAn, Disparity, Zone) 한 번에 생성."""
    price = get_price(code, years=years)
    res = compute_disparity(price["Close"], window=window)
    res["Zone"] = res["Disparity"].apply(lambda d: classify_zone(d))
    return res


# ──────────────────────────────────────────────────────────────
# 4. CLI 실행 예시:  python disparity.py 디아이
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    query = sys.argv[1] if len(sys.argv) > 1 else "삼성전자"
    code, name = resolve_code(query)
    print(f"▶ {name} ({code})")

    table = build(code, years=2.0).dropna()
    latest = table.iloc[-1]
    print(f"  최신 종가     : {latest['Close']:,.0f}")
    print(f"  50일 이동평균 : {latest['MA50']:,.0f}")
    print(f"  이격도        : {latest['Disparity']:.1f}  →  [{latest['Zone']}]")

    th = compute_adaptive_thresholds(table["Disparity"])
    print(f"  (종목 보정 임계값) 과열≥{th['overheat']} / 경계≥{th['caution']} / 해소≤{th['normal']}")
    print("\n  최근 7거래일")
    print(table.tail(7)[["Close", "MA50", "Disparity", "Zone"]].round(2).to_string())
