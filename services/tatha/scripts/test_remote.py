"""测试远程 Tatha API"""
import json, urllib.request

def test(msg):
    url = "http://47.115.168.107:8010/v1/ask"
    data = json.dumps({"message": msg}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": "Bearer final-verify-deploy"
    }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        r = json.loads(resp.read())
        print(f"\n=== {msg} ===")
        print(json.dumps(r, ensure_ascii=False, indent=2))

test("推荐一句思乡的诗")
test("帮我匹配前端开发职位")
test("我做事喜欢提前规划")
