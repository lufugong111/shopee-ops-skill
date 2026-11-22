---
name: shopee-draft-writer
description: Prepare and upload new Shopee products using product details and images supplied through the user's interface or local files. Before use, confirm the target shop, secure Shopee credential binding, and the listing rules for this product.
---

# Shopee Draft Writer

Use this skill for Shopee product creation from information and images the user provides through the current interface or local files. This package contains Shopee product operations only.

## Before Use

Before reading product assets or calling Shopee, ask the user to confirm:

- Marketplace/region, destination shop, and listing language.
- That the Shopee app credentials and shop authorization are bound in the local protected configuration and correspond to the selected shop.
- Product details and the exact user-provided files/images to use.
- This product's listing rules: title/description, category/attributes, price/stock, SKU and variations, image order, logistics, package data, and desired status.

Ask which optional rule groups apply. Do not reuse another product's or shop's values as defaults. If credentials are missing or point to another shop, stop before any Shopee API call and guide the user to bind the account locally. Never ask for Partner Key, access/refresh token, app secret, password, or authorization code in chat. Show configured/missing status only and mask any shop identifier.

For first-time setup, direct the user to Shopee Open Platform (`https://open.shopee.com/`) to register the app and authorize the intended shop. Check the current console for the fields required by that region/API version; common local configuration fields include Partner ID, Partner Key, API host, Shop ID, and OAuth access/refresh tokens. The user must enter these into the protected local configuration, not chat. Verify that the configured authorization matches the selected shop before proceeding.

Show the effective rules and complete listing preview, then obtain explicit confirmation immediately before the first Shopee write request. This creator supports creating `UNLIST` drafts; it does not publish items for public sale.

## User-Provided Images

Read images attached or uploaded by the user in the current interface, or use local image files the user explicitly supplies. Ask the user to identify each image's role when filenames or ordering are ambiguous. Do not retrieve product data or images from an external catalog.

For local files, create an image manifest with entries containing `path`, `kind` (`product`, `sku`, or `description`), and `label`. Run `scripts/upload_local_images.py` without `--execute` first to validate and preview the files. Only after rules, shop binding, and the product preview are confirmed, run it with `--execute` to upload the images and write `outputs/shopee_uploaded_images.json`.

## Shopee Workflow

- Read [references/workflow.md](references/workflow.md) before preparing a new listing or changing this workflow.
- Use the Shopee-only `config/credentials.json` template, populated locally through a protected configuration path. All credentials and listing values must be supplied for the intended shop/product; this package has no account secrets, fixed shop/product/category IDs, or fixed listing defaults.
- Use `scripts/create_shopee_draft.py` with the prepared image map to preview or create the draft. The script requires explicit product/category/SKU/price/stock/shipping/package/variation inputs and stops when required values are missing.
- New items are created as `UNLIST`. The script initializes the configured variation tiers after creation. Never retry `add_item` after an ambiguous timeout until the shop is checked for a previously created item.
- Existing-item operations remain available through `--item-id`, including tier-option, logistics, category-attribute, description/package, price/stock, and video updates. Ask the user to confirm the exact item and fields before changing them; preserve unspecified live fields.
- Local video upload is update-only. Check the file size and documented Shopee constraints before any video API request.
- Keep credentials and signed request data out of logs, previews, result artifacts, and source control.
