"""快速冒烟测试，验证 agent pipeline 基本可通"""
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.service.agent.agent import final_answer

query = "烈咬陆鲨的速度种族值是多少，适合什么对战策略？"
print(f"问题：{query}\n{'='*60}")

for event in final_answer(query):
    if "thinking" in event and '"thinking": false' in event.lower():
        import json, re
        m = re.search(r'data: (.+)', event)
        if m:
            data = json.loads(m.group(1))
            print(data.get("content", ""), end="", flush=True)

print("\n" + "="*60)
