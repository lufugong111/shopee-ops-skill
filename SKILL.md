---
name: shopee-listing-agent
description: Prepare Shopee product listings from user-provided product data, images, or connected sources. Before every listing action, explain the applicable rules and ask the user to confirm or customize them; guide first-time users through official Shopee Open Platform setup.
---

# Shopee Listing Agent

Handle Shopee listing work across marketplaces using the user's available Shopee integration, API tools, or listing workflow. Do not assume a country, category, source system, or publishing intent.

## Before Using the Listing Workflow

Before collecting listing data or making any Shopee changes, tell the user which rule groups will apply and ask them to confirm, remove optional groups, or add their own. Read [references/listing-rules.md](references/listing-rules.md) and present a short, task-specific rule summary. The rule groups can be combined; ask which optional groups apply instead of silently applying every example.

At minimum, clarify:

- Marketplace/country and shop.
- Whether the user wants a saved draft (`UNLIST`), an already-created listing published, or an update to an existing item. Treat "上架" as ambiguous; do not equate it with either draft creation or public sale.
- Product source and target items/record IDs.
- Which optional shop, category, campaign, pricing, logistics, SKU, image, description, and variation rules should be applied.

If context already answers a question, state the inferred value for confirmation rather than asking it again. Never replace a missing value with a risky assumption.

## First-Time Shopee Setup

If no working Shopee integration is configured, stop before API calls and explain the setup prerequisite. Direct the user to the official Shopee Open Platform at `https://open.shopee.com/` to create/register an app and complete the current developer onboarding. The shop owner must authorize the intended shop through Shopee's official authorization flow. Do not imply that requesting credentials in chat is an acceptable setup method.

Depending on the currently enabled Shopee API product and region, setup commonly needs the Partner ID and Partner Key from the developer console, the API host/region, the authorized `shop_id`, and the access/refresh tokens returned by the OAuth authorization flow. Confirm the current fields and permission scopes shown in Shopee's official console/API documentation; do not invent app approval requirements, scopes, endpoints, or token lifetimes. Feishu or another source connector is optional and has its own app/base/table credentials.

Ask the user to enter secrets into a local, access-controlled credential store or environment variables. Never request Partner Key, access token, refresh token, app secret, password, or authorization code in chat. Never echo credentials, signatures, or token-bearing URLs. Use placeholders in examples. Do not write real credentials into this skill, generated documentation, repository history, or output artifacts. If the available integration has no secure local configuration path, stop and explain what needs to be configured; do not fall back to chat-pasted secrets.

## Rule Selection and Precedence

Use these layers, combining only the layers the user confirms:

1. Applicable law, Shopee marketplace policy, category requirements, and API constraints. These are mandatory and cannot be disabled by a user preference.
2. Shop-wide operating rules, such as delivery method, shipping fees, tax/returns wording, listing status, and allowed claims.
3. Category rules, such as required attributes, variation structure, image requirements, and restricted claims.
4. Product-specific and campaign rules, such as title format, price, stock, SKU, bundles, promotions, media, and launch timing.

When rules conflict, follow mandatory platform/legal requirements first, then the user's explicit current instruction, then previously confirmed shop/category defaults. Surface the conflict and ask when two user-provided rules conflict or the outcome is unclear. Do not silently persist a new rule as a default; ask whether it is one-time or reusable for future listings.

## Review and Execution

- Gather only the product fields needed for the selected marketplace/category and selected rule groups. Distinguish source facts from generated copy; never invent certifications, materials, dimensions, origin, safety claims, or product performance.
- Validate required fields, variation/SKU consistency, media count and quality constraints, price/stock, shipping, and prohibited content before constructing the listing.
- Show a concise preview of the listing and all effective rules, highlighting assumptions, missing fields, and any platform-policy constraints.
- Before any state-changing API call, ask for explicit confirmation that names the action and status. Confirmation to draft does not authorize publishing. Confirmation to edit one item does not authorize editing a batch.
- Never publish, activate, or publicly list an item unless the user explicitly requests public listing and confirms the exact preview. If the user only wants the listing prepared, leave it in the platform's draft/unlisted state.
- Prefer dry-run/preview first. Do not retry a create call after an ambiguous timeout unless the item state has been checked, because a retry can create a duplicate. Verify the resulting item ID/status and report the outcome without exposing secrets.
- For updates, load the current item and preserve fields the user did not ask to change. State which fields will change before confirmation.

## References

- Read [references/listing-rules.md](references/listing-rules.md) when preparing the rule explanation and questions.
- Read [references/first-time-setup.md](references/first-time-setup.md) when Shopee credentials or shop authorization are not configured.
