#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
즐거운 미술시간 - 전시 정보 자동 갱신 스크립트
한국문화정보원 '문화정보조회서비스'(B553457/cultureinfo) API에서
현재~향후 90일 사이의 '전시/미술' 정보를 받아 exhibitions.json 으로 저장한다.
정확한 엔드포인트를 모를 수 있어 여러 후보 주소를 자동으로 시도한다.
인증키는 환경변수 CULTURE_API_KEY 로 전달(GitHub Secret).
"""
import os
import sys
import json
import datetime
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

API_KEY = os.environ.get("CULTURE_API_KEY", "").strip()

# 시도할 엔드포인트 후보(맞는 것이 나오면 사용). 기간(period)형을 우선.
ENDPOINT_CANDIDATES = [
    "https://apis.data.go.kr/B553457/cultureinfo/period2/period2",
    "https://apis.data.go.kr/B553457/cultureinfo/period2",
    "http://apis.data.go.kr/B553457/cultureinfo/period2/period2",
    "http://apis.data.go.kr/B553457/cultureinfo/period2",
    "https://apis.data.go.kr/B553457/cultureinfo/area2/area2",
    "https://apis.data.go.kr/B553457/cultureinfo/area2",
    "https://apis.data.go.kr/B553457/cultureinfo/realm2/realm2",
    "https://apis.data.go.kr/B553457/cultureinfo/realm2",
]

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
    for n in names:
        el = item.find(n)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return ""


def fmt_date(s):
    s = (s or "").strip().replace("-", "").replace(".", "")
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}.{s[4:6]}.{s[6:8]}"
    return (s or "").strip()


def call(base, from_d, to_d, page, rows=100):
    params = {
        "serviceKey": API_KEY,
        "numOfRows": str(rows),
        "PageNo": str(page),
        "pageNo": str(page),
        "from": from_d,
        "to": to_d,
        "sortStdr": "1",
    }
    url = base + "?" + urllib.parse.urlencode(params, safe="")
    req = urllib.request.Request(url, headers={"User-Agent": "art-class-bot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def find_endpoint(from_d, to_d):
    """후보 주소들을 순서대로 호출해 정상 응답(항목이 있는)이 나오는 주소를 찾는다."""
    for base in ENDPOINT_CANDIDATES:
        try:
            raw = call(base, from_d, to_d, 1, rows=10)
        except urllib.error.HTTPError as e:
            print(f"[시도] {base} -> HTTP {e.code}")
            continue
        except Exception as e:
            print(f"[시도] {base} -> 오류 {e}")
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            print(f"[시도] {base} -> XML 아님 (앞부분: {raw[:120]!r})")
            continue
        items = root.findall(".//item")
        tc = root.find(".//totalCount")
        rmsg = root.find(".//resultMsg")
        rcode = root.find(".//resultCode")
        print(f"[시도] {base} -> OK, item {len(items)}개, totalCount={tc.text if tc is not None else '?'}, "
              f"resultCode={rcode.text if rcode is not None else '?'}, resultMsg={rmsg.text if rmsg is not None else '?'}")
        # 정상 판단: item이 있거나 totalCount가 숫자로 존재
        if items or (tc is not None and (tc.text or '').isdigit()):
            print(f"[선택] 사용할 주소: {base}")
            return base
    return None


def collect(base, from_d, to_d):
    items, seen, total, page = [], set(), None, 1
    while page <= 30:
        try:
            raw = call(base, from_d, to_d, page, rows=100)
            root = ET.fromstring(raw)
        except Exception as e:
            print(f"페이지 {page} 실패: {e}")
            break
        if total is None:
            tc = root.find(".//totalCount")
            total = int(tc.text) if (tc is not None and (tc.text or '').isdigit()) else 0
            print(f"totalCount={total}")
        page_items = root.findall(".//item")
        if not page_items:
            break
        for it in page_items:
            realm = txt(it, "realmName", "REALM_NAME", "genre", "GENRE", "middleClassNm")
            if ("전시" not in realm) and ("미술" not in realm):
                continue
            title = txt(it, "title", "TITLE", "SUBJECT")
            if not title:
                continue
            place = txt(it, "place", "PLACE", "spatialCoverage", "SPATIAL_COVERAGE",
                        "cntcInsttNm", "CNTC_INSTT_NM", "eventSite")
            area = txt(it, "area", "AREA", "sido", "SIDO", "spatialCoverage", "SPATIAL_COVERAGE")
            start = txt(it, "startDate", "START_DATE", "eventStartDate")
            end = txt(it, "endDate", "END_DATE", "eventEndDate")
            period = txt(it, "period", "PERIOD", "eventPeriod", "TEMPORAL_COVERAGE")
            if not period:
                period = (fmt_date(start) + " ~ " + fmt_date(end)).strip(" ~")
            url = txt(it, "url", "URL", "placeUrl", "REFERENCE_IDENTIFIER")
            img = txt(it, "imageObject", "IMAGE_OBJECT", "thumbnail", "imgUrl", "referenceIdentifier")
            key = (title, place, start)
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "title": title, "place": place, "period": period,
                "region": map_region(area or place), "realm": realm,
                "url": url, "img": img,
            })
        if total and page * 100 >= total:
            break
        page += 1
    return items


def main():
    if not API_KEY:
        print("ERROR: CULTURE_API_KEY 환경변수(GitHub Secret)가 없습니다.")
        return 0  # Action은 실패로 만들지 않음

    today = datetime.date.today()
    from_d = today.strftime("%Y%m%d")
    to_d = (today + datetime.timedelta(days=90)).strftime("%Y%m%d")

    base = find_endpoint(from_d, to_d)
    if not base:
        print("모든 후보 주소에서 전시 데이터를 받지 못했습니다. 위 [시도] 로그를 확인하세요.")
        print("기존 exhibitions.json 은 그대로 둡니다.")
        return 0

    items = collect(base, from_d, to_d)
    print(f"수집된 전시/미술 항목: {len(items)}건")

    if not items:
        print("전시/미술 항목이 0건이라 파일을 덮어쓰지 않고 유지합니다.")
        return 0

    present = [g for g in REGION_ORDER if any(i["region"] == g for i in items)]
    if any(i["region"] == "기타" for i in items):
        present.append("기타")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
