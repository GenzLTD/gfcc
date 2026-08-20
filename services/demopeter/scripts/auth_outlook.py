"""
Outlook 邮箱授权脚本 — 完成首次 OAuth2 授权
运行: python scripts/auth_outlook.py

前提:
1. 已在 Azure 注册应用，拿到 client_id / client_secret
2. 已在 .env 中配置 OUTLOOK_CLIENT_ID / OUTLOOK_CLIENT_SECRET
3. 重定向 URI 已设置为 http://localhost:5220/auth/outlook/callback
"""
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bootstrap_paths  # noqa: F401

from src.outlook_client import OutlookClient

print("=" * 55)
print("  Outlook / Microsoft Graph OAuth2 授权")
print("=" * 55)

# 1. 检查配置
try:
    client = OutlookClient()
except ValueError as e:
    print(f"\n❌ 配置不完整: {e}")
    print("\n请在 .env 中设置:")
    print("  OUTLOOK_CLIENT_ID=你的客户端ID")
    print("  OUTLOOK_CLIENT_SECRET=你的客户端密钥")
    sys.exit(1)

# 2. 检查是否已授权
if client.is_authorized:
    print("\n✅ 已授权，Token 有效。")
    try:
        profile = client.get_profile()
        print(f"   用户: {profile.get('displayName', '?')}")
        print(f"   邮箱: {profile.get('mail', profile.get('userPrincipalName', '?'))}")
    except Exception:
        print("   ⚠️ Token 已过期，将刷新...")
    else:
        print("\n无需重新授权，退出。")
        sys.exit(0)

# 3. 打开授权页面
auth_url = OutlookClient.get_auth_url()
print(f"\n📋 正在打开浏览器进行 Microsoft 登录授权...")
print(f"   如果浏览器未自动打开，请手动访问:\n   {auth_url}\n")
webbrowser.open(auth_url)

# 4. 获取回调 code
print("等待授权回调...")
print('授权完成后，浏览器地址栏会出现 code=... 参数')
code = input("\n请粘贴完整的回调 URL（含 ?code=...）:\n> ").strip()

# 提取 code
import urllib.parse as up
parsed = up.urlparse(code)
query = up.parse_qs(parsed.query)
auth_code = query.get("code", [None])[0]

if not auth_code:
    print("❌ 未检测到授权码，请检查粘贴的 URL")
    sys.exit(1)

# 5. 交换 token
try:
    client.exchange_code(auth_code)
    profile = client.get_profile()
    print(f"\n✅ 授权成功！")
    print(f"   用户: {profile.get('displayName', '?')}")
    print(f"   邮箱: {profile.get('mail', profile.get('userPrincipalName', '?'))}")
    print(f"   Token 已保存到 db/outlook_tokens.json")
    print(f"   refresh_token 可长期有效，无需重复授权")
except Exception as e:
    print(f"\n❌ 换取 token 失败: {e}")
    sys.exit(1)
