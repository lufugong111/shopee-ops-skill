#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


DEFAULT_HOST = "https://partner.shopeemobile.com"
ADD_ITEM_PATH = "/api/v2/product/add_item"
UPDATE_ITEM_PATH = "/api/v2/product/update_item"
PRODUCT_INFO_PATH = "/api/v2/product/get_item_base_info"
MODEL_LIST_PATH = "/api/v2/product/get_model_list"
UPDATE_PRICE_PATH = "/api/v2/product/update_price"
UPDATE_STOCK_PATH = "/api/v2/product/update_stock"
UPDATE_MODEL_PATH = "/api/v2/product/update_model"
INIT_TIER_VARIATION_PATH = "/api/v2/product/init_tier_variation"
UPDATE_TIER_VARIATION_PATH = "/api/v2/product/update_tier_variation"
INIT_VIDEO_UPLOAD_PATH = "/api/v2/media_space/init_video_upload"
UPLOAD_VIDEO_PART_PATH = "/api/v2/media_space/upload_video_part"
COMPLETE_VIDEO_UPLOAD_PATH = "/api/v2/media_space/complete_video_upload"
GET_VIDEO_UPLOAD_RESULT_PATH = "/api/v2/media_space/get_video_upload_result"
SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_IMAGE_MAP = SKILL_DIR / "work" / "shopee_uploaded_images.json"
DEFAULT_OUTPUT_DIR = SKILL_DIR / "outputs"
DEFAULT_CONFIG = SKILL_DIR / "config" / "credentials.json"
DEFAULT_TOKEN_FILE = Path.home() / ".shopee_tokens" / "live_token.json"
SHOPEE_TOKEN_PATH = "/api/v2/auth/access_token/get"
DEFAULT_LOCATION_ID = ""
DEFAULT_LOGISTIC_ID = None
DEFAULT_SIZE_ID = None
DEFAULT_SHIPPING_FEE = None
DEFAULT_CATEGORY_ID = None
DEFAULT_CURRENT_PRICE = None
DEFAULT_ORIGINAL_PRICE = None
DEFAULT_WEIGHT = None
DEFAULT_STOCK = None
DEFAULT_DAYS_TO_SHIP = None
DEFAULT_PACKAGE = (None, None, None)
DEFAULT_SIZE_OPTIONS: list[str] = []
REQUEST_RETRY_DELAYS = (1, 3, 8)
UPDATE_LOCK_RETRY_DELAYS = (8, 15, 30)
MAX_VIDEO_SIZE_BYTES = 30 * 1000 * 1000
VIDEO_PART_SIZE_BYTES = 4 * 1024 * 1024
VIDEO_TRANSCODE_POLL_SECONDS = 5
VIDEO_TRANSCODE_MAX_ATTEMPTS = 30
DEFAULT_DESCRIPTION_TEXT = ""

COLOR_TRANSLATIONS = {
    "黑色": "Black",
    "花灰色": "Heather Gray",
    "杏色": "Apricot",
    "粉色": "Pink",
    "棕色": "Brown",
    "红色": "Red",
    "灰色": "Gray",
    "白色": "White",
    "蓝色": "Blue",
    "绿色": "Dark Green",
    "墨绿色": "Dark Green",
    "Green": "Dark Green",
    "浅灰色": "Heather Gray",
    "Light Gray": "Heather Gray",
    "卡其色": "Khaki",
    "黄色": "Yellow",
    "橘色": "Orange",
    "紫色": "Purple",
    "米色": "Beige",
}

def read_text_auto(path: Path) -> str:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"):
        try:
            return path.read_text(encoding=encoding)
        except Exception as exc:  # noqa: BLE001 - encoding fallback
            last_error = exc
    raise SystemExit(f"无法读取文本文件 {path}: {last_error}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001 - surface path in a friendly way
        raise SystemExit(f"无法读取 JSON 文件 {path}: {exc}") from exc


def load_optional_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = load_json(path)
    return payload if isinstance(payload, dict) else {}


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_text(text: str) -> str:
    text = text.replace("\ufeff", "").replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in lines:
        if not line:
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
            continue
        buffer.append(line)
    if buffer:
        paragraphs.append(" ".join(buffer))
    return "\n\n".join(paragraphs).strip()


def decode_asset_label(stem: str) -> str:
    candidate = re.sub(r"u([0-9a-fA-F]{4})", lambda m: f"\\u{m.group(1)}", stem)
    try:
        return candidate.encode("utf-8").decode("unicode_escape")
    except Exception:  # noqa: BLE001 - fallback to the raw stem
        return stem


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "option"


def translate_color(label: str) -> str:
    return COLOR_TRANSLATIONS.get(label, label)


def build_color_sku(color: str, size: str, args: argparse.Namespace) -> str:
    """Build a generic model SKU from the confirmed prefix/suffix and options."""
    color_code = slugify(translate_color(color)).upper()
    size_code = slugify(size).upper()
    if not args.sku_prefix or not args.sku_suffix:
        raise SystemExit("缺少本次确认的 SKU 前缀或后缀。")
    return f"{args.sku_prefix}-{size_code}-{color_code}-{args.sku_suffix}"


def required_env(name: str, value: str | None = None) -> str:
    result = (value if value is not None else os.getenv(name, "")).strip()
    if not result:
        raise SystemExit(f"缺少 {name}。")
    return result


def parse_int(value: str, name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} 必须是整数: {value}") from exc


def parse_float(value: str, name: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise SystemExit(f"{name} 必须是数字: {value}") from exc


def api_host(raw: str | None) -> str:
    host = (raw or DEFAULT_HOST).strip().rstrip("/")
    return host


def sign_path(partner_id: str, partner_key: str, path: str, timestamp: int,
              access_token: str = "", shop_id: int | None = None) -> str:
    raw = f"{partner_id}{path}{timestamp}"
    if access_token:
        if shop_id is None:
            raise ValueError("shop_id is required when access_token is used")
        raw += f"{access_token}{shop_id}"
    return hmac.new(partner_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()


def request_json(method: str, host: str, path: str, params: dict[str, Any],
                 body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{host}{path}?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json", "User-Agent": "shopee-draft-writer/1.0"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    raw = ""
    # Retrying GET is safe. Retrying a mutating POST after a timeout can create
    # duplicate items when the server accepted the first request.
    retryable = method.upper() in {"GET", "HEAD"}
    attempts = len(REQUEST_RETRY_DELAYS) + 1 if retryable else 1
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"Shopee HTTP {exc.code}: {detail}") from exc
        except (TimeoutError, socket.timeout, ConnectionError, urllib.error.URLError) as exc:
            reason = getattr(exc, "reason", exc)
            if retryable and attempt < len(REQUEST_RETRY_DELAYS):
                time.sleep(REQUEST_RETRY_DELAYS[attempt])
                continue
            raise SystemExit(f"无法连接 Shopee API: {reason}") from exc

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Shopee 返回的不是 JSON: {raw[:500]}") from exc
    if not isinstance(result, dict):
        raise SystemExit(f"Shopee 返回格式异常: {result!r}")
    if result.get("error"):
        raise SystemExit(f"Shopee API 错误: {json.dumps(result, ensure_ascii=False)}")
    return result


def is_update_lock_error(exc: BaseException) -> bool:
    message = str(exc)
    return "337211300" in message or "get update lock failed" in message


def init_tier_variation_with_lock_retry(
    host: str,
    partner_id: str,
    partner_key: str,
    access_token: str,
    shop_id: int,
    tier_body: dict[str, Any],
) -> dict[str, Any]:
    for attempt in range(len(UPDATE_LOCK_RETRY_DELAYS) + 1):
        tier_params = common_params(
            partner_id, partner_key, INIT_TIER_VARIATION_PATH, access_token, shop_id
        )
        try:
            return request_json("POST", host, INIT_TIER_VARIATION_PATH, tier_params, tier_body)
        except SystemExit as exc:
            if attempt >= len(UPDATE_LOCK_RETRY_DELAYS) or not is_update_lock_error(exc):
                raise
            delay = UPDATE_LOCK_RETRY_DELAYS[attempt]
            print(
                f"Shopee item update lock, retrying init_tier_variation in {delay}s...",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise SystemExit("init_tier_variation retry loop ended unexpectedly")


def request_multipart(method: str, host: str, path: str, params: dict[str, Any],
                      body: bytes, content_type: str) -> dict[str, Any]:
    url = f"{host}{path}?{urllib.parse.urlencode(params)}"
    headers = {
        "Accept": "application/json",
        "Content-Type": content_type,
        "User-Agent": "shopee-draft-writer/1.0",
    }
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Shopee HTTP {exc.code}: {detail}") from exc
    except (TimeoutError, socket.timeout, ConnectionError, urllib.error.URLError) as exc:
        reason = getattr(exc, "reason", exc)
        raise SystemExit(f"Could not connect to Shopee API: {reason}") from exc

    try:
        result = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Shopee returned non-JSON response: {raw[:500]}") from exc
    if not isinstance(result, dict):
        raise SystemExit(f"Shopee returned an unexpected response: {result!r}")
    if result.get("error"):
        raise SystemExit(f"Shopee API error: {json.dumps(result, ensure_ascii=False)}")
    return result


def multipart_file_body(fields: dict[str, Any], file_field: str, filename: str,
                        content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = f"----CodexShopee{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    chunks.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(content)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def validate_video_file(video_file: Path) -> dict[str, Any]:
    if not video_file.exists() or not video_file.is_file():
        raise SystemExit(f"video file not found: {video_file}")
    size = video_file.stat().st_size
    if video_file.suffix.lower() != ".mp4":
        raise SystemExit(f"video file must be mp4: {video_file.name}")
    if size > MAX_VIDEO_SIZE_BYTES:
        raise SystemExit(
            "video file is too large for Shopee product video: "
            f"{size} bytes ({size / 1000 / 1000:.2f} MB). "
            f"Limit is {MAX_VIDEO_SIZE_BYTES} bytes (30 MB). "
            "Compress the video below the limit before updating the item."
        )
    return {
        "path": str(video_file),
        "size": size,
        "max_size": MAX_VIDEO_SIZE_BYTES,
        "part_size": VIDEO_PART_SIZE_BYTES,
        "part_count": (size + VIDEO_PART_SIZE_BYTES - 1) // VIDEO_PART_SIZE_BYTES,
    }


def upload_product_video(video_file: Path, host: str, partner_id: str,
                         partner_key: str, access_token: str, shop_id: int) -> dict[str, Any]:
    content = video_file.read_bytes()
    file_md5 = hashlib.md5(content).hexdigest()
    init_body = {"file_md5": file_md5, "file_size": len(content)}
    init_params = common_params(partner_id, partner_key, INIT_VIDEO_UPLOAD_PATH, access_token, shop_id)
    init_result = request_json("POST", host, INIT_VIDEO_UPLOAD_PATH, init_params, init_body)
    video_upload_id = str(((init_result.get("response") or {}).get("video_upload_id") or "")).strip()
    if not video_upload_id:
        raise SystemExit(f"init_video_upload did not return video_upload_id: {json.dumps(init_result, ensure_ascii=False)}")

    part_results: list[dict[str, Any]] = []
    upload_started = time.time()
    for seq, offset in enumerate(range(0, len(content), VIDEO_PART_SIZE_BYTES)):
        part = content[offset:offset + VIDEO_PART_SIZE_BYTES]
        content_md5 = hashlib.md5(part).hexdigest()
        body, content_type = multipart_file_body(
            {
                "video_upload_id": video_upload_id,
                "part_seq": seq,
                "content_md5": content_md5,
            },
            "part_content",
            f"{video_file.stem}.part{seq}.mp4",
            part,
            "video/mp4",
        )
        upload_params = common_params(partner_id, partner_key, UPLOAD_VIDEO_PART_PATH, access_token, shop_id)
        upload_result = request_multipart("POST", host, UPLOAD_VIDEO_PART_PATH, upload_params, body, content_type)
        part_results.append({
            "part_seq": seq,
            "part_size": len(part),
            "content_md5": content_md5,
            "response": upload_result,
        })

    part_seq_list = [part["part_seq"] for part in part_results]
    complete_body = {
        "video_upload_id": video_upload_id,
        "part_seq_list": part_seq_list,
        "upload_cost": max(1, int(round(time.time() - upload_started))),
    }
    complete_params = common_params(partner_id, partner_key, COMPLETE_VIDEO_UPLOAD_PATH, access_token, shop_id)
    complete_result = request_json("POST", host, COMPLETE_VIDEO_UPLOAD_PATH, complete_params, complete_body)

    poll_results: list[dict[str, Any]] = []
    final_result: dict[str, Any] = {}
    for attempt in range(1, VIDEO_TRANSCODE_MAX_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(VIDEO_TRANSCODE_POLL_SECONDS)
        result_params = common_params(partner_id, partner_key, GET_VIDEO_UPLOAD_RESULT_PATH, access_token, shop_id)
        result_params["video_upload_id"] = video_upload_id
        result = request_json("GET", host, GET_VIDEO_UPLOAD_RESULT_PATH, result_params)
        response = result.get("response") or {}
        status = str(response.get("status") or "").upper()
        poll_results.append({"attempt": attempt, "status": status, "response": response})
        if status in {"SUCCEEDED", "SUCCESS"}:
            final_result = result
            break
        if status in {"FAILED", "FAILURE", "CANCELLED"}:
            raise SystemExit(f"video transcode failed: {json.dumps(result, ensure_ascii=False)}")
    else:
        raise SystemExit(f"video transcode did not finish after {VIDEO_TRANSCODE_MAX_ATTEMPTS} attempts")

    return {
        "video_upload_id": video_upload_id,
        "file_md5": file_md5,
        "file_size": len(content),
        "init_request": init_body,
        "init_response": init_result,
        "part_results": part_results,
        "complete_request": complete_body,
        "complete_response": complete_result,
        "poll_results": poll_results,
        "final_response": final_result,
    }


def update_existing_item_video(args: argparse.Namespace, host: str, output_dir: Path) -> None:
    if args.item_id is None:
        raise SystemExit("--video-file requires --item-id; video file upload is only supported for existing item updates")
    video_file = Path(args.video_file).expanduser()
    video_info = validate_video_file(video_file)
    if not args.execute:
        preview_path = output_dir / "shopee_update_video_preview.json"
        save_json(preview_path, {
            "mode": "dry-run",
            "item_id": args.item_id,
            "video_file": video_info,
            "note": "Live execution uploads the video, waits for Shopee transcoding, and updates only video_upload_id on the existing item.",
        })
        print(json.dumps({
            "mode": "dry-run",
            "item_id": args.item_id,
            "video_file": video_info,
            "preview_file": str(preview_path),
        }, ensure_ascii=False, indent=2))
        return

    partner_id, partner_key = load_partner_credentials(args)
    access_token, shop_id = load_access_credentials(args)
    info_params = common_params(partner_id, partner_key, PRODUCT_INFO_PATH, access_token, shop_id)
    info_params["item_id_list"] = str(args.item_id)
    before_result = request_json("GET", host, PRODUCT_INFO_PATH, info_params)
    item_list = (before_result.get("response") or {}).get("item_list") or []
    if not item_list or not isinstance(item_list[0], dict):
        raise SystemExit(f"get_item_base_info did not return item {args.item_id}")
    live_item = item_list[0]
    if str(live_item.get("item_status", "")).upper() != "UNLIST":
        raise SystemExit(f"video updates are only allowed for UNLIST items; current status is {live_item.get('item_status')!r}")

    video_upload = upload_product_video(video_file, host, partner_id, partner_key, access_token, shop_id)
    update_body = {"item_id": args.item_id, "video_upload_id": [video_upload["video_upload_id"]]}
    update_params = common_params(partner_id, partner_key, UPDATE_ITEM_PATH, access_token, shop_id)
    update_result = request_json("POST", host, UPDATE_ITEM_PATH, update_params, update_body)

    verify_params = common_params(partner_id, partner_key, PRODUCT_INFO_PATH, access_token, shop_id)
    verify_params["item_id_list"] = str(args.item_id)
    after_result = request_json("GET", host, PRODUCT_INFO_PATH, verify_params)
    verify_items = (after_result.get("response") or {}).get("item_list") or []
    verified_item = verify_items[0] if verify_items and isinstance(verify_items[0], dict) else {}
    if str(verified_item.get("item_status", "")).upper() != "UNLIST":
        raise SystemExit(f"item status changed unexpectedly after video update: {verified_item.get('item_status')!r}")

    result_path = output_dir / "shopee_update_video_result.json"
    save_json(result_path, {
        "get_item_base_info_before": before_result,
        "video_validation": video_info,
        "video_upload": video_upload,
        "update_item_request": update_body,
        "update_item_response": update_result,
        "get_item_base_info_after": after_result,
    })
    print(json.dumps({
        "item_id": args.item_id,
        "item_status": verified_item.get("item_status"),
        "video_upload_id": video_upload["video_upload_id"],
        "saved_to": str(result_path),
    }, ensure_ascii=False, indent=2))


def common_params(partner_id: str, partner_key: str, path: str, access_token: str,
                  shop_id: int, timestamp: int | None = None) -> dict[str, Any]:
    ts = timestamp or int(time.time())
    return {
        "partner_id": partner_id,
        "timestamp": ts,
        "sign": sign_path(partner_id, partner_key, path, ts, access_token, shop_id),
        "access_token": access_token,
        "shop_id": shop_id,
    }


def load_access_credentials(args: argparse.Namespace) -> tuple[str, int]:
    access_token = os.getenv("SHOPEE_ACCESS_TOKEN", "").strip() or args.access_token or ""
    shop_value = os.getenv("SHOPEE_SHOP_ID", "").strip() or args.shop_id or ""
    config = getattr(args, "_config", {})
    shopee = config.get("shopee") or {}
    access_token = access_token or str(shopee.get("access_token") or "").strip()
    shop_value = shop_value or str(shopee.get("shop_id") or "").strip()

    token_file_value = os.getenv("SHOPEE_TOKEN_FILE", "").strip() or args.token_file or ""
    token_file = Path(token_file_value).expanduser() if token_file_value else DEFAULT_TOKEN_FILE
    if (not access_token or not shop_value) and token_file.exists():
        try:
            saved = load_json(token_file)
        except SystemExit:
            saved = {}
        if isinstance(saved, dict):
            access_token = access_token or str(saved.get("access_token", "")).strip()
            shop_value = shop_value or str(saved.get("shop_id", "")).strip()

    if not access_token or not shop_value:
        raise SystemExit("缺少 access_token 或 shop_id。")
    return access_token, parse_int(shop_value, "shop_id")


def load_partner_credentials(args: argparse.Namespace) -> tuple[str, str]:
    partner_id = os.getenv("SHOPEE_PARTNER_ID", "").strip() or args.partner_id or ""
    partner_key = os.getenv("SHOPEE_PARTNER_KEY", "").strip() or args.partner_key or ""
    config = getattr(args, "_config", {})
    shopee = config.get("shopee") or {}
    partner_id = partner_id or str(shopee.get("partner_id") or "").strip()
    partner_key = partner_key or str(shopee.get("partner_key") or "").strip()
    if not partner_id or not partner_key:
        raise SystemExit("缺少 SHOPEE_PARTNER_ID 或 SHOPEE_PARTNER_KEY。")
    return partner_id, partner_key


def refresh_configured_shopee_token(args: argparse.Namespace) -> None:
    """Refresh configured live credentials before a direct execute run."""
    config = getattr(args, "_config", {})
    shopee = config.get("shopee") or {}
    refresh_token = str(shopee.get("refresh_token") or "").strip()
    explicit_override = any(
        os.getenv(name, "").strip()
        for name in (
            "SHOPEE_PARTNER_ID", "SHOPEE_PARTNER_KEY",
            "SHOPEE_ACCESS_TOKEN", "SHOPEE_SHOP_ID",
        )
    ) or bool(args.partner_id or args.partner_key or args.access_token or args.shop_id)
    if not refresh_token or explicit_override:
        return

    partner_id = str(shopee.get("partner_id") or "").strip()
    partner_key = str(shopee.get("partner_key") or "").strip()
    shop_id = str(shopee.get("shop_id") or "").strip()
    if not all((partner_id, partner_key, shop_id)):
        raise SystemExit("配置缺少 Shopee 刷新 token 所需的 partner_id、partner_key 或 shop_id")

    timestamp = int(time.time())
    signature = hmac.new(
        partner_key.encode("utf-8"),
        f"{partner_id}{SHOPEE_TOKEN_PATH}{timestamp}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    params = {
        "partner_id": partner_id,
        "timestamp": timestamp,
        "sign": signature,
    }
    body = {
        "refresh_token": refresh_token,
        "partner_id": int(partner_id),
        "shop_id": int(shop_id),
    }
    result = request_json(
        "POST",
        api_host(str(shopee.get("host") or DEFAULT_HOST)),
        SHOPEE_TOKEN_PATH,
        params,
        body,
    )
    new_access_token = str(result.get("access_token") or "").strip()
    if not new_access_token:
        raise SystemExit("Shopee access_token 刷新没有返回 access_token")
    shopee["access_token"] = new_access_token
    shopee["refresh_token"] = str(result.get("refresh_token") or refresh_token).strip()
    config_path = Path(getattr(args, "_config_path", DEFAULT_CONFIG))
    save_json(config_path, config)
    save_json(DEFAULT_TOKEN_FILE, {
        "access_token": shopee["access_token"],
        "refresh_token": shopee["refresh_token"],
        "shop_id": shop_id,
        "partner_id": partner_id,
    })


def load_image_map(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if not isinstance(payload, list):
        raise SystemExit(f"图片映射文件格式不正确: {path}")
    result: list[dict[str, Any]] = []
    for entry in payload:
        if isinstance(entry, dict) and entry.get("path") and entry.get("image_id") and entry.get("kind"):
            result.append(entry)
    return result


def build_image_lookup(entries: list[dict[str, Any]], kind: str) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for entry in entries:
        if entry.get("kind") != kind:
            continue
        path = Path(str(entry["path"]))
        label = decode_asset_label(path.stem)
        lookup.setdefault(label, str(entry["image_id"]))
    return lookup


def pick_image(lookup: dict[str, str], *labels: str) -> str | None:
    for label in labels:
        if label in lookup:
            return lookup[label]
    return None


def build_product_image_ids(entries: list[dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
    lookup = build_image_lookup(entries, "product")
    order = [
        ("主图",),
        ("背景图", "合规白底主图"),
        ("背景图1",),
        ("多场景图",),
        ("细节特写图1",),
        ("买点解析图", "卖点解析图"),
        ("一",),
        ("二",),
        ("三",),
    ]
    picked: list[str] = []
    picked_ids: set[str] = set()
    for labels in order:
        image_id = pick_image(lookup, *labels)
        if image_id:
            picked.append(image_id)
            picked_ids.add(image_id)
    if not picked:
        raise SystemExit("没有找到可用的商品图。")
    return picked[:9], lookup


def build_variation_options(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    lookup = build_image_lookup(entries, "sku")
    options: list[dict[str, str]] = []
    for label, image_id in lookup.items():
        options.append({
            "label": translate_color(label),
            "image_id": image_id,
        })
    if not options:
        raise SystemExit("??????????? SKU ???")
    return options


def parse_size_options(raw: str) -> list[str]:
    options = [item.strip() for item in raw.split(",") if item.strip()]
    return options


def parse_attributes(values: list[str]) -> list[dict[str, Any]]:
    attributes_by_id: dict[int, list[dict[str, Any]]] = {}
    for raw in values:
        if "=" not in raw:
            raise SystemExit(f"属性格式必须是 attribute_id=value_id: {raw}")
        left, right = raw.split("=", 1)
        attribute_id = parse_int(left.strip(), "attribute_id")
        value_parts = right.split("|", 1)
        value_id = parse_int(value_parts[0].strip(), "value_id")
        value = {"value_id": value_id}
        if len(value_parts) == 2 and value_parts[1].strip():
            if value_id != 0:
                raise SystemExit(
                    "只有 value_id=0 才能附加自定义 original_value_name: "
                    f"{raw}"
                )
            value["original_value_name"] = value_parts[1].strip()
        existing = attributes_by_id.setdefault(attribute_id, [])
        key = (value["value_id"], value.get("original_value_name", ""))
        if key not in {
            (item["value_id"], item.get("original_value_name", ""))
            for item in existing
        }:
            existing.append(value)
    return [
        {"attribute_id": attribute_id, "attribute_value_list": value_list}
        for attribute_id, value_list in attributes_by_id.items()
    ]


def merge_attributes(live_attributes: Any,
                     requested_attributes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge requested attribute values while keeping untouched live attributes."""
    merged: dict[int, dict[str, Any]] = {}
    if isinstance(live_attributes, list):
        for attribute in live_attributes:
            if not isinstance(attribute, dict) or attribute.get("attribute_id") is None:
                continue
            attribute_id = int(attribute["attribute_id"])
            value_list = attribute.get("attribute_value_list") or []
            values: list[dict[str, Any]] = []
            if isinstance(value_list, list):
                for value in value_list:
                    if isinstance(value, dict) and value.get("value_id") is not None:
                        values.append({"value_id": int(value["value_id"])})
            if values:
                merged[attribute_id] = {
                    "attribute_id": attribute_id,
                    "attribute_value_list": values,
                }

    requested_by_id: dict[int, list[dict[str, Any]]] = {}
    for attribute in requested_attributes:
        attribute_id = int(attribute["attribute_id"])
        requested_by_id.setdefault(attribute_id, []).extend(
            value for value in attribute.get("attribute_value_list", [])
            if isinstance(value, dict) and value.get("value_id") is not None
        )
    for attribute_id, raw_values in requested_by_id.items():
        requested_values: list[dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        for value in raw_values:
            normalized = {"value_id": int(value["value_id"])}
            if value.get("original_value_name"):
                normalized["original_value_name"] = str(value["original_value_name"])
            key = (normalized["value_id"], normalized.get("original_value_name", ""))
            if key not in seen:
                requested_values.append(normalized)
                seen.add(key)
        # An explicitly requested attribute replaces its old values. This is
        # important for multi-select attributes and for correcting a prior run.
        merged[attribute_id] = {
            "attribute_id": attribute_id,
            "attribute_value_list": requested_values,
        }
    return list(merged.values())


def build_attributes_update_body(item: dict[str, Any], item_id: int,
                                 requested_attributes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "attribute_list": merge_attributes(
            item.get("attribute_list"), requested_attributes
        ),
    }


def parse_wholesale(values: list[str]) -> list[dict[str, Any]]:
    tiers: list[dict[str, Any]] = []
    for raw in values:
        parts = raw.split(":")
        if len(parts) != 3:
            raise SystemExit(f"批发格式必须是 min:max:price，收到: {raw}")
        tiers.append({
            "min_count": parse_int(parts[0].strip(), "min_count"),
            "max_count": parse_int(parts[1].strip(), "max_count"),
            "unit_price": parse_float(parts[2].strip(), "unit_price"),
        })
    return tiers


def build_description_block(text: str, image_id: str | None) -> dict[str, Any]:
    field_list: list[dict[str, Any]] = [{"field_type": "text", "text": text}]
    if image_id:
        field_list.append({"field_type": "image", "image_info": {"image_id": image_id}})
    return {"extended_description": {"field_list": field_list}}


def build_size_chart_info(args: argparse.Namespace, product_lookup: dict[str, str]) -> dict[str, Any]:
    image_id = getattr(args, "size_chart_image_id", "") or product_lookup.get("三", "")
    image_id = image_id.strip()
    if image_id:
        return {"size_chart": image_id}
    if args.size_chart_id:
        return {"size_chart_id": args.size_chart_id}
    return {}


def build_existing_update_body(item: dict[str, Any], item_id: int,
                               size_chart_info: dict[str, Any],
                               description_text: str, weight: float,
                               package_width: int, package_length: int,
                               package_height: int, logistic_id: int,
                               size_id: int, shipping_fee: float,
                               is_free: bool) -> dict[str, Any]:
    """Update only the requested editable fields; omit global item SKU."""
    live_logistics = item.get("logistic_info") or []
    logistic_info: list[dict[str, Any]] = []
    if isinstance(live_logistics, list) and live_logistics:
        for entry in live_logistics:
            if not isinstance(entry, dict):
                continue
            current_id = int(entry.get("logistic_id") or 0)
            logistic_info.append({
                "logistic_id": current_id,
                "size_id": int(entry.get("size_id") or size_id),
                "shipping_fee": shipping_fee if current_id == logistic_id else float(
                    entry.get("estimated_shipping_fee")
                    or entry.get("shipping_fee")
                    or shipping_fee
                ),
                "enabled": True if current_id == logistic_id else bool(entry.get("enabled")),
                "is_free": False if current_id == logistic_id else bool(entry.get("is_free")),
            })
    else:
        logistic_info = [
            {
                "logistic_id": logistic_id,
                "size_id": size_id,
                "shipping_fee": shipping_fee,
                "enabled": True,
                "is_free": is_free,
            }
        ]

    body: dict[str, Any] = {
        "item_id": item_id,
        "description": description_text,
        "weight": weight,
        "dimension": {
            "package_width": package_width,
            "package_length": package_length,
            "package_height": package_height,
        },
        "logistic_info": logistic_info,
        "description_type": "extended",
        "description_info": build_description_block(
            description_text, get_description_image_id(item)
        ),
    }
    if size_chart_info:
        body["size_chart_info"] = size_chart_info
    return body


def build_logistics_update_body(item: dict[str, Any], item_id: int,
                                logistic_id: int, size_id: int,
                                shipping_fee: float, is_free: bool) -> dict[str, Any]:
    live_logistics = item.get("logistic_info") or []
    logistic_info: list[dict[str, Any]] = []
    if isinstance(live_logistics, list) and live_logistics:
        for entry in live_logistics:
            if not isinstance(entry, dict):
                continue
            current_id = int(entry.get("logistic_id") or 0)
            logistic_info.append({
                "logistic_id": current_id,
                "size_id": int(entry.get("size_id") or size_id),
                "shipping_fee": shipping_fee if current_id == logistic_id else float(
                    entry.get("estimated_shipping_fee")
                    or entry.get("shipping_fee")
                    or shipping_fee
                ),
                "enabled": True if current_id == logistic_id else bool(entry.get("enabled")),
                "is_free": False if current_id == logistic_id else bool(entry.get("is_free")),
            })
    else:
        logistic_info = [
            {
                "logistic_id": logistic_id,
                "size_id": size_id,
                "shipping_fee": shipping_fee,
                "enabled": True,
                "is_free": is_free,
            }
        ]
    return {"item_id": item_id, "logistic_info": logistic_info}


def get_description_image_id(item: dict[str, Any]) -> str | None:
    description_info = item.get("description_info")
    if not isinstance(description_info, dict):
        return None
    fields = ((description_info.get("extended_description") or {}).get("field_list") or [])
    for field in fields:
        if not isinstance(field, dict) or field.get("field_type") != "image":
            continue
        image_info = field.get("image_info") or {}
        if isinstance(image_info, dict) and image_info.get("image_id"):
            return str(image_info["image_id"])
    return None


def chunks(values: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def build_model_sku(model: dict[str, Any], args: argparse.Namespace,
                    tier_variation: list[dict[str, Any]]) -> str:
    """Build the warehouse SKU from prefix, size code, color code, and suffix."""
    tier_index = model.get("tier_index") or []
    if len(tier_index) < 2:
        raise SystemExit(f"model {model.get('model_id')} has an invalid tier_index")
    color_options = tier_variation[0].get("option_list") or []
    size_options = tier_variation[1].get("option_list") or []
    color_index, size_index = int(tier_index[0]), int(tier_index[1])
    if color_index >= len(color_options) or size_index >= len(size_options):
        raise SystemExit(f"model {model.get('model_id')} tier_index is out of range")
    color = str(color_options[color_index].get("option", ""))
    size = str(size_options[size_index].get("option", ""))
    return build_color_sku(color, size, args)


def build_add_item_body(args: argparse.Namespace, product_images: list[str],
                        description_text: str, description_image_id: str | None,
                        attributes: list[dict[str, Any]], wholesale: list[dict[str, Any]],
                        size_chart_info: dict[str, Any]) -> dict[str, Any]:
    width, length, height = args.package_width, args.package_length, args.package_height
    body: dict[str, Any] = {
        "original_price": args.original_price,
        "description": description_text,
        "weight": args.weight,
        "item_name": args.item_name,
        "item_status": "UNLIST",
        "dimension": {
            "package_height": height,
            "package_length": length,
            "package_width": width,
        },
        "logistic_info": [
            {
                "size_id": args.size_id,
                "shipping_fee": args.shipping_fee,
                "enabled": True,
                "logistic_id": args.logistic_id,
                "is_free": args.is_free,
            }
        ],
        "attribute_list": attributes,
        "category_id": args.category_id,
        "image": {"image_id_list": product_images},
        "pre_order": {
            "is_pre_order": args.pre_order,
            "days_to_ship": args.days_to_ship,
        },
        "condition": args.condition,
        "wholesale": wholesale,
        "video_upload_id": args.video_upload_id,
        "brand": {
            "brand_id": args.brand_id,
            "original_brand_name": args.brand_name,
        },
        "item_dangerous": args.item_dangerous,
        "tax_info": {
            "ncm": args.tax_ncm,
            "same_state_cfop": args.tax_same_state_cfop,
            "diff_state_cfop": args.tax_diff_state_cfop,
            "csosn": args.tax_csosn,
            "origin": args.tax_origin,
            "cest": args.tax_cest,
            "measure_unit": args.tax_measure_unit,
            "invoice_option": args.tax_invoice_option,
            "vat_rate": args.tax_vat_rate,
        },
        "complaint_policy": {
            "warranty_time": args.warranty_time,
            "exclude_entrepreneur_warranty": args.exclude_entrepreneur_warranty,
            "complaint_address_id": args.complaint_address_id,
            "additional_information": args.complaint_additional_information,
        },
        "description_info": build_description_block(description_text, description_image_id),
        "description_type": "extended",
        "seller_stock": [
            {
                "location_id": args.location_id,
                "stock": args.stock,
            }
        ],
    }
    if size_chart_info:
        body["size_chart_info"] = size_chart_info
    return body


def build_tier_variation_body(args: argparse.Namespace, item_id: int,
                              color_options: list[dict[str, str]],
                              size_options: list[str]) -> dict[str, Any]:
    tier_variation = [
        {
            "name": args.tier_name,
            "option_list": [
                {
                    "option": option["label"],
                    "image": {"image_id": option["image_id"]},
                }
                for option in color_options
            ],
        },
        {
            "name": args.size_tier_name,
            "option_list": [{"option": size} for size in size_options],
        },
    ]

    model_list: list[dict[str, Any]] = []
    for color_index, color_option in enumerate(color_options):
        for size_index, size_option in enumerate(size_options):
            model_list.append({
                "tier_index": [color_index, size_index],
                "model_sku": build_color_sku(color_option["label"], size_option, args),
                "original_price": args.original_price,
                "seller_stock": [
                    {
                        "location_id": args.location_id,
                        "stock": args.variation_stock,
                    }
                ],
            })

    return {
        "item_id": item_id,
        "tier_variation": tier_variation,
        "model": model_list,
    }


def build_update_tier_variation_body(item_id: int, model_values: list[dict[str, Any]],
                                     live_tier_variation: list[dict[str, Any]],
                                     size_options: list[str]) -> dict[str, Any]:
    """Preserve current combinations while changing only tier option labels."""
    if len(live_tier_variation) < 2:
        raise SystemExit("get_model_list did not return Color and Size tier variations")

    standardise_tier_variation: list[dict[str, Any]] = []
    for tier_index, tier in enumerate(live_tier_variation):
        if not isinstance(tier, dict):
            raise SystemExit("get_model_list returned an invalid tier variation")
        tier_name = str(tier.get("name") or tier.get("variation_name") or "")
        raw_options = tier.get("option_list") or tier.get("variation_option_list") or []
        option_list: list[dict[str, Any]] = []
        for option_index, option in enumerate(raw_options):
            if not isinstance(option, dict):
                raise SystemExit("get_model_list returned an invalid tier option")
            if tier_index == 1 and option_index < len(size_options):
                option_name = size_options[option_index]
            else:
                option_name = str(option.get("option") or option.get("variation_option_name") or "")
            updated_option: dict[str, Any] = {
                "variation_option_id": int(option.get("variation_option_id") or 0),
                "variation_option_name": option_name,
            }
            image_id = (option.get("image") or {}).get("image_id") if isinstance(option.get("image"), dict) else option.get("image_id")
            if image_id:
                updated_option["image_id"] = str(image_id)
            option_list.append(updated_option)
        standardise_tier_variation.append({
            "variation_id": int(tier.get("variation_id") or 0),
            "variation_name": tier_name,
            "variation_option_list": option_list,
        })

    model_list = []
    for model in model_values:
        if not isinstance(model, dict) or model.get("model_id") is None:
            continue
        model_list.append({
            "model_id": int(model["model_id"]),
            "tier_index": model.get("tier_index") or [],
        })
    if not model_list:
        raise SystemExit("get_model_list did not return any model_id")

    return {
        "item_id": item_id,
        "model_list": model_list,
        "standardise_tier_variation": standardise_tier_variation,
    }


def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or execute a Shopee draft product workflow.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Credential/config JSON path")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--partner-id")
    parser.add_argument("--partner-key")
    parser.add_argument("--access-token")
    parser.add_argument("--shop-id")
    parser.add_argument("--token-file")
    parser.add_argument("--description-file", default="")
    parser.add_argument("--description-text", default=DEFAULT_DESCRIPTION_TEXT)
    parser.add_argument("--image-map", default=str(DEFAULT_IMAGE_MAP))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--item-id", type=int, help="Update an existing item instead of creating a new one")
    parser.add_argument(
        "--update-tier-options",
        default="",
        help="Only rename existing tier options for --item-id, e.g. S,M,L,XL,XXL,XXXL",
    )
    parser.add_argument(
        "--update-logistics-only",
        action="store_true",
        help="Only update logistics for --item-id and keep all other fields unchanged",
    )
    parser.add_argument(
        "--update-attributes-only",
        action="store_true",
        help="Only update attribute_list for --item-id and keep all other fields unchanged",
    )
    parser.add_argument("--execute", action="store_true")

    parser.add_argument("--category-id", type=int, default=DEFAULT_CATEGORY_ID)
    parser.add_argument("--item-name", default="")
    parser.add_argument("--sku-prefix", default="")
    parser.add_argument("--sku-suffix", default="")
    parser.add_argument("--brand-name", default="")
    parser.add_argument("--brand-id", type=int, default=None)
    parser.add_argument("--currency", default="")
    parser.add_argument("--current-price", type=float, default=DEFAULT_CURRENT_PRICE)
    parser.add_argument("--original-price", type=float, default=DEFAULT_ORIGINAL_PRICE)
    parser.add_argument("--weight", type=float, default=DEFAULT_WEIGHT)
    parser.add_argument("--stock", type=int, default=DEFAULT_STOCK)
    parser.add_argument("--variation-stock", type=int, default=DEFAULT_STOCK)
    parser.add_argument("--location-id", default=DEFAULT_LOCATION_ID)
    parser.add_argument("--logistic-id", type=int, default=DEFAULT_LOGISTIC_ID)
    parser.add_argument("--size-id", type=int, default=DEFAULT_SIZE_ID)
    parser.add_argument("--size-chart-id", type=int, default=0)
    parser.add_argument(
        "--size-chart-image-id",
        default="",
        help="Optional size-chart image ID; when omitted, use the mapped 三 image if available",
    )
    parser.add_argument("--days-to-ship", type=int, default=DEFAULT_DAYS_TO_SHIP)
    parser.add_argument("--pre-order", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--shipping-fee", type=float, default=DEFAULT_SHIPPING_FEE)
    parser.add_argument("--is-free", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--package-width", type=int, default=DEFAULT_PACKAGE[0])
    parser.add_argument("--package-length", type=int, default=DEFAULT_PACKAGE[1])
    parser.add_argument("--package-height", type=int, default=DEFAULT_PACKAGE[2])
    parser.add_argument("--item-dangerous", type=int, default=None)
    parser.add_argument("--tier-name", default="Color")
    parser.add_argument("--size-tier-name", default="Size")
    parser.add_argument("--size-options", default=",".join(DEFAULT_SIZE_OPTIONS))
    parser.add_argument("--condition", default="")
    parser.add_argument("--video-upload-id", action="append", default=[])
    parser.add_argument(
        "--video-file",
        default="",
        help="Upload a local mp4 and update video_upload_id for an existing --item-id only",
    )
    parser.add_argument("--attribute", action="append", default=[], help="Repeatable attribute_id=value_id pairs")
    parser.add_argument("--wholesale", action="append", default=[], help="Repeatable min:max:price tiers")
    parser.add_argument("--warranty-time", default="")
    parser.add_argument("--exclude-entrepreneur-warranty", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--complaint-address-id", type=int, default=None)
    parser.add_argument("--complaint-additional-information", default="-")
    parser.add_argument("--tax-ncm", default="-")
    parser.add_argument("--tax-same-state-cfop", default="-")
    parser.add_argument("--tax-diff-state-cfop", default="-")
    parser.add_argument("--tax-csosn", default="-")
    parser.add_argument("--tax-origin", default="-")
    parser.add_argument("--tax-cest", default="-")
    parser.add_argument("--tax-measure-unit", default="-")
    parser.add_argument("--tax-invoice-option", default="-")
    parser.add_argument("--tax-vat-rate", default="-")
    return parser.parse_args()


def main() -> None:
    args = build_args()
    args._config_path = str(Path(args.config).expanduser())
    args._config = load_optional_config(Path(args._config_path))
    config_defaults = (args._config.get("defaults") or {}) if isinstance(args._config, dict) else {}
    if not args.attribute and isinstance(config_defaults.get("attributes"), list):
        args.attribute = [str(attribute) for attribute in config_defaults["attributes"]]
    if args.video_file:
        validate_video_file(Path(args.video_file).expanduser())
    if args.execute:
        refresh_configured_shopee_token(args)
    host = api_host(args.host)
    description_path = Path(args.description_file).expanduser() if args.description_file else None
    image_map_path = Path(args.image_map).expanduser()
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.video_file:
        update_existing_item_video(args, host, output_dir)
        return

    # Tier-option-only updates do not need local product assets.
    if args.execute and args.update_tier_options:
        if args.item_id is None:
            raise SystemExit("--update-tier-options requires --item-id")
        partner_id, partner_key = load_partner_credentials(args)
        access_token, shop_id = load_access_credentials(args)
        requested_sizes = parse_size_options(args.update_tier_options)
        model_params = common_params(partner_id, partner_key, MODEL_LIST_PATH, access_token, shop_id)
        model_params["item_id"] = args.item_id
        model_result = request_json("GET", host, MODEL_LIST_PATH, model_params)
        model_response = model_result.get("response") or {}
        model_values = model_response.get("model") or []
        live_tier_variation = model_response.get("tier_variation") or []
        tier_body = build_update_tier_variation_body(
            args.item_id, model_values, live_tier_variation, requested_sizes
        )
        tier_params = common_params(
            partner_id, partner_key, UPDATE_TIER_VARIATION_PATH, access_token, shop_id
        )
        tier_result = request_json(
            "POST", host, UPDATE_TIER_VARIATION_PATH, tier_params, tier_body
        )
        save_json(output_dir / "shopee_update_tier_variation_body.json", tier_body)
        save_json(output_dir / "shopee_update_tier_variation_result.json", {
            "request": tier_body,
            "response": tier_result,
        })
        print(json.dumps({
            "item_id": args.item_id,
            "updated_size_options": requested_sizes,
            "model_count": len(tier_body["model_list"]),
            "saved_to": str(output_dir / "shopee_update_tier_variation_result.json"),
        }, ensure_ascii=False, indent=2))
        return

    if args.execute and args.item_id is not None and args.update_logistics_only:
        partner_id, partner_key = load_partner_credentials(args)
        access_token, shop_id = load_access_credentials(args)
        info_params = common_params(partner_id, partner_key, PRODUCT_INFO_PATH, access_token, shop_id)
        info_params["item_id_list"] = str(args.item_id)
        info_result = request_json("GET", host, PRODUCT_INFO_PATH, info_params)
        item_list = (info_result.get("response") or {}).get("item_list") or []
        if not item_list or not isinstance(item_list[0], dict):
            raise SystemExit(f"get_item_base_info did not return item {args.item_id}")
        live_item = item_list[0]
        update_body = build_logistics_update_body(
            live_item,
            args.item_id,
            args.logistic_id,
            args.size_id,
            args.shipping_fee,
            args.is_free,
        )
        update_params = common_params(partner_id, partner_key, UPDATE_ITEM_PATH, access_token, shop_id)
        update_result = request_json("POST", host, UPDATE_ITEM_PATH, update_params, update_body)
        save_json(output_dir / "shopee_update_logistics_body.json", update_body)
        save_json(output_dir / "shopee_update_logistics_result.json", {
            "request": update_body,
            "response": update_result,
        })
        print(json.dumps({
            "item_id": args.item_id,
            "shipping_fee": args.shipping_fee,
            "is_free": args.is_free,
            "saved_to": str(output_dir / "shopee_update_logistics_result.json"),
        }, ensure_ascii=False, indent=2))
        return

    if args.execute and args.item_id is not None and args.update_attributes_only:
        if not args.attribute:
            raise SystemExit("--update-attributes-only requires at least one --attribute attribute_id=value_id")
        partner_id, partner_key = load_partner_credentials(args)
        access_token, shop_id = load_access_credentials(args)

        info_params = common_params(partner_id, partner_key, PRODUCT_INFO_PATH, access_token, shop_id)
        info_params["item_id_list"] = str(args.item_id)
        info_result = request_json("GET", host, PRODUCT_INFO_PATH, info_params)
        item_list = (info_result.get("response") or {}).get("item_list") or []
        if not item_list or not isinstance(item_list[0], dict):
            raise SystemExit(f"get_item_base_info did not return item {args.item_id}")
        live_item = item_list[0]
        if str(live_item.get("item_status", "")).upper() != "UNLIST":
            raise SystemExit(
                f"为避免误上架，属性更新仅允许 UNLIST 商品；当前状态为 {live_item.get('item_status')!r}"
            )

        requested_attributes = parse_attributes(args.attribute)
        update_body = build_attributes_update_body(
            live_item, args.item_id, requested_attributes
        )
        update_params = common_params(partner_id, partner_key, UPDATE_ITEM_PATH, access_token, shop_id)
        update_result = request_json("POST", host, UPDATE_ITEM_PATH, update_params, update_body)

        verify_params = common_params(partner_id, partner_key, PRODUCT_INFO_PATH, access_token, shop_id)
        verify_params["item_id_list"] = str(args.item_id)
        verify_result = request_json("GET", host, PRODUCT_INFO_PATH, verify_params)
        verify_items = (verify_result.get("response") or {}).get("item_list") or []
        verified_item = verify_items[0] if verify_items and isinstance(verify_items[0], dict) else {}
        if str(verified_item.get("item_status", "")).upper() != "UNLIST":
            raise SystemExit(
                f"属性更新后商品状态异常，已停止: {verified_item.get('item_status')!r}"
            )

        attributes_body_path = output_dir / "shopee_update_attributes_body.json"
        attributes_result_path = output_dir / "shopee_update_attributes_result.json"
        save_json(attributes_body_path, update_body)
        save_json(attributes_result_path, {
            "get_item_base_info_before": info_result,
            "update_item_request": update_body,
            "update_item_response": update_result,
            "get_item_base_info_after": verify_result,
        })
        print(json.dumps({
            "item_id": args.item_id,
            "updated_attribute_count": len(update_body["attribute_list"]),
            "item_status": verified_item.get("item_status"),
            "saved_to": str(attributes_result_path),
        }, ensure_ascii=False, indent=2))
        return

    if not args.execute and args.item_id is not None and args.update_attributes_only:
        if not args.attribute:
            raise SystemExit("--update-attributes-only requires at least one --attribute attribute_id=value_id")
        preview_path = output_dir / "shopee_update_attributes_preview.json"
        preview = {
            "mode": "dry-run",
            "item_id": args.item_id,
            "update_attributes_only": True,
            "requested_attributes": parse_attributes(args.attribute),
            "note": "Live execution will read the existing item, preserve other attributes, and submit only item_id and attribute_list.",
        }
        save_json(preview_path, preview)
        print(json.dumps({
            "mode": "dry-run",
            "preview_file": str(preview_path),
        }, ensure_ascii=False, indent=2))
        return

    description_text = normalize_text(args.description_text)
    if args.description_file:
        description_text = normalize_text(read_text_auto(description_path))
    required_values = (
        ("商品名称/产品名称", args.item_name),
        ("商品描述", description_text),
        ("类别 ID", args.category_id),
        ("SKU 前缀", args.sku_prefix),
        ("SKU 后缀", args.sku_suffix),
        ("品牌名称", args.brand_name),
        ("品牌 ID", args.brand_id),
        ("价格", args.current_price),
        ("原价", args.original_price),
        ("重量", args.weight),
        ("库存", args.stock),
        ("变体库存", args.variation_stock),
        ("库存地点 ID", args.location_id),
        ("物流 ID", args.logistic_id),
        ("币种", args.currency),
        ("发货天数", args.days_to_ship),
        ("运费", args.shipping_fee),
        ("包裹宽度", args.package_width),
        ("包裹长度", args.package_length),
        ("包裹高度", args.package_height),
        ("尺码选项", args.size_options),
        ("成色/condition", args.condition),
        ("是否免运费", args.is_free),
        ("是否预售", args.pre_order),
        ("商品危险品分类", args.item_dangerous),
    )
    missing_required = [label for label, value in required_values if value is None or value == "" or value == []]
    if missing_required:
        raise SystemExit("缺少本次上架所需且尚未确认的字段：" + "、".join(missing_required) + "。请先向用户确认后再继续。")
    image_entries = load_image_map(image_map_path)
    product_images, product_lookup = build_product_image_ids(image_entries)
    description_lookup = build_image_lookup(image_entries, "description")
    variation_options = build_variation_options(image_entries)
    size_options = parse_size_options(args.size_options)
    size_chart_info = build_size_chart_info(args, product_lookup)
    # The KV image is optional. The description remains valid with text only.
    description_image_id = description_lookup.get("KV细节图") or product_lookup.get("KV细节图")

    attributes = parse_attributes(args.attribute)
    wholesale = parse_wholesale(args.wholesale)
    if not wholesale:
        wholesale = []

    add_item_body = build_add_item_body(
        args=args,
        product_images=product_images,
        description_text=description_text,
        description_image_id=description_image_id,
        attributes=attributes,
        wholesale=wholesale,
        size_chart_info=size_chart_info,
    )
    add_item_payload_path = output_dir / "shopee_add_item_body.json"
    variation_payload_path = output_dir / "shopee_init_tier_variation_body.json"
    save_json(add_item_payload_path, add_item_body)

    tier_preview = build_tier_variation_body(args, 0, variation_options, size_options)
    save_json(variation_payload_path, tier_preview)

    preview = {
        "host": host,
        "description_file": str(description_path) if description_path else None,
        "image_map": str(image_map_path),
        "product_images": product_images,
        "size_chart_info": size_chart_info,
        "variation_options": {
            "color": [option["label"] for option in variation_options],
            "size": size_options,
        },
        "add_item_body": add_item_body,
        "tier_variation_body": tier_preview,
    }

    if not args.execute:
        save_json(output_dir / "shopee_draft_preview.json", preview)
        print(json.dumps({
            "mode": "dry-run",
            "preview_file": str(output_dir / "shopee_draft_preview.json"),
            "add_item_body": str(add_item_payload_path),
            "variation_body": str(variation_payload_path),
        }, ensure_ascii=False, indent=2))
        return

    partner_id, partner_key = load_partner_credentials(args)
    access_token, shop_id = load_access_credentials(args)
    if args.item_id is None:
        add_params = common_params(partner_id, partner_key, ADD_ITEM_PATH, access_token, shop_id)
        add_result = request_json("POST", host, ADD_ITEM_PATH, add_params, add_item_body)
        response = add_result.get("response") or {}
        item_id = response.get("item_id")
        if item_id is None:
            raise SystemExit(f"add_item ??? item_id: {json.dumps(add_result, ensure_ascii=False)}")
        item_id_int = parse_int(str(item_id), "item_id")
    else:
        item_id_int = args.item_id
        add_result = {
            "skipped": True,
            "reason": "item_id provided, existing item will be updated",
            "item_id": item_id_int,
        }

    if args.item_id is None:
        tier_body = build_tier_variation_body(args, item_id_int, variation_options, size_options)
        save_json(variation_payload_path, tier_body)
        tier_result = init_tier_variation_with_lock_retry(
            host, partner_id, partner_key, access_token, shop_id, tier_body
        )
        final_payload = {
            "add_item_request": add_item_body,
            "add_item_response": add_result,
            "init_tier_variation_request": tier_body,
            "init_tier_variation_response": tier_result,
        }
    else:
        # Existing items already have their tier structure. Re-initializing it
        # is rejected when the Color/Size levels are unchanged.
        info_params = common_params(partner_id, partner_key, PRODUCT_INFO_PATH, access_token, shop_id)
        # The live gateway accepts repeated/scalar item_id_list query values;
        # bracketed JSON is treated as a literal uint64 and rejected.
        info_params["item_id_list"] = str(item_id_int)
        info_result = request_json("GET", host, PRODUCT_INFO_PATH, info_params)
        item_list = (info_result.get("response") or {}).get("item_list") or []
        if not item_list or not isinstance(item_list[0], dict):
            raise SystemExit(f"get_item_base_info did not return item {item_id_int}")
        live_item = item_list[0]

        update_body = build_existing_update_body(
            live_item,
            item_id_int,
            size_chart_info,
            description_text,
            args.weight,
            args.package_width,
            args.package_length,
            args.package_height,
            args.logistic_id,
            args.size_id,
            args.shipping_fee,
            args.is_free,
        )
        update_params = common_params(partner_id, partner_key, UPDATE_ITEM_PATH, access_token, shop_id)
        update_result = request_json("POST", host, UPDATE_ITEM_PATH, update_params, update_body)

        model_params = common_params(partner_id, partner_key, MODEL_LIST_PATH, access_token, shop_id)
        model_params["item_id"] = item_id_int
        model_result = request_json("GET", host, MODEL_LIST_PATH, model_params)
        model_values = (model_result.get("response") or {}).get("model") or []
        models = [model for model in model_values if isinstance(model, dict) and model.get("model_id") is not None]
        if not models:
            raise SystemExit("get_model_list did not return any model_id")

        live_tier_variation = (model_result.get("response") or {}).get("tier_variation") or []
        if len(live_tier_variation) < 2:
            raise SystemExit("get_model_list did not return Color and Size tier variations")
        model_sku_updates = [
            {
                "model_id": int(model["model_id"]),
                "model_sku": build_model_sku(model, args, live_tier_variation),
            }
            for model in models
        ]
        model_update_results: list[dict[str, Any]] = []
        for model_list in chunks(model_sku_updates, 50):
            model_update_body = {"item_id": item_id_int, "model": model_list}
            model_update_params = common_params(partner_id, partner_key, UPDATE_MODEL_PATH, access_token, shop_id)
            model_update_results.append(
                request_json("POST", host, UPDATE_MODEL_PATH, model_update_params, model_update_body)
            )

        price_batches = chunks([
            {"model_id": int(model["model_id"]), "original_price": args.current_price}
            for model in models
        ], 50)
        price_results: list[dict[str, Any]] = []
        for price_list in price_batches:
            price_body = {"item_id": item_id_int, "price_list": price_list}
            price_params = common_params(partner_id, partner_key, UPDATE_PRICE_PATH, access_token, shop_id)
            price_results.append(request_json("POST", host, UPDATE_PRICE_PATH, price_params, price_body))

        stock_batches = chunks([
            {
                "model_id": int(model["model_id"]),
                "seller_stock": [{"location_id": args.location_id, "stock": args.variation_stock}],
            }
            for model in models
        ], 50)
        stock_results: list[dict[str, Any]] = []
        for stock_list in stock_batches:
            stock_body = {"item_id": item_id_int, "stock_list": stock_list}
            stock_params = common_params(partner_id, partner_key, UPDATE_STOCK_PATH, access_token, shop_id)
            stock_results.append(request_json("POST", host, UPDATE_STOCK_PATH, stock_params, stock_body))

        tier_body = {
            "item_id": item_id_int,
            "model_count": len(models),
            "model_ids": [int(model["model_id"]) for model in models],
        }
        save_json(variation_payload_path, tier_body)
        final_payload = {
            "add_item_request": add_item_body,
            "add_item_response": add_result,
            "get_item_base_info_response": info_result,
            "update_item_request": update_body,
            "update_item_response": update_result,
            "get_model_list_response": model_result,
            "update_model_requests": model_sku_updates,
            "update_model_responses": model_update_results,
            "update_price_responses": price_results,
            "update_stock_responses": stock_results,
        }
    save_json(output_dir / "shopee_draft_result.json", final_payload)
    print(json.dumps({
        "item_id": item_id_int,
        "saved_to": str(output_dir / "shopee_draft_result.json"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
