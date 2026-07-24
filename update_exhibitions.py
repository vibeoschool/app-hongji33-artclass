#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
즐거운 미술시간 - 전시 정보 자동 갱신 스크립트
한국문화정보원 '문화정보조회서비스'(B553457/cultureinfo) API에서
현재~향후 90일 사이의 '전시/미술' 정보를 받아 exhibitions.json 으로 저장한다.
GitHub Actions에서 매주 실행된다. 인증키는 환경변수 CULTURE_API_KEY 로 전달.
"""
import os
import sys
import json
import datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API_KEY = os.environ.get("CULTURE_API_KEY", "").strip()
BASE = "https://apis.data.go.kr/B553457/cultureinfo/period2/period2"

# 지역(시도) -> 앱에서 쓰는 지역 그룹 매핑
REGION_MAP = [
    (("서울",), "서울"),
    (("경기", "인천"), "경기·인천"),
    (("부산", "울산", "경남", "경상남"), "부산·경남"),
    (("대구", "경북", "경상북"), "대구·경북"),
    (("대전", "세종", "충남", "충북", "충청"), "대전·충청"),
    (("광주", "전남", "전북", "전라"), "광주·전라"),
    (("강원", "제주"), "강원·제주"),
]
REGION_ORDER = ["서울", "경기·인천", "부산·경남", "대구·경북", "대전·충청", "광주·전라", "강원·제주"]


def map_region(area):
    area = area or ""
    for keys, group in REGION_MAP:
        for k in keys:
            if k in area:
                return group
    return "기타"


def txt(item, *names):
    """여러 후보 태그 이름 중 값이 있는 것을 반환(응답 필드명 방어)."""
    for n in names:
        el = item.find(n)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return ""


def fmt_date(s):
    s = (s or "").strip().replace("-", "")
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}.{s[4:6]}.{s[6:8]}"
    return s


def fetch_page(from_d, to_d, page, rows=100):
    params = {
        "serviceKey": API_KEY,
        "numOfRows": str(rows),
        "PageNo": str(page),
        "from": from_d,
        "to": to_d,
        "sortStdr": "1",
    }
    url = BASE + "?" + urllib.parse.urlencode(params, safe="")
    req = urllib.request.Request(url, headers={"User-Agent": "art-class-bot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main():
    if not API_KEY:
        print("ERROR: CULTURE_API_KEY 환경변수가 없습니다.", file=sys.stderr)
        sys.exit(1)

    today = datetime.date.today()
    from_d = today.strftime("%Y%m%d")
    to_d = (today + datetime.timedelta(days=90)).strftime("%Y%m%d")

    items = []
    seen = set()
    total = None
    page = 1
    while page <= 30:  # 안전 상한 (최대 3000건)
        raw = fetch_page(from_d, to_d, page)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            print("XML 파싱 실패. 응답 일부:", raw[:300], file=sys.stderr)
            break

        # 오류 헤더 확인
        rmsg = root.find(".//resultMsg")
        rcode = root.find(".//resultCode")
        if rcode is not None and rcode.text not in (None, "", "00", "0"):
            print(f"API 응답 코드 {rcode.text} / {rmsg.text if rmsg is not None else ''}", file=sys.stderr)

        if total is None:
            tc = root.find(".//totalCount")
            total = int(tc.text) if (tc is not None and tc.text and tc.text.isdigit()) else 0
            print(f"totalCount={total}")

        page_items = root.findall(".//item")
        if not page_items:
            break

        for it in page_items:
            realm = txt(it, "realmName", "REALM_NAME", "genre", "GENRE")
            # 전시/미술 계열만
            if ("전시" not in realm) and ("미술" not in realm):
                continue
            title = txt(it, "title", "TITLE")
            if not title:
                continue
            place = txt(it, "place", "PLACE", "spatialCoverage", "SPATIAL_COVERAGE", "cntcInsttNm")
            area = txt(it, "area", "AREA", "sido", "SIDO")
            start = txt(it, "startDate", "START_DATE")
            end = txt(it, "endDate", "END_DATE")
            period = txt(it, "period", "PERIOD", "eventPeriod")
            if not period:
                period = (fmt_date(start) + " ~ " + fmt_date(end)).strip(" ~")
            url = txt(it, "url", "URL", "placeUrl")
            img = txt(it, "imageObject", "IMAGE_OBJECT", "thumbnail", "imgUrl")

            key = (title, place, start)
            if key in seen:
                continue
            seen.add(key)

            items.append({
                "title": title,
                "place": place,
                "period": period,
                "region": map_region(area or place),
                "realm": realm,
                "url": url,
                "img": img,
            })

        if total and page * 100 >= total:
            break
        page += 1

    # 지역 그룹 정렬
    present = [g for g in REGION_ORDER if any(i["region"] == g for i in items)]
    if any(i["region"] == "기타" for i in items):
        present.append("기타")

    # 지역 순 -> 제목 순 정렬
    order_index = {g: n for n, g in enumerate(present)}
    items.sort(key=lambda i: (order_index.get(i["region"], 99), i["title"]))

    out = {
        "updated": today.strftime("%Y-%m-%d"),
        "regions": present,
        "count": len(items),
        "items": items,
    }
    with open("exhibitions.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"저장 완료: exhibitions.json ({len(items)}건, 지역 {present})")


if __name__ == "__main__":
    main()
