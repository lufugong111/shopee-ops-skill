# First-Time Shopee Setup

Use this guide only when a Shopee integration is not already configured.

1. Ask which Shopee marketplace/region and shop the user intends to connect.
2. Direct the user to the official Shopee Open Platform (`https://open.shopee.com/`) and have them follow the current app registration and developer onboarding instructions. The console's current requirements take precedence over this guide.
3. Have the shop owner authorize the app for the intended shop using Shopee's official OAuth/authorization flow. Do not ask for the owner's Shopee password or for them to send an authorization code in chat.
4. Identify, from the current console and selected API product, the values the integration requires. Common fields are Partner ID, Partner Key, API host/region, shop ID, access token, and refresh token. Feishu/source-system credentials are separate and optional.
5. Configure the values in an access-controlled local secret store or environment variables supported by the integration. A local ignored credentials file is acceptable only when the project provides it and permissions are appropriately restricted. Never put credentials in `SKILL.md`, committed files, issue text, chat, screenshots, or ordinary logs.
6. Verify configuration presence without printing values. Make a read-only or dry-run API check first. If app review, permissions, token exchange, or shop authorization is incomplete, stop and tell the user which official setup step remains.

Do not fabricate credentials, scopes, API hosts, callback URLs, or approval status. Verify those details against the user's Shopee Open Platform console and current official documentation because they can vary by region and integration version.
