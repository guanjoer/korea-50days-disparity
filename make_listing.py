"""
make_listing.py — 종목목록(krx_listing.csv) 갱신용.

클라우드에서는 KRX 접근이 막히므로 목록을 미리 만들어 저장소에 올려야 한다.
이 스크립트는 KRX 접근이 되는 '로컬(한국 IP)' 에서 실행한다.

    python make_listing.py        # 최신 KRX 목록을 받아 krx_listing.csv 로 저장
    git add krx_listing.csv && git commit -m "update listing" && git push

새 IPO 종목이 검색에 나오게 하려면 가끔 이 스크립트를 다시 돌려 갱신하면 된다.
"""

import FinanceDataReader as fdr

df = fdr.StockListing("KRX")
if "Code" not in df.columns and "Symbol" in df.columns:
    df = df.rename(columns={"Symbol": "Code"})

out = df[["Code", "Name", "Market"]].copy()
out["Code"] = out["Code"].astype(str).str.zfill(6)
out = out.dropna(subset=["Code", "Name"]).drop_duplicates("Code").sort_values("Name")
out.to_csv("krx_listing.csv", index=False, encoding="utf-8-sig")

print(f"krx_listing.csv 저장 완료: {len(out)} 종목")
