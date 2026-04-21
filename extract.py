"""
LIT metrics extractor — Meta Ads + Google Ads + Klaviyo + Shopify.
Genera data/YYYY-MM.json. Solo agregados, sin PII.
"""

import argparse
import base64
import calendar
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extract")

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"


# ── helpers ──────────────────────────────────────────────────────────────────

def month_bounds(month: str) -> tuple[date, date]:
    y, m = map(int, month.split("-"))
    first = date(y, m, 1)
    last_day = calendar.monthrange(y, m)[1]
    last = date(y, m, last_day)
    today = date.today()
    if last > today:
        last = today
    return first, last


def iso_range(first: date, last: date) -> tuple[str, str]:
    return first.isoformat(), last.isoformat()


def daterange(first: date, last: date):
    d = first
    while d <= last:
        yield d
        d += timedelta(days=1)


def safe_div(a, b, default=0.0):
    return round(a / b, 4) if b else default


# ── META ─────────────────────────────────────────────────────────────────────

META_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
META_ACCOUNT = os.environ.get("META_AD_ACCOUNT_ID", "")
META_API = "https://graph.facebook.com/v21.0"


def _meta_get(path, params):
    params = {**params, "access_token": META_TOKEN}
    r = httpx.get(f"{META_API}{path}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def _meta_paginate(path, params):
    out = []
    data = _meta_get(path, params)
    out.extend(data.get("data", []))
    while data.get("paging", {}).get("next"):
        r = httpx.get(data["paging"]["next"], timeout=60)
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("data", []))
    return out


def _meta_actions_lookup(actions, action_values, action_type="purchase"):
    count = 0.0
    value = 0.0
    for a in actions or []:
        if a.get("action_type") == action_type:
            count = float(a.get("value", 0))
    for a in action_values or []:
        if a.get("action_type") == action_type:
            value = float(a.get("value", 0))
    return count, value


def _meta_base_metrics(row):
    spend = float(row.get("spend", 0) or 0)
    impressions = int(row.get("impressions", 0) or 0)
    clicks = int(row.get("clicks", 0) or 0)
    reach = int(row.get("reach", 0) or 0)
    purchases, revenue = _meta_actions_lookup(row.get("actions"), row.get("action_values"))
    return {
        "spend": round(spend, 2),
        "impressions": impressions,
        "clicks": clicks,
        "reach": reach,
        "purchases": round(purchases, 2),
        "revenue": round(revenue, 2),
        "ctr": round(safe_div(clicks, impressions) * 100, 2),
        "cpc": round(safe_div(spend, clicks), 2),
        "cpm": round(safe_div(spend * 1000, impressions), 2),
        "cpa": round(safe_div(spend, purchases), 2),
        "roas": round(safe_div(revenue, spend), 2),
    }


def extract_meta(month: str) -> dict:
    if not META_TOKEN or not META_ACCOUNT:
        log.warning("Meta: missing credentials, skipping")
        return {"totals": {}, "daily": [], "campaigns": [], "platforms": [], "creatives": []}

    first, last = month_bounds(month)
    since, until = iso_range(first, last)
    time_range = json.dumps({"since": since, "until": until})

    fields = "spend,impressions,clicks,reach,frequency,actions,action_values"

    totals_rows = _meta_paginate(
        f"/{META_ACCOUNT}/insights",
        {"fields": fields, "time_range": time_range, "level": "account"},
    )
    totals = _meta_base_metrics(totals_rows[0]) if totals_rows else {}

    daily_rows = _meta_paginate(
        f"/{META_ACCOUNT}/insights",
        {
            "fields": fields,
            "time_range": time_range,
            "level": "account",
            "time_increment": 1,
        },
    )
    daily = [{"date": r.get("date_start"), **_meta_base_metrics(r)} for r in daily_rows]

    campaign_rows = _meta_paginate(
        f"/{META_ACCOUNT}/insights",
        {
            "fields": "campaign_name," + fields,
            "time_range": time_range,
            "level": "campaign",
            "limit": 200,
        },
    )
    campaigns = [
        {"campaign": r.get("campaign_name"), **_meta_base_metrics(r)} for r in campaign_rows
    ]

    adset_rows = _meta_paginate(
        f"/{META_ACCOUNT}/insights",
        {
            "fields": "campaign_name,adset_name," + fields,
            "time_range": time_range,
            "level": "adset",
            "limit": 200,
        },
    )
    adsets = [
        {"campaign": r.get("campaign_name"), "adset": r.get("adset_name"), **_meta_base_metrics(r)}
        for r in adset_rows
    ]

    platform_rows = _meta_paginate(
        f"/{META_ACCOUNT}/insights",
        {
            "fields": fields,
            "time_range": time_range,
            "level": "account",
            "breakdowns": "publisher_platform",
        },
    )
    platforms = [
        {"platform": r.get("publisher_platform"), **_meta_base_metrics(r)} for r in platform_rows
    ]

    ad_rows = _meta_paginate(
        f"/{META_ACCOUNT}/insights",
        {
            "fields": "ad_id,ad_name,campaign_name,adset_name," + fields,
            "time_range": time_range,
            "level": "ad",
            "limit": 200,
        },
    )
    ad_ids = list({r["ad_id"] for r in ad_rows if r.get("ad_id")})
    creative_map = {}
    if ad_ids:
        chunks = [ad_ids[i : i + 50] for i in range(0, len(ad_ids), 50)]
        for chunk in chunks:
            data = _meta_get(
                "/",
                {
                    "ids": ",".join(chunk),
                    "fields": "creative{id,thumbnail_url,title,body}",
                },
            )
            for ad_id, payload in data.items():
                creative = payload.get("creative") or {}
                creative_map[ad_id] = {
                    "creative_id": creative.get("id"),
                    "thumbnail_url": creative.get("thumbnail_url"),
                    "title": creative.get("title"),
                    "body": creative.get("body"),
                }

    merged = defaultdict(lambda: {"campaigns": set(), "adsets": set(), "spend": 0, "impressions": 0, "clicks": 0,
                                   "reach": 0, "purchases": 0.0, "revenue": 0.0})
    for r in ad_rows:
        cm = creative_map.get(r.get("ad_id"), {})
        cid = cm.get("creative_id") or r.get("ad_id")
        m = _meta_base_metrics(r)
        c = merged[cid]
        c["campaigns"].add(r.get("campaign_name") or "")
        c["adsets"].add(r.get("adset_name") or "")
        c["spend"] += m["spend"]
        c["impressions"] += m["impressions"]
        c["clicks"] += m["clicks"]
        c["reach"] += m["reach"]
        c["purchases"] += m["purchases"]
        c["revenue"] += m["revenue"]
        c["thumbnail_url"] = cm.get("thumbnail_url")
        c["title"] = cm.get("title")
        c["body"] = cm.get("body")
        c["ad_name"] = r.get("ad_name")

    creatives = []
    for cid, c in merged.items():
        spend = c["spend"]
        imp = c["impressions"]
        clk = c["clicks"]
        purchases = c["purchases"]
        revenue = c["revenue"]
        creatives.append({
            "creative_id": cid,
            "ad_name": c.get("ad_name"),
            "thumbnail_url": c.get("thumbnail_url"),
            "title": c.get("title"),
            "body": c.get("body"),
            "campaigns": sorted(x for x in c["campaigns"] if x),
            "adsets": sorted(x for x in c["adsets"] if x),
            "spend": round(spend, 2),
            "impressions": imp,
            "clicks": clk,
            "reach": c["reach"],
            "purchases": round(purchases, 2),
            "revenue": round(revenue, 2),
            "ctr": round(safe_div(clk, imp) * 100, 2),
            "cpc": round(safe_div(spend, clk), 2),
            "cpa": round(safe_div(spend, purchases), 2),
            "roas": round(safe_div(revenue, spend), 2),
        })
    creatives.sort(key=lambda x: x["spend"], reverse=True)

    return {
        "totals": totals,
        "daily": daily,
        "campaigns": campaigns,
        "adsets": adsets,
        "platforms": platforms,
        "creatives": creatives,
    }


# ── GOOGLE ADS ───────────────────────────────────────────────────────────────

GA_DEV_TOKEN = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", "")
GA_MCC = os.environ.get("GOOGLE_ADS_MCC_ID", "")
GA_CUSTOMER = os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "")

_ga_client = None


def _ga_get_client():
    global _ga_client
    if _ga_client is not None:
        return _ga_client
    from google.ads.googleads.client import GoogleAdsClient

    _ga_client = GoogleAdsClient.load_from_dict({
        "developer_token": GA_DEV_TOKEN,
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN", ""),
        "login_customer_id": GA_MCC,
        "use_proto_plus": False,
    })
    return _ga_client


def _ga_query(gaql):
    client = _ga_get_client()
    service = client.get_service("GoogleAdsService")
    resp = service.search_stream(customer_id=GA_CUSTOMER, query=gaql)
    rows = []
    for batch in resp:
        for row in batch.results:
            rows.append(row)
    return rows


def _ga_cost(m):
    return (m.cost_micros or 0) / 1_000_000


def _ga_cpc(m):
    return (m.average_cpc or 0) / 1_000_000


def extract_google(month: str) -> dict:
    if not (GA_DEV_TOKEN and GA_MCC and GA_CUSTOMER):
        log.warning("Google Ads: missing credentials, skipping")
        return {"totals": {}, "daily": [], "campaigns": [], "keywords": [], "gender": [], "age": []}

    first, last = month_bounds(month)
    start, end = iso_range(first, last)

    daily_rows = _ga_query(f"""
        SELECT segments.date, metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM customer
        WHERE segments.date BETWEEN '{start}' AND '{end}'
    """)
    daily_agg = defaultdict(lambda: {"impressions": 0, "clicks": 0, "cost": 0.0,
                                      "conversions": 0.0, "revenue": 0.0})
    for row in daily_rows:
        d = row.segments.date
        m = row.metrics
        daily_agg[d]["impressions"] += m.impressions
        daily_agg[d]["clicks"] += m.clicks
        daily_agg[d]["cost"] += _ga_cost(m)
        daily_agg[d]["conversions"] += m.conversions
        daily_agg[d]["revenue"] += m.conversions_value
    daily = []
    for d, v in sorted(daily_agg.items()):
        daily.append({
            "date": d,
            "impressions": v["impressions"],
            "clicks": v["clicks"],
            "cost": round(v["cost"], 2),
            "conversions": round(v["conversions"], 2),
            "revenue": round(v["revenue"], 2),
            "ctr": round(safe_div(v["clicks"], v["impressions"]) * 100, 2),
            "cpc": round(safe_div(v["cost"], v["clicks"]), 2),
            "cpa": round(safe_div(v["cost"], v["conversions"]), 2),
            "conv_rate": round(safe_div(v["conversions"], v["clicks"]) * 100, 2),
        })

    t = defaultdict(float)
    for v in daily_agg.values():
        for k, x in v.items():
            t[k] += x
    totals = {
        "impressions": int(t["impressions"]),
        "clicks": int(t["clicks"]),
        "cost": round(t["cost"], 2),
        "conversions": round(t["conversions"], 2),
        "revenue": round(t["revenue"], 2),
        "ctr": round(safe_div(t["clicks"], t["impressions"]) * 100, 2),
        "cpc": round(safe_div(t["cost"], t["clicks"]), 2),
        "cpa": round(safe_div(t["cost"], t["conversions"]), 2),
        "conv_rate": round(safe_div(t["conversions"], t["clicks"]) * 100, 2),
        "roas": round(safe_div(t["revenue"], t["cost"]), 2),
    }

    campaign_rows = _ga_query(f"""
        SELECT campaign.name, campaign.status, campaign.advertising_channel_type,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE segments.date BETWEEN '{start}' AND '{end}'
    """)
    camp_agg = defaultdict(lambda: {"impressions": 0, "clicks": 0, "cost": 0.0,
                                     "conversions": 0.0, "revenue": 0.0,
                                     "type": "", "status": ""})
    for row in campaign_rows:
        name = row.campaign.name
        m = row.metrics
        c = camp_agg[name]
        c["impressions"] += m.impressions
        c["clicks"] += m.clicks
        c["cost"] += _ga_cost(m)
        c["conversions"] += m.conversions
        c["revenue"] += m.conversions_value
        c["type"] = str(row.campaign.advertising_channel_type).split(".")[-1]
        c["status"] = str(row.campaign.status).split(".")[-1]
    campaigns = []
    for name, v in camp_agg.items():
        campaigns.append({
            "campaign": name,
            "status": v["status"],
            "type": v["type"],
            "impressions": v["impressions"],
            "clicks": v["clicks"],
            "cost": round(v["cost"], 2),
            "conversions": round(v["conversions"], 2),
            "revenue": round(v["revenue"], 2),
            "ctr": round(safe_div(v["clicks"], v["impressions"]) * 100, 2),
            "cpc": round(safe_div(v["cost"], v["clicks"]), 2),
            "cpa": round(safe_div(v["cost"], v["conversions"]), 2),
            "conv_rate": round(safe_div(v["conversions"], v["clicks"]) * 100, 2),
            "roas": round(safe_div(v["revenue"], v["cost"]), 2),
        })
    campaigns.sort(key=lambda x: x["cost"], reverse=True)

    ag_rows = _ga_query(f"""
        SELECT campaign.name, ad_group.name, ad_group.status,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM ad_group
        WHERE segments.date BETWEEN '{start}' AND '{end}'
    """)
    ag_agg = defaultdict(lambda: {"impressions": 0, "clicks": 0, "cost": 0.0,
                                   "conversions": 0.0, "revenue": 0.0,
                                   "campaign": "", "status": ""})
    for row in ag_rows:
        key = (row.campaign.name, row.ad_group.name)
        m = row.metrics
        a = ag_agg[key]
        a["impressions"] += m.impressions
        a["clicks"] += m.clicks
        a["cost"] += _ga_cost(m)
        a["conversions"] += m.conversions
        a["revenue"] += m.conversions_value
        a["campaign"] = row.campaign.name
        a["status"] = str(row.ad_group.status).split(".")[-1]
    ad_groups = []
    for (_camp, ag_name), v in ag_agg.items():
        ad_groups.append({
            "campaign": v["campaign"],
            "ad_group": ag_name,
            "status": v["status"],
            "impressions": v["impressions"],
            "clicks": v["clicks"],
            "cost": round(v["cost"], 2),
            "conversions": round(v["conversions"], 2),
            "revenue": round(v["revenue"], 2),
            "ctr": round(safe_div(v["clicks"], v["impressions"]) * 100, 2),
            "cpc": round(safe_div(v["cost"], v["clicks"]), 2),
            "cpa": round(safe_div(v["cost"], v["conversions"]), 2),
            "conv_rate": round(safe_div(v["conversions"], v["clicks"]) * 100, 2),
            "roas": round(safe_div(v["revenue"], v["cost"]), 2),
        })
    ad_groups.sort(key=lambda x: x["cost"], reverse=True)

    keyword_rows = _ga_query(f"""
        SELECT campaign.name, ad_group.name,
               ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.average_cpc
        FROM keyword_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
        ORDER BY metrics.cost_micros DESC
        LIMIT 200
    """)
    keywords = []
    for row in keyword_rows:
        m = row.metrics
        cost = _ga_cost(m)
        keywords.append({
            "keyword": row.ad_group_criterion.keyword.text,
            "match_type": str(row.ad_group_criterion.keyword.match_type).split(".")[-1],
            "campaign": row.campaign.name,
            "ad_group": row.ad_group.name,
            "impressions": m.impressions,
            "clicks": m.clicks,
            "cost": round(cost, 2),
            "conversions": round(m.conversions, 2),
            "ctr": round(safe_div(m.clicks, m.impressions) * 100, 2),
            "avg_cpc": round(_ga_cpc(m), 2),
            "cpa": round(safe_div(cost, m.conversions), 2),
        })

    gender_rows = _ga_query(f"""
        SELECT ad_group_criterion.gender.type,
               metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions
        FROM gender_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
    """)
    g_agg = defaultdict(lambda: {"impressions": 0, "clicks": 0, "cost": 0.0, "conversions": 0.0})
    for row in gender_rows:
        key = str(row.ad_group_criterion.gender.type_).split(".")[-1]
        m = row.metrics
        g_agg[key]["impressions"] += m.impressions
        g_agg[key]["clicks"] += m.clicks
        g_agg[key]["cost"] += _ga_cost(m)
        g_agg[key]["conversions"] += m.conversions
    gender = [{"gender": k, **{**v, "cost": round(v["cost"], 2),
                                "conversions": round(v["conversions"], 2)}} for k, v in g_agg.items()]

    age_rows = _ga_query(f"""
        SELECT ad_group_criterion.age_range.type,
               metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions
        FROM age_range_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'
    """)
    a_agg = defaultdict(lambda: {"impressions": 0, "clicks": 0, "cost": 0.0, "conversions": 0.0})
    for row in age_rows:
        key = str(row.ad_group_criterion.age_range.type_).split(".")[-1]
        m = row.metrics
        a_agg[key]["impressions"] += m.impressions
        a_agg[key]["clicks"] += m.clicks
        a_agg[key]["cost"] += _ga_cost(m)
        a_agg[key]["conversions"] += m.conversions
    age = [{"age_range": k, **{**v, "cost": round(v["cost"], 2),
                                "conversions": round(v["conversions"], 2)}} for k, v in a_agg.items()]

    return {
        "totals": totals,
        "daily": daily,
        "campaigns": campaigns,
        "ad_groups": ad_groups,
        "keywords": keywords,
        "gender": gender,
        "age": age,
    }


# ── KLAVIYO ──────────────────────────────────────────────────────────────────

KLAVIYO_KEY = os.environ.get("KLAVIYO_API_KEY", "")
KLAVIYO_API = "https://a.klaviyo.com/api"
KLAVIYO_HEADERS = {
    "Authorization": f"Klaviyo-API-Key {KLAVIYO_KEY}",
    "revision": "2024-10-15",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
KLAVIYO_STATS = [
    "recipients",
    "delivered",
    "opens",
    "opens_unique",
    "clicks",
    "clicks_unique",
    "unsubscribes",
    "unsubscribe_rate",
    "open_rate",
    "click_rate",
    "bounced",
    "bounce_rate",
    "conversions",
    "conversion_value",
    "conversion_uniques",
]


def _klaviyo_placed_order_metric_id() -> str | None:
    url = f"{KLAVIYO_API}/metrics/"
    found = None
    while url:
        r = httpx.get(url, headers=KLAVIYO_HEADERS, timeout=30)
        if r.status_code >= 400:
            log.warning("Klaviyo metrics list failed: %s %s", r.status_code, r.text[:200])
            return None
        j = r.json()
        for m in j.get("data", []):
            attrs = m.get("attributes", {})
            if attrs.get("name") == "Placed Order":
                found = m.get("id")
                break
        if found:
            return found
        url = j.get("links", {}).get("next")
    return None


def _klaviyo_post_report(kind: str, first: date, last: date, metric_id: str) -> list:
    body = {
        "data": {
            "type": f"{kind}-values-report",
            "attributes": {
                "statistics": KLAVIYO_STATS,
                "timeframe": {
                    "start": f"{first.isoformat()}T00:00:00+00:00",
                    "end": f"{(last + timedelta(days=1)).isoformat()}T00:00:00+00:00",
                },
                "conversion_metric_id": metric_id,
            },
        }
    }
    r = httpx.post(
        f"{KLAVIYO_API}/{kind}-values-reports/",
        headers=KLAVIYO_HEADERS,
        json=body,
        timeout=60,
    )
    if r.status_code >= 400:
        log.warning("Klaviyo %s report failed: %s %s", kind, r.status_code, r.text[:300])
        return []
    return r.json().get("data", {}).get("attributes", {}).get("results", [])


def _klaviyo_list_campaigns(first: date, last: date) -> list:
    filter_str = (
        f'and(equals(messages.channel,"email"),'
        f'greater-or-equal(scheduled_at,{first.isoformat()}T00:00:00Z),'
        f'less-than(scheduled_at,{(last + timedelta(days=1)).isoformat()}T00:00:00Z))'
    )
    url = f"{KLAVIYO_API}/campaigns/?filter={filter_str}&fields[campaign]=name,send_time,scheduled_at,status"
    out = []
    while url:
        r = httpx.get(url, headers=KLAVIYO_HEADERS, timeout=60)
        if r.status_code >= 400:
            log.warning("Klaviyo campaigns list failed: %s %s", r.status_code, r.text[:300])
            return out
        j = r.json()
        out.extend(j.get("data", []))
        url = j.get("links", {}).get("next")
    return out


def _klaviyo_list_flows() -> list:
    url = f"{KLAVIYO_API}/flows/?fields[flow]=name,status&page[size]=50"
    out = []
    while url:
        r = httpx.get(url, headers=KLAVIYO_HEADERS, timeout=30)
        if r.status_code >= 400:
            log.warning("Klaviyo flows list failed: %s %s", r.status_code, r.text[:300])
            return out
        j = r.json()
        out.extend(j.get("data", []))
        url = j.get("links", {}).get("next")
    return out


def _klaviyo_report_row_to_stats(row):
    groupings = row.get("groupings", {})
    statistics = row.get("statistics", {})
    return groupings, statistics


def _klaviyo_kpis(stats_totals):
    sends = stats_totals.get("recipients", 0)
    opens = stats_totals.get("opens_unique", 0)
    clicks = stats_totals.get("clicks_unique", 0)
    unsubs = stats_totals.get("unsubscribes", 0)
    revenue = stats_totals.get("conversion_value", 0.0)
    return {
        "sends": int(sends),
        "opens": int(opens),
        "clicks": int(clicks),
        "unsubs": int(unsubs),
        "revenue": round(float(revenue), 2),
        "open_rate": round(safe_div(opens, sends) * 100, 2),
        "click_rate": round(safe_div(clicks, sends) * 100, 2),
        "unsub_rate": round(safe_div(unsubs, sends) * 100, 2),
    }


def extract_klaviyo(month: str) -> dict:
    if not KLAVIYO_KEY:
        log.warning("Klaviyo: missing credentials, skipping")
        return {"totals": {}, "daily": [], "flows": [], "campaigns": []}

    first, last = month_bounds(month)
    metric_id = _klaviyo_placed_order_metric_id()
    if not metric_id:
        log.warning("Klaviyo: Placed Order metric not found, skipping")
        return {"totals": {}, "daily": [], "flows": [], "campaigns": []}

    campaign_index = {c["id"]: c["attributes"] for c in _klaviyo_list_campaigns(first, last)}
    flow_index = {f["id"]: f["attributes"] for f in _klaviyo_list_flows()}

    camp_report = _klaviyo_post_report("campaign", first, last, metric_id)
    flow_report = _klaviyo_post_report("flow", first, last, metric_id)

    campaigns = []
    for row in camp_report:
        g, s = _klaviyo_report_row_to_stats(row)
        cid = g.get("campaign_id")
        meta = campaign_index.get(cid, {})
        kpis = _klaviyo_kpis(s)
        campaigns.append({
            "campaign_id": cid,
            "name": meta.get("name"),
            "send_time": meta.get("send_time") or meta.get("scheduled_at"),
            **kpis,
        })
    campaigns.sort(key=lambda x: x.get("send_time") or "", reverse=True)

    flows = []
    flow_agg = defaultdict(lambda: defaultdict(float))
    for row in flow_report:
        g, s = _klaviyo_report_row_to_stats(row)
        fid = g.get("flow_id")
        for k, v in s.items():
            flow_agg[fid][k] += float(v or 0)
    for fid, s in flow_agg.items():
        meta = flow_index.get(fid, {})
        kpis = _klaviyo_kpis(s)
        flows.append({
            "flow_id": fid,
            "name": meta.get("name"),
            "status": meta.get("status"),
            **kpis,
        })
    flows.sort(key=lambda x: x["revenue"], reverse=True)

    def totals_from(rows):
        out = defaultdict(float)
        for r in rows:
            for k in ("sends", "opens", "clicks", "unsubs", "revenue"):
                out[k] += r.get(k, 0) or 0
        return out

    camp_t = totals_from(campaigns)
    flow_t = totals_from(flows)
    total_sends = camp_t["sends"] + flow_t["sends"]
    total_opens = camp_t["opens"] + flow_t["opens"]
    total_clicks = camp_t["clicks"] + flow_t["clicks"]
    total_unsubs = camp_t["unsubs"] + flow_t["unsubs"]
    totals = {
        "revenue_total": round(camp_t["revenue"] + flow_t["revenue"], 2),
        "revenue_campaigns": round(camp_t["revenue"], 2),
        "revenue_flows": round(flow_t["revenue"], 2),
        "sends": int(total_sends),
        "opens": int(total_opens),
        "clicks": int(total_clicks),
        "unsubs": int(total_unsubs),
        "open_rate": round(safe_div(total_opens, total_sends) * 100, 2),
        "click_rate": round(safe_div(total_clicks, total_sends) * 100, 2),
        "unsub_rate": round(safe_div(total_unsubs, total_sends) * 100, 2),
    }

    daily_agg = defaultdict(lambda: {"revenue": 0.0, "sends": 0, "opens": 0})
    for c in campaigns:
        st = (c.get("send_time") or "")[:10]
        if st:
            daily_agg[st]["revenue"] += c["revenue"]
            daily_agg[st]["sends"] += c["sends"]
            daily_agg[st]["opens"] += c["opens"]
    daily = []
    for d in daterange(first, last):
        k = d.isoformat()
        v = daily_agg.get(k, {"revenue": 0.0, "sends": 0, "opens": 0})
        daily.append({
            "date": k,
            "revenue": round(v["revenue"], 2),
            "sends": int(v["sends"]),
            "opens": int(v["opens"]),
            "open_rate": round(safe_div(v["opens"], v["sends"]) * 100, 2),
        })

    return {
        "totals": totals,
        "daily": daily,
        "flows": flows,
        "campaigns": campaigns,
    }


# ── SHOPIFY ──────────────────────────────────────────────────────────────────

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_API_VERSION = "2024-10"

_shopify_token_cache: str | None = None


def _shopify_access_token() -> str:
    """Return a usable Shopify Admin API token.

    Dev Dashboard apps (post 2026-01-01) issue short-lived tokens via
    client_credentials grant. If SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET
    are set we refresh on first call and cache for the process lifetime.
    Falls back to a static SHOPIFY_TOKEN otherwise.
    """
    global _shopify_token_cache
    if _shopify_token_cache:
        return _shopify_token_cache
    if SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET:
        r = httpx.post(
            f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
            data={
                "grant_type": "client_credentials",
                "client_id": SHOPIFY_CLIENT_ID,
                "client_secret": SHOPIFY_CLIENT_SECRET,
            },
            timeout=15,
        )
        r.raise_for_status()
        token = r.json().get("access_token")
        if not token:
            raise RuntimeError(f"Shopify token refresh returned no token: {r.text[:200]}")
        _shopify_token_cache = token
        log.info("Shopify token refreshed via client_credentials")
        return token
    if SHOPIFY_TOKEN and SHOPIFY_TOKEN != "PENDIENTE":
        _shopify_token_cache = SHOPIFY_TOKEN
        return SHOPIFY_TOKEN
    raise RuntimeError(
        "Shopify credentials missing: set SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET "
        "or a static SHOPIFY_TOKEN"
    )


def _shopify_graphql(query, variables=None):
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    r = httpx.post(
        url,
        headers={
            "X-Shopify-Access-Token": _shopify_access_token(),
            "Content-Type": "application/json",
        },
        json={"query": query, "variables": variables or {}},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


SHOPIFY_ORDERS_QUERY = """
query($cursor: String, $query: String!) {
  orders(first: 100, after: $cursor, query: $query, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        createdAt
        displayFinancialStatus
        tags
        currentSubtotalPriceSet { shopMoney { amount } }
        currentTotalPriceSet { shopMoney { amount } }
        totalRefundedSet { shopMoney { amount } }
        customer { numberOfOrders }
        lineItems(first: 50) {
          edges {
            node {
              currentQuantity
              originalUnitPriceSet { shopMoney { amount } }
              product { id title }
            }
          }
        }
      }
    }
  }
}
"""


def extract_shopify(month: str) -> dict:
    if not (SHOPIFY_STORE and SHOPIFY_TOKEN):
        log.warning("Shopify: missing credentials, skipping")
        return {"totals": {}, "daily": [], "products": [], "breakdowns": {}}

    first, last = month_bounds(month)
    query_str = (
        f"created_at:>={first.isoformat()} "
        f"created_at:<={last.isoformat()} "
        f"financial_status:paid OR financial_status:partially_paid OR financial_status:partially_refunded"
    )

    cursor = None
    orders = []
    while True:
        resp = _shopify_graphql(SHOPIFY_ORDERS_QUERY, {"cursor": cursor, "query": query_str})
        data = resp.get("data", {}).get("orders", {})
        if not data:
            errors = resp.get("errors")
            if errors:
                log.error("Shopify GraphQL error: %s", errors)
            break
        for edge in data.get("edges", []):
            orders.append(edge["node"])
        if data.get("pageInfo", {}).get("hasNextPage"):
            cursor = data["pageInfo"]["endCursor"]
        else:
            break

    def order_amount(o):
        return float(o["currentTotalPriceSet"]["shopMoney"]["amount"])

    def order_refunds(o):
        rs = o.get("totalRefundedSet")
        return float(rs["shopMoney"]["amount"]) if rs else 0.0

    def order_has_subscription(o):
        tags = o.get("tags") or []
        for t in tags:
            tl = (t or "").lower()
            if "subscription" in tl or "recharge" in tl or "seal" in tl:
                return True
        return False

    daily_agg = defaultdict(lambda: {"orders": 0, "revenue": 0.0, "refunds": 0.0,
                                      "new": 0, "returning": 0, "subs": 0, "onetime": 0})
    product_agg = defaultdict(lambda: {"title": "", "orders": 0, "units": 0, "revenue": 0.0})

    total = {"orders": 0, "revenue": 0.0, "refunds": 0.0, "new": 0, "returning": 0,
             "subs_orders": 0, "onetime_orders": 0, "subs_revenue": 0.0, "onetime_revenue": 0.0}

    for o in orders:
        d = (o["createdAt"] or "")[:10]
        amt = order_amount(o)
        refunds = order_refunds(o)
        customer = o.get("customer") or {}
        try:
            num_orders = int(customer.get("numberOfOrders") or 0)
        except (TypeError, ValueError):
            num_orders = 0
        is_new = num_orders <= 1
        is_sub = order_has_subscription(o)

        daily_agg[d]["orders"] += 1
        daily_agg[d]["revenue"] += amt
        daily_agg[d]["refunds"] += refunds
        if is_new:
            daily_agg[d]["new"] += 1
            total["new"] += 1
        else:
            daily_agg[d]["returning"] += 1
            total["returning"] += 1
        if is_sub:
            daily_agg[d]["subs"] += 1
            total["subs_orders"] += 1
            total["subs_revenue"] += amt
        else:
            daily_agg[d]["onetime"] += 1
            total["onetime_orders"] += 1
            total["onetime_revenue"] += amt

        total["orders"] += 1
        total["revenue"] += amt
        total["refunds"] += refunds

        for edge in o.get("lineItems", {}).get("edges", []):
            li = edge["node"]
            prod = li.get("product") or {}
            pid = prod.get("id") or "unknown"
            qty = li.get("currentQuantity", 0) or 0
            unit_price = float(li["originalUnitPriceSet"]["shopMoney"]["amount"])
            p = product_agg[pid]
            p["title"] = prod.get("title", "")
            p["orders"] += 1
            p["units"] += qty
            p["revenue"] += qty * unit_price

    daily = []
    for d in daterange(first, last):
        k = d.isoformat()
        v = daily_agg.get(k, {"orders": 0, "revenue": 0.0, "refunds": 0.0,
                               "new": 0, "returning": 0, "subs": 0, "onetime": 0})
        daily.append({
            "date": k,
            "orders": v["orders"],
            "revenue": round(v["revenue"], 2),
            "refunds": round(v["refunds"], 2),
            "aov": round(safe_div(v["revenue"], v["orders"]), 2),
            "new": v["new"],
            "returning": v["returning"],
            "subscription_orders": v["subs"],
            "onetime_orders": v["onetime"],
        })

    products = [
        {
            "product_id": pid,
            "title": p["title"],
            "orders": p["orders"],
            "units": p["units"],
            "revenue": round(p["revenue"], 2),
        }
        for pid, p in product_agg.items()
    ]
    products.sort(key=lambda x: x["revenue"], reverse=True)

    totals = {
        "orders": total["orders"],
        "revenue": round(total["revenue"], 2),
        "refunds": round(total["refunds"], 2),
        "net_revenue": round(total["revenue"] - total["refunds"], 2),
        "aov": round(safe_div(total["revenue"], total["orders"]), 2),
        "new_customers": total["new"],
        "returning_customers": total["returning"],
        "subscription_orders": total["subs_orders"],
        "onetime_orders": total["onetime_orders"],
        "subscription_revenue": round(total["subs_revenue"], 2),
        "onetime_revenue": round(total["onetime_revenue"], 2),
        "subscription_pct": round(safe_div(total["subs_orders"], total["orders"]) * 100, 2),
        "returning_pct": round(safe_div(total["returning"], total["orders"]) * 100, 2),
        "refund_rate": round(safe_div(total["refunds"], total["revenue"]) * 100, 2),
    }

    breakdowns = {
        "new_vs_returning": [
            {"bucket": "new", "orders": total["new"]},
            {"bucket": "returning", "orders": total["returning"]},
        ],
        "subscription_vs_onetime": [
            {"bucket": "subscription", "orders": total["subs_orders"],
             "revenue": round(total["subs_revenue"], 2)},
            {"bucket": "onetime", "orders": total["onetime_orders"],
             "revenue": round(total["onetime_revenue"], 2)},
        ],
    }

    return {
        "totals": totals,
        "daily": daily,
        "products": products,
        "breakdowns": breakdowns,
    }


# ── WHOLESALE (Holded) ───────────────────────────────────────────────────────
# B2B invoices + CRM pipeline stages.

HOLDED_API_KEY = os.environ.get("HOLDED_API_KEY", "")
HOLDED_INVOICING = "https://api.holded.com/api/invoicing/v1"
HOLDED_CRM = "https://api.holded.com/api/crm/v1"

# Stage IDs from the "LIT - CRM" funnel (hardcoded — must match Holded setup)
HOLDED_STAGES = [
    ("6924316373aa8b6ff50532bb", "Prospects"),
    ("6924316373aa8b6ff50532bc", "Outreach / Visits"),
    ("6985ead1ffc3d8cc190b36ff", "Qualified / In Communication"),
    ("699c8e8fe5c58fb5570b7d59", "Lost"),
    ("6930220d9e7882a79e087f1f", "Order: Consignment"),
]


def _holded_list_invoices(start_ts: int, end_ts: int) -> list[dict]:
    r = httpx.get(
        f"{HOLDED_INVOICING}/documents/invoice",
        headers={"key": HOLDED_API_KEY},
        params={"starttmp": start_ts, "endtmp": end_ts, "sort": "created-asc"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def _holded_list_leads() -> list[dict]:
    r = httpx.get(
        f"{HOLDED_CRM}/leads",
        headers={"key": HOLDED_API_KEY},
        params={"limit": 1000},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def extract_wholesale(month: str) -> dict:
    if not HOLDED_API_KEY:
        log.warning("Holded: missing credentials, skipping")
        return {"totals": {}, "daily": [], "pipeline": [], "top_accounts": []}

    first, last = month_bounds(month)
    start_ts = int(datetime(first.year, first.month, first.day, tzinfo=timezone.utc).timestamp())
    # Include the whole of `last` day
    end_ts = int(datetime(last.year, last.month, last.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())

    # 1. Invoices within the month
    all_invoices = _holded_list_invoices(start_ts, end_ts)
    invoices = []
    for inv in all_invoices:
        try:
            ts = int(inv.get("date") or 0)
        except (ValueError, TypeError):
            continue
        if not (start_ts <= ts <= end_ts):
            continue
        invoices.append(inv)

    daily_agg = defaultdict(lambda: {"orders": 0, "revenue": 0.0, "paid": 0.0})
    account_agg = defaultdict(lambda: {"orders": 0, "revenue": 0.0})
    total_revenue = 0.0
    total_paid = 0.0
    total_pending = 0.0
    for inv in invoices:
        try:
            d = datetime.fromtimestamp(int(inv.get("date") or 0), tz=timezone.utc).date().isoformat()
        except Exception:
            continue
        total = float(inv.get("total") or 0)
        paid = float(inv.get("paymentsTotal") or 0)
        pending = float(inv.get("paymentsPending") or 0)
        daily_agg[d]["orders"] += 1
        daily_agg[d]["revenue"] += total
        daily_agg[d]["paid"] += paid
        total_revenue += total
        total_paid += paid
        total_pending += pending
        account = (inv.get("contactName") or "Sin cliente").strip() or "Sin cliente"
        account_agg[account]["orders"] += 1
        account_agg[account]["revenue"] += total

    daily = []
    for d in daterange(first, last):
        k = d.isoformat()
        v = daily_agg.get(k, {"orders": 0, "revenue": 0.0, "paid": 0.0})
        daily.append({
            "date": k,
            "orders": v["orders"],
            "revenue": round(v["revenue"], 2),
            "paid": round(v["paid"], 2),
        })

    top_accounts = [
        {"account": name, "orders": v["orders"], "revenue": round(v["revenue"], 2)}
        for name, v in account_agg.items()
    ]
    top_accounts.sort(key=lambda x: x["revenue"], reverse=True)

    totals = {
        "orders": len(invoices),
        "revenue": round(total_revenue, 2),
        "paid": round(total_paid, 2),
        "pending": round(total_pending, 2),
        "aov": round(safe_div(total_revenue, len(invoices)), 2),
        "paid_pct": round(safe_div(total_paid, total_revenue) * 100, 2),
        "accounts": len(account_agg),
    }

    # 2. Pipeline stages — current snapshot (not filterable by month)
    try:
        leads = _holded_list_leads()
    except Exception as exc:
        log.warning("Holded leads fetch failed: %s", exc)
        leads = []
    stage_counts = {sid: 0 for sid, _ in HOLDED_STAGES}
    for lead in leads:
        sid = lead.get("stageId")
        if sid in stage_counts:
            stage_counts[sid] += 1
    pipeline = [
        {"stage": name, "count": stage_counts[sid]}
        for sid, name in HOLDED_STAGES
    ]

    return {
        "totals": totals,
        "daily": daily,
        "pipeline": pipeline,
        "top_accounts": top_accounts,
    }


# ── AFFILIATES (GoAffPro) ────────────────────────────────────────────────────
# GoAffPro replaced UpPromote in April 2026 for LIT's affiliate program.

GOAFFPRO_TOKEN = os.environ.get("GOAFFPRO_ACCESS_TOKEN", "")
GOAFFPRO_API = "https://api.goaffpro.com/v1"


def _goaffpro_get(path: str, params: dict | None = None) -> dict:
    r = httpx.get(
        f"{GOAFFPRO_API}{path}",
        headers={"x-goaffpro-access-token": GOAFFPRO_TOKEN, "Accept": "application/json"},
        params=params or {},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _parse_iso(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        return None


def extract_affiliates(month: str) -> dict:
    if not GOAFFPRO_TOKEN:
        log.warning("GoAffPro: missing credentials, skipping")
        return {"totals": {}, "daily": [], "top_affiliates": []}

    first, last = month_bounds(month)

    aff_resp = _goaffpro_get("/admin/affiliates", {
        "count": 500,
        "fields": "id,name,email,ref_code,created,tags",
    })
    affiliates = aff_resp.get("affiliates", [])

    ord_resp = _goaffpro_get("/admin/orders", {
        "count": 10000,
        "fields": "id,total,subtotal,affiliate_id,commission,status,created",
    })
    orders_all = ord_resp.get("orders", [])

    # Affiliate index for name/email lookup
    aff_index = {a.get("id"): a for a in affiliates}

    # Filter orders to the month and status=approved
    month_orders = []
    for o in orders_all:
        d = _parse_iso(o.get("created"))
        if not d:
            continue
        if not (first <= d <= last):
            continue
        if (o.get("status") or "").lower() != "approved":
            continue
        month_orders.append({**o, "_date": d})

    # Cumulative affiliate count (all-time) up to end of month
    total_affs_all_time = 0
    new_affs_this_month = 0
    for a in affiliates:
        d = _parse_iso(a.get("created"))
        if d and d <= last:
            total_affs_all_time += 1
            if first <= d <= last:
                new_affs_this_month += 1

    # Aggregates
    daily_agg = defaultdict(lambda: {"orders": 0, "revenue": 0.0, "commission": 0.0})
    aff_agg = defaultdict(lambda: {"orders": 0, "revenue": 0.0, "commission": 0.0})
    total_revenue = 0.0
    total_commission = 0.0
    active_affiliates = set()
    for o in month_orders:
        d_iso = o["_date"].isoformat()
        total = float(o.get("total") or 0)
        commission = float(o.get("commission") or 0)
        aff_id = o.get("affiliate_id")
        daily_agg[d_iso]["orders"] += 1
        daily_agg[d_iso]["revenue"] += total
        daily_agg[d_iso]["commission"] += commission
        aff_agg[aff_id]["orders"] += 1
        aff_agg[aff_id]["revenue"] += total
        aff_agg[aff_id]["commission"] += commission
        total_revenue += total
        total_commission += commission
        if aff_id is not None:
            active_affiliates.add(aff_id)

    daily = []
    for d in daterange(first, last):
        k = d.isoformat()
        v = daily_agg.get(k, {"orders": 0, "revenue": 0.0, "commission": 0.0})
        daily.append({
            "date": k,
            "orders": v["orders"],
            "revenue": round(v["revenue"], 2),
            "commission": round(v["commission"], 2),
        })

    top_affiliates = []
    for aff_id, v in aff_agg.items():
        meta = aff_index.get(aff_id, {}) or {}
        top_affiliates.append({
            "affiliate_id": aff_id,
            "name": meta.get("name"),
            "ref_code": meta.get("ref_code"),
            "orders": v["orders"],
            "revenue": round(v["revenue"], 2),
            "commission": round(v["commission"], 2),
        })
    top_affiliates.sort(key=lambda x: x["revenue"], reverse=True)

    totals = {
        "orders": len(month_orders),
        "revenue": round(total_revenue, 2),
        "commission": round(total_commission, 2),
        "active_affiliates": len(active_affiliates),
        "total_affiliates": total_affs_all_time,
        "new_affiliates": new_affs_this_month,
        "aov": round(safe_div(total_revenue, len(month_orders)), 2),
        "commission_rate": round(safe_div(total_commission, total_revenue) * 100, 2),
    }

    return {
        "totals": totals,
        "daily": daily,
        "top_affiliates": top_affiliates,
    }


# ── commit helper ────────────────────────────────────────────────────────────

def github_commit(month: str, path: Path):
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
    if not (repo and token):
        log.info("No GITHUB_REPOSITORY/token set, skipping commit")
        return
    rel = path.relative_to(ROOT).as_posix()
    content = base64.b64encode(path.read_bytes()).decode()

    url = f"https://api.github.com/repos/{repo}/contents/{rel}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = httpx.get(url, headers=headers, timeout=30)
    sha = r.json().get("sha") if r.status_code == 200 else None
    body = {
        "message": f"data: refresh {month}",
        "content": content,
        "committer": {"name": "lit-metrics-bot", "email": "bot@litsalt.com"},
    }
    if sha:
        body["sha"] = sha
    r = httpx.put(url, headers=headers, json=body, timeout=30)
    if r.status_code >= 300:
        log.error("GitHub commit failed: %s %s", r.status_code, r.text[:300])
    else:
        log.info("Committed %s", rel)


# ── main ─────────────────────────────────────────────────────────────────────

def resolve_month(arg: str) -> str:
    if arg == "current":
        today = date.today()
        return f"{today.year:04d}-{today.month:02d}"
    return arg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default="current", help="YYYY-MM o 'current'")
    parser.add_argument("--commit", action="store_true", help="commit via GitHub Contents API (requires GH_PAT + GITHUB_REPOSITORY)")
    args = parser.parse_args()

    month = resolve_month(args.month)
    log.info("Extracting month %s", month)

    def safe_extract(name, fn, empty):
        try:
            return fn(month)
        except Exception as exc:
            log.exception("%s failed: %s", name, exc)
            return {**empty, "error": str(exc)[:300]}

    payload = {
        "month": month,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meta": safe_extract("meta", extract_meta,
                             {"totals": {}, "daily": [], "campaigns": [], "adsets": [], "platforms": [], "creatives": []}),
        "google": safe_extract("google", extract_google,
                               {"totals": {}, "daily": [], "campaigns": [], "ad_groups": [], "keywords": [], "gender": [], "age": []}),
        "klaviyo": safe_extract("klaviyo", extract_klaviyo,
                                {"totals": {}, "daily": [], "flows": [], "campaigns": []}),
        "shopify": safe_extract("shopify", extract_shopify,
                                {"totals": {}, "daily": [], "products": [], "breakdowns": {}}),
        "wholesale": safe_extract("wholesale", extract_wholesale,
                                  {"totals": {}, "daily": [], "pipeline": [], "top_accounts": []}),
        "affiliates": safe_extract("affiliates", extract_affiliates,
                                   {"totals": {}, "daily": [], "top_affiliates": []}),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / f"{month}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Wrote %s (%.1f KB)", out, out.stat().st_size / 1024)

    manifest_path = DATA_DIR / "manifest.json"
    months = sorted(
        p.stem for p in DATA_DIR.glob("*.json") if p.name != "manifest.json"
    )
    manifest_path.write_text(
        json.dumps({"months": months, "updated_at": payload["generated_at"]}, indent=2),
        encoding="utf-8",
    )
    log.info("Manifest updated: %d months", len(months))

    if args.commit:
        github_commit(month, out)
        github_commit("manifest", manifest_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Extract failed: %s", e)
        sys.exit(1)
