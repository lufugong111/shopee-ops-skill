#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from create_shopee_draft import (
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT_DIR,
    api_host,
    common_params,
    load_json,
    refresh_configured_shopee_token,
    save_json,
)

UPLOAD_IMAGE_PATH = "/api/v2/media_space/upload_image"
SUPPORTED_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}


def required_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SystemExit(f"缺少本地 Shopee 配置项：{label}。")
    return text


def load_manifest(path: Path) -> list[dict[str, str]]:
    payload = load_json(path)
    images = payload.get("images") if isinstance(payload, dict) else None
    if not isinstance(images, list) or not images:
        raise SystemExit("图片清单必须是包含非空 images 数组的 JSON 文件。")

    entries = []
    for index, item in enumerate(images):
        if not isinstance(item, dict):
            raise SystemExit(f"图片清单第 {index + 1} 项格式不正确。")
        kind = str(item.get("kind") or "").strip()
        label = str(item.get("label") or "").strip()
        image_path = Path(str(item.get("path") or "")).expanduser()
        if kind not in {"product", "sku", "description"}:
            raise SystemExit(f"图片清单第 {index + 1} 项 kind 必须是 product、sku 或 description。")
        if not label:
            raise SystemExit(f"图片清单第 {index + 1} 项缺少 label。")
        if not image_path.is_file():
            raise SystemExit(f"找不到图片文件：{image_path}")
        if image_path.suffix.lower() not in SUPPORTED_IMAGE_TYPES:
            raise SystemExit(f"不支持的图片格式：{image_path.suffix}")
        entries.append({"kind": kind, "label": label, "path": str(image_path.resolve())})
    return entries


def multipart_body(filename: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = f"----ShopeeImage{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def find_image_id(value: Any) -> str:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"image_id", "imageId"} and nested:
                return str(nested)
            found = find_image_id(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = find_image_id(nested)
            if found:
                return found
    return ""


def upload_image(entry: dict[str, str], shopee: dict[str, Any]) -> str:
    from create_shopee_draft import load_partner_credentials, load_access_credentials

    args = argparse.Namespace(
        partner_id=None,
        partner_key=None,
        access_token=None,
        shop_id=None,
        token_file=None,
        _config={"shopee": shopee},
    )
    partner_id, partner_key = load_partner_credentials(args)
    access_token, shop_id = load_access_credentials(args)
    path = Path(entry["path"])
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body, multipart_type = multipart_body(path.name, path.read_bytes(), content_type)
    params = common_params(partner_id, partner_key, UPLOAD_IMAGE_PATH, access_token, shop_id)
    url = f"{api_host(str(shopee.get('host') or ''))}{UPLOAD_IMAGE_PATH}?"
    from urllib.parse import urlencode

    request = urllib.request.Request(
        url + urlencode(params),
        data=body,
        headers={"Accept": "application/json", "Content-Type": multipart_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Shopee 图片上传失败，HTTP {exc.code}。") from exc
    except (TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Shopee 图片上传未能确认结果，请先检查店铺媒体记录，不要盲目重试：{exc}") from exc
    image_id = find_image_id(result)
    if not image_id:
        raise SystemExit("Shopee 图片上传响应中没有 image_id，请检查接口响应后再继续。")
    return image_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload user-provided local images to Shopee and build an image map.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--manifest", required=True, help="JSON with images: [{path, kind, label}]")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--execute", action="store_true", help="Perform Shopee image uploads; default is validation only.")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    config = load_json(config_path)
    entries = load_manifest(Path(args.manifest).expanduser())
    shopee = config.get("shopee") or {}
    for key in ("partner_id", "partner_key", "shop_id", "access_token"):
        required_text(shopee.get(key), key)
    required_text(shopee.get("host"), "host")

    if not args.execute:
        print(json.dumps({
            "mode": "dry-run",
            "image_count": len(entries),
            "images": [{"kind": e["kind"], "label": e["label"], "filename": Path(e["path"]).name} for e in entries],
            "note": "No Shopee API calls were made. Pass --execute only after confirming the listing rules and destination shop.",
        }, ensure_ascii=False, indent=2))
        return

    refresh_args = argparse.Namespace(
        _config=config,
        _config_path=str(config_path),
        partner_id=None,
        partner_key=None,
        access_token=None,
        shop_id=None,
    )
    refresh_configured_shopee_token(refresh_args)
    shopee = config.get("shopee") or {}
    image_map = []
    for entry in entries:
        image_id = upload_image(entry, shopee)
        image_map.append({
            "kind": entry["kind"],
            "path": f"{entry['label']}{Path(entry['path']).suffix.lower()}",
            "image_id": image_id,
        })

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    map_path = output_dir / "shopee_uploaded_images.json"
    save_json(map_path, image_map)
    print(json.dumps({"ok": True, "image_count": len(image_map), "image_map": str(map_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
