"""Recuperation et mise en cache des prix spot."""

import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error
from typing import Optional
import pandas as pd

from config.admin_config import load_spot_projection_config

HTTP_HEADERS = {
    "User-Agent": "sobry-energy-app/0.1 (+https://sobry.co)",
    "Accept": "application/json",
}


def _to_paris(ts: pd.Timestamp) -> pd.Timestamp:
    # Normalise le timestamp en timezone Europe/Paris.
    if ts.tzinfo is None:
        return ts.tz_localize("Europe/Paris")
    return ts.tz_convert("Europe/Paris")


def _fetch_sobry_prices(start: str, end: str, display: str = "HT"):
    # Appel API Sobry (prix spot).
    base_url = "https://api.sobry.co/api/prices/raw"
    query = urllib.parse.urlencode({"start": start, "end": end, "display": display})
    url = f"{base_url}?{query}"
    try:
        req = urllib.request.Request(url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return []


def _normalize_sobry_prices(data):
    # Normalise les reponses API en liste {timestamp, price_eur_per_kwh}.
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    normalized = []
    if not isinstance(data, list):
        return normalized
    for item in data:
        if not isinstance(item, dict):
            continue
        ts = item.get("timestamp")
        if ts is None:
            continue
        if "price_eur_per_kwh" in item:
            spot = item.get("price_eur_per_kwh")
            spot_in_mwh = False
        else:
            spot = item.get("spot_price")
            spot_in_mwh = True
        if spot is None:
            continue
        try:
            price_eur_per_kwh = float(spot) / 1000.0 if spot_in_mwh else float(spot)
        except (TypeError, ValueError):
            continue
        normalized.append({"timestamp": ts, "price_eur_per_kwh": price_eur_per_kwh})
    return normalized


def _load_cache(cache_path: str) -> list:
    # Cache local de prix spot (optionnel).
    if not cache_path or not os.path.exists(cache_path):
        return []
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _save_cache(cache_path: str, data: list) -> None:
    if not cache_path:
        return
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _save_cache_persistent(cache_path: str, data: list) -> None:
    # Ecrit le cache runtime et le cache bundle du repo pour conserver l'historique dans le code.
    _save_cache(cache_path, data)
    bundled_path = _bundled_cache_path()
    if os.path.abspath(cache_path) == os.path.abspath(bundled_path):
        return
    try:
        _save_cache(bundled_path, data)
    except OSError:
        # En environnement restreint (read-only), on conserve au moins le cache runtime.
        pass


def _parse_prices(data: list) -> pd.DataFrame:
    # Parse et convertit les timestamps en Europe/Paris.
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_convert("Europe/Paris")
    df = df.drop_duplicates(subset=["timestamp"], keep="last")
    return df


def _merge_cache_append_only(cache_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    # Politique append-only: on conserve les anciennes valeurs, on ajoute uniquement les timestamps absents.
    if cache_df.empty:
        merged = new_df.copy()
    elif new_df.empty:
        merged = cache_df.copy()
    else:
        existing_ts = set(cache_df["timestamp"])
        to_append = new_df[~new_df["timestamp"].isin(existing_ts)]
        merged = pd.concat([cache_df, to_append], ignore_index=True)
    if "timestamp" not in merged.columns:
        return pd.DataFrame(columns=["timestamp", "price_eur_per_kwh"])
    merged = merged.drop_duplicates(subset=["timestamp"], keep="first")
    return merged.sort_values("timestamp")


def _filter_range(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    start_dt = pd.Timestamp(start_date, tz="Europe/Paris")
    end_dt = pd.Timestamp(end_date, tz="Europe/Paris")
    return df[(df["timestamp"] >= start_dt) & (df["timestamp"] < end_dt)]


def _expected_timestamps(start_date: str, end_date: str) -> pd.DatetimeIndex:
    # Pas attendu des prix spot: 15 minutes.
    start_dt = pd.Timestamp(start_date, tz="Europe/Paris")
    end_dt = pd.Timestamp(end_date, tz="Europe/Paris")
    return pd.date_range(start_dt, end_dt, freq="15min", inclusive="left")


def _build_intraday_fallback(expected: pd.DatetimeIndex, source_df: pd.DataFrame) -> pd.DataFrame:
    # Construit une serie de secours en repetant un profil 15 min issu du cache local.
    if source_df.empty or len(expected) == 0:
        return pd.DataFrame(columns=["timestamp", "price_eur_per_kwh"])
    profile_df = source_df.copy()
    profile_df["slot"] = profile_df["timestamp"].dt.strftime("%H:%M")
    slot_profile = profile_df.groupby("slot")["price_eur_per_kwh"].median().to_dict()
    if not slot_profile:
        return pd.DataFrame(columns=["timestamp", "price_eur_per_kwh"])
    global_median = float(profile_df["price_eur_per_kwh"].median())
    fallback_rows = []
    for ts in expected:
        slot = ts.strftime("%H:%M")
        price = float(slot_profile.get(slot, global_median))
        fallback_rows.append({"timestamp": ts, "price_eur_per_kwh": price})
    return pd.DataFrame(fallback_rows)


def _shift_years(series: pd.Series, years: int) -> pd.Series:
    # Decale en UTC pour eviter les erreurs DST (heures inexistantes/ambiguës).
    utc = series.dt.tz_convert("UTC")
    shifted = utc + pd.DateOffset(years=years)
    return shifted.dt.tz_convert("Europe/Paris")


def _shift_by_weeks(series: pd.Series, weeks: int) -> pd.Series:
    # Decale de N semaines pour conserver le jour de la semaine.
    utc = series.dt.tz_convert("UTC")
    shifted = utc + pd.Timedelta(weeks=weeks)
    return shifted.dt.tz_convert("Europe/Paris")


def _load_projection_config() -> dict:
    try:
        return load_spot_projection_config()
    except Exception:
        return {}


def _default_spot_price_dir() -> str:
    env_dir = os.environ.get("SOBRY_SPOT_PRICE_DIR")
    if env_dir:
        return env_dir
    env_mode = (os.environ.get("SOBRY_ENV") or os.environ.get("NODE_ENV") or "").lower()
    if env_mode == "production" or getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(appdata, "Sobry", "spot_price")
    return os.path.join(os.path.dirname(__file__), "spot_price")


def _bundled_cache_path() -> str:
    return os.path.join(os.path.dirname(__file__), "spot_price", "spot_price_cache.json")


def _get_transition_rule(config: dict, target_year: int | None) -> dict:
    if not target_year or not isinstance(config, dict):
        return {}
    rules = config.get("transition_rules", {})
    if not isinstance(rules, dict):
        return {}
    rule = rules.get(str(target_year))
    return rule if isinstance(rule, dict) else {}


def _get_config_ratio(
    config: dict,
    reference_year: int | None,
    target_year: int | None,
    rule: dict | None = None
) -> float | None:
    if not reference_year or not target_year:
        return None
    if isinstance(rule, dict) and "ratio" in rule:
        try:
            return float(rule["ratio"])
        except (TypeError, ValueError):
            return None
    transitions = config.get("default_ratio_by_transition", {}) if isinstance(config, dict) else {}
    key = f"{reference_year}to{target_year}"
    ratio = transitions.get(key)
    if ratio is None:
        return None
    try:
        return float(ratio)
    except (TypeError, ValueError):
        return None


def _fetch_spot_prices_internal(
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_path: Optional[str] = None,
    provider_url: Optional[str] = None,
    projection_ratio_override: Optional[float] = None,
    allow_projection: bool = True,
    max_projection_years: int = 3
):
    # Recupere les prix spot, complete le cache si besoin.
    if pd.isna(start) or pd.isna(end):
        raise ValueError("start/end timestamps are missing; cannot fetch spot prices")
    start_ts = _to_paris(pd.Timestamp(start))
    end_ts = _to_paris(pd.Timestamp(end))
    start_date = start_ts.date().isoformat()
    end_date = end_ts.date().isoformat()
    if end_ts != end_ts.normalize():
        end_date = (end_ts + pd.Timedelta(days=1)).date().isoformat()
    if cache_path is None:
        spot_dir = _default_spot_price_dir()
        cache_path = os.path.join(spot_dir, "spot_price_cache.json")

    cache_raw = _load_cache(cache_path)
    if not cache_raw:
        bundled_cache = _bundled_cache_path()
        if os.path.abspath(cache_path) != os.path.abspath(bundled_cache):
            cache_raw = _load_cache(bundled_cache)
    cache_norm = _normalize_sobry_prices(cache_raw) if cache_raw else []
    cache_df = _parse_prices(cache_norm)

    expected = _expected_timestamps(start_date, end_date)
    cached_range = _filter_range(cache_df, start_date, end_date) if not cache_df.empty else cache_df
    cached_ts = set(cached_range["timestamp"]) if not cached_range.empty else set()
    # Trouve les timestamps manquants dans le cache.
    missing = [ts for ts in expected if ts not in cached_ts]

    fetch_failed = False
    if missing:
        if provider_url:
            try:
                req = urllib.request.Request(provider_url, headers=HTTP_HEADERS)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.load(resp)
            except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
                data = []
                fetch_failed = True
        else:
            data = _fetch_sobry_prices(start_date, end_date)
            if not data:
                fetch_failed = True

        if data:
            needs_normalize = False
            if isinstance(data, dict) and "data" in data:
                needs_normalize = True
            elif isinstance(data, list):
                first = data[0] if data else {}
                if isinstance(first, dict) and "price_eur_per_kwh" not in first and "spot_price" in first:
                    needs_normalize = True
            if needs_normalize:
                data = _normalize_sobry_prices(data)
        fetched_df = _parse_prices(data if isinstance(data, list) else [])
        if fetched_df.empty and data:
            fetched_df = pd.DataFrame(columns=["timestamp", "price_eur_per_kwh"])
        merged_df = _merge_cache_append_only(cache_df, fetched_df)
        to_save = [
            {
                "timestamp": row["timestamp"].isoformat(),
                "price_eur_per_kwh": float(row["price_eur_per_kwh"])
            }
            for _, row in merged_df.iterrows()
        ]
        _save_cache_persistent(cache_path, to_save)
        cache_df = merged_df

    final_df = _filter_range(cache_df, start_date, end_date) if not cache_df.empty else cache_df
    expected = _expected_timestamps(start_date, end_date)
    final_ts = set(final_df["timestamp"]) if not final_df.empty else set()
    remaining_missing = [ts for ts in expected if ts not in final_ts]
    projection_ratio = None
    projection_applied = False
    projection_override = None
    projection_source_years = []
    projection_config_ratio = None
    projection_config_key = None
    projection_config = _load_projection_config()
    projection_targets = []

    if remaining_missing and allow_projection:
        expected_years = sorted({ts.year for ts in expected})
        for target_year in expected_years:
            segment_start_ts = max(
                start_ts,
                pd.Timestamp(year=target_year, month=1, day=1, tz="Europe/Paris")
            )
            segment_end_ts = min(
                end_ts,
                pd.Timestamp(year=target_year + 1, month=1, day=1, tz="Europe/Paris")
            )
            if segment_end_ts <= segment_start_ts:
                continue
            remaining_missing_year = [ts for ts in remaining_missing if ts.year == target_year]
            if not remaining_missing_year:
                continue

            projection_rule = _get_transition_rule(projection_config, target_year)
            fallback_years = projection_rule.get("fallback_years", []) if isinstance(projection_rule, dict) else []
            candidate_years_back = []
            if isinstance(fallback_years, list) and fallback_years:
                for year in fallback_years:
                    try:
                        year_int = int(year)
                    except (TypeError, ValueError):
                        continue
                    years_back = target_year - year_int
                    if years_back <= 0 or years_back > max_projection_years:
                        continue
                    candidate_years_back.append(years_back)
            if not candidate_years_back:
                candidate_years_back = list(range(1, max_projection_years + 1))

            per_year_source_years = []
            per_year_ratio = None
            per_year_config_ratio = None
            per_year_config_key = None
            per_year_applied = False

            for years_back in candidate_years_back:
                weeks_back = years_back * 52
                prev_start_ts = _shift_by_weeks(pd.Series([segment_start_ts]), -weeks_back).iloc[0]
                prev_end_ts = _shift_by_weeks(pd.Series([segment_end_ts]), -weeks_back).iloc[0]
                prev_start_date = prev_start_ts.date().isoformat()
                prev_end_date = prev_end_ts.date().isoformat()
                if prev_end_ts != prev_end_ts.normalize():
                    prev_end_date = (prev_end_ts + pd.Timedelta(days=1)).date().isoformat()

                prev_range = _filter_range(cache_df, prev_start_date, prev_end_date) if not cache_df.empty else cache_df
                prev_expected = _expected_timestamps(prev_start_date, prev_end_date)
                prev_cached_ts = set(prev_range["timestamp"]) if not prev_range.empty else set()
                prev_missing = [ts for ts in prev_expected if ts not in prev_cached_ts]

                if prev_missing:
                    if provider_url:
                        try:
                            req = urllib.request.Request(provider_url, headers=HTTP_HEADERS)
                            with urllib.request.urlopen(req, timeout=20) as resp:
                                prev_data = json.load(resp)
                        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
                            prev_data = []
                            fetch_failed = True
                    else:
                        prev_data = _fetch_sobry_prices(prev_start_date, prev_end_date)
                        if not prev_data:
                            fetch_failed = True
                    if prev_data:
                        needs_normalize = False
                        if isinstance(prev_data, dict) and "data" in prev_data:
                            needs_normalize = True
                        elif isinstance(prev_data, list):
                            first = prev_data[0] if prev_data else {}
                            if isinstance(first, dict) and "price_eur_per_kwh" not in first and "spot_price" in first:
                                needs_normalize = True
                        if needs_normalize:
                            prev_data = _normalize_sobry_prices(prev_data)
                    prev_df = _parse_prices(prev_data if isinstance(prev_data, list) else [])
                    if prev_df.empty and prev_data:
                        prev_df = pd.DataFrame(columns=["timestamp", "price_eur_per_kwh"])
                    if not prev_df.empty:
                        merged_df = _merge_cache_append_only(cache_df, prev_df)
                        to_save = [
                            {
                                "timestamp": row["timestamp"].isoformat(),
                                "price_eur_per_kwh": float(row["price_eur_per_kwh"])
                            }
                            for _, row in merged_df.iterrows()
                        ]
                        _save_cache_persistent(cache_path, to_save)
                        cache_df = merged_df

                prev_range = _filter_range(cache_df, prev_start_date, prev_end_date) if not cache_df.empty else cache_df
                if not prev_range.empty:
                    prev_shifted = prev_range.copy()
                    prev_shifted["timestamp"] = _shift_by_weeks(prev_shifted["timestamp"], weeks_back)
                else:
                    prev_shifted = prev_range

                ratio = 1.0
                if projection_ratio_override is None:
                    config_ratio = _get_config_ratio(
                        projection_config,
                        prev_start_ts.year,
                        target_year,
                        rule=projection_rule
                    )
                    if config_ratio is not None:
                        ratio = config_ratio
                        per_year_config_ratio = config_ratio
                        if isinstance(projection_rule, dict) and "ratio" in projection_rule:
                            per_year_config_key = f"target:{target_year}"
                        else:
                            per_year_config_key = f"{prev_start_ts.year}to{target_year}"
                if not prev_shifted.empty:
                    current_segment = final_df
                    if not final_df.empty:
                        current_segment = final_df[
                            (final_df["timestamp"] >= segment_start_ts)
                            & (final_df["timestamp"] < segment_end_ts)
                        ]
                    if not current_segment.empty:
                        overlap = current_segment.merge(
                            prev_shifted,
                            on="timestamp",
                            how="inner",
                            suffixes=("_current", "_prev")
                        )
                        if not overlap.empty:
                            prev_mean = float(overlap["price_eur_per_kwh_prev"].mean())
                            current_mean = float(overlap["price_eur_per_kwh_current"].mean())
                            if prev_mean > 0:
                                ratio = current_mean / prev_mean if per_year_config_ratio is None else ratio
                                if projection_ratio is None:
                                    projection_ratio = ratio
                if projection_ratio_override is not None:
                    ratio = float(projection_ratio_override)
                    projection_ratio = ratio
                    projection_override = ratio

                if not prev_shifted.empty:
                    missing_df = prev_shifted[prev_shifted["timestamp"].isin(remaining_missing_year)].copy()
                    if not missing_df.empty:
                        missing_df["price_eur_per_kwh"] = missing_df["price_eur_per_kwh"] * ratio
                        final_df = pd.concat([final_df, missing_df], ignore_index=True)
                        final_df = final_df.drop_duplicates(subset=["timestamp"], keep="last")
                        final_df = final_df.sort_values("timestamp")
                        if projection_ratio is None:
                            projection_ratio = ratio
                        projection_applied = True
                        per_year_ratio = ratio
                        per_year_applied = True
                        per_year_source_years.append(years_back)
                        projection_source_years.append(years_back)
                        final_ts = set(final_df["timestamp"]) if not final_df.empty else set()
                        remaining_missing_year = [ts for ts in remaining_missing_year if ts not in final_ts]
                        remaining_missing = [ts for ts in expected if ts not in final_ts]
                        if not remaining_missing_year:
                            break
                if not remaining_missing:
                    break

            if per_year_applied or per_year_ratio is not None:
                if projection_config_ratio is None and per_year_config_ratio is not None:
                    projection_config_ratio = per_year_config_ratio
                if projection_config_key is None and per_year_config_key is not None:
                    projection_config_key = per_year_config_key
                projection_targets.append({
                    "year": target_year,
                    "ratio": per_year_ratio,
                    "applied": per_year_applied,
                    "source_years": per_year_source_years,
                    "config_ratio": per_year_config_ratio,
                    "config_key": per_year_config_key,
                })
            if not remaining_missing:
                break

    prices = [
        {
            "timestamp": row["timestamp"].isoformat(),
            "price_eur_per_kwh": float(row["price_eur_per_kwh"])
        }
        for _, row in final_df.sort_values("timestamp").iterrows()
    ]
    if fetch_failed and not prices:
        fallback_df = _build_intraday_fallback(expected, cache_df)
        if fallback_df.empty:
            raise ValueError("Service prix spot indisponible (HTTP 500). Reessayez plus tard.")
        final_df = fallback_df.sort_values("timestamp")
        prices = [
            {
                "timestamp": row["timestamp"].isoformat(),
                "price_eur_per_kwh": float(row["price_eur_per_kwh"])
            }
            for _, row in final_df.iterrows()
        ]
        projection_applied = True
        projection_ratio = projection_ratio if projection_ratio is not None else 1.0
        projection_targets.append({
            "year": int(start_ts.year),
            "ratio": projection_ratio,
            "applied": True,
            "source_years": [],
            "config_ratio": None,
            "config_key": "intraday_cache_fallback",
        })
    meta = {
        "projection": {
            "method": "replay_prev_years_global_ratio",
            "ratio": projection_ratio,
            "applied": projection_applied,
            "override": projection_override,
            "source_years": projection_source_years,
            "target_year": int(start_ts.year),
            "reference_years": [int(start_ts.year - years_back) for years_back in projection_source_years],
            "config_ratio": projection_config_ratio,
            "config_key": projection_config_key,
            "targets": projection_targets,
        }
    }
    return prices, meta


def fetch_spot_prices(
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_path: Optional[str] = None,
    provider_url: Optional[str] = None,
    allow_projection: bool = True
):
    prices, _meta = _fetch_spot_prices_internal(start, end, cache_path, provider_url, None, allow_projection)
    return prices


def fetch_spot_prices_with_meta(
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_path: Optional[str] = None,
    provider_url: Optional[str] = None,
    projection_ratio_override: Optional[float] = None,
    allow_projection: bool = True
):
    return _fetch_spot_prices_internal(start, end, cache_path, provider_url, projection_ratio_override, allow_projection)
