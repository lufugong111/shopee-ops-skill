# Shopee Product Workflow

## Inputs

- Product facts, title/description, category, attributes, SKU, variations, price, stock, shipping, package data, and status: supplied by the user or explicitly confirmed for this listing.
- Images: supplied through the user's current interface or as local files. Classify every image as product gallery, SKU/variation, or description media. Ask about ambiguous images.
- Shopee credentials and shop authorization: bound locally in `config/credentials.json`, environment variables, or an approved secret store. Never put credential values in this reference or output artifacts.

## Local Image Manifest

`scripts/upload_local_images.py` accepts a JSON manifest:

```json
{
  "images": [
    {"path": "<local-file-path>", "kind": "product", "label": "<image-role>"},
    {"path": "<local-file-path>", "kind": "sku", "label": "<variation-option>"},
    {"path": "<local-file-path>", "kind": "description", "label": "<description-image-role>"}
  ]
}
```

Use absolute local paths when files are staged from interface uploads. The manifest contains file paths and labels only; Shopee image IDs are returned by the API and written to the generated image map. Run the helper without `--execute` to validate and preview. Run with `--execute` only after confirming the selected shop and listing rules.

The image map is consumed by `scripts/create_shopee_draft.py`. Product gallery, variation-option, and description media remain separate `kind` values. For product gallery entries, use the creator's supported labels: `主图`, `背景图` (or `合规白底主图` fallback), `背景图1`, `多场景图`, `细节特写图1`, `买点解析图`/`卖点解析图`, `一`, `二`, and `三`. Use the user's confirmed ordering and current Shopee image constraints for the selected market/category. Use the actual variation label for `sku` entries and `KV细节图` for a description image when applicable.

## Create Flow

1. Confirm the destination shop, user-supplied product facts/images, and applicable listing rules.
2. Verify the intended Shopee credentials are configured locally and the active authorization matches the selected shop. Stop if this cannot be established.
3. Resolve current category requirements, allowed attribute values, logistics, image constraints, and API fields from the selected market's Shopee documentation. Do not hard-code numeric identifiers or values from another shop/market.
4. Validate all required product fields, variations, model SKUs, media, prices, inventory, package details, shipping, and attributes. Ask about missing values.
5. Show the complete payload preview and ask for explicit confirmation.
6. Upload images, then call the Shopee product-create operation with `item_status = UNLIST`.
7. Use the returned item identifier for variation initialization and verification. If variation initialization hits a documented transient update lock, retry only that operation according to the current API guidance.
8. Verify the created item and report its status and identifier without exposing credentials or signatures.

Never blindly retry a timed-out create request; inspect the shop first because the original request may have succeeded.

## Existing Item Operations

When `--item-id` is supplied, load the existing item and preserve fields the user did not ask to change. The script supports targeted updates for tier labels, logistics, attributes, description/package fields, price/stock, and video. Before a live update, verify the item belongs to the intended shop and show the exact update scope for confirmation.

For video updates, local file upload is update-only. Validate file size and current Shopee video constraints before any network request. Treat a successful update response and unchanged item status as the API-side confirmation when the read endpoint does not expose the video field.
