"""验收机制自身的测试：Node 单元测试套件全部通过；数据层验收脚本对正确数据通过、对违背设计的数据失败。

需求与验收层次见 docs/size-match-acceptance.md。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_build_size_match_code_data import mod as builder, write_inputs

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="需要 Node.js")

# 夹具数据只有 Acura ADX（非皮卡）与 Cadillac Escalade EXT（皮卡）
SCENARIOS = {"searches": [
    {"id": "F1", "requirement": "R3", "title": "acura adx", "query": "acura adx", "source": "US", "kind": "nonpick",
     "expect": {"makes": ["Acura"], "models": ["ADX"]}},
    {"id": "F2", "requirement": "R3", "title": "escalade 2004", "query": "escalade 2004", "source": "EU", "kind": "pick",
     "expect": {"makes": ["Cadillac"], "models": ["Escalade EXT"], "year": 2004}},
]}


def test_node_unit_suites_pass():
    suites = sorted(str(path) for path in (ROOT / "tests" / "js").glob("*.test.cjs"))
    completed = subprocess.run([NODE, "--test", *suites], capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode == 0, completed.stdout[-3000:] + completed.stderr[-2000:]


def make_site(tmp_path: Path) -> tuple[Path, Path, Path]:
    site = tmp_path / "site"
    a1, a0 = write_inputs(tmp_path)
    builder.build(a1, site / "data" / "generated", a0)
    data = "data/generated/size-match-data.json"
    (site / "size-match.html").write_text(f'matchDataPath: "{data}",\nhistoryDataPath: "{data}"\n', encoding="utf-8")
    (site / "assets" / "app").mkdir(parents=True)
    shutil.copy2(ROOT / "site_overrides" / "assets" / "app" / "viewer-data.js", site / "assets" / "app" / "viewer-data.js")
    scenarios = tmp_path / "scenarios.json"
    scenarios.write_text(json.dumps(SCENARIOS, ensure_ascii=False), encoding="utf-8")
    return site, a1, scenarios


def run_acceptance(site: Path, a1: Path, scenarios: Path, out: Path) -> tuple[int, dict[str, dict]]:
    script = ROOT / "tests" / "acceptance" / "size_match_data.cjs"
    completed = subprocess.run([NODE, str(script), "--site", str(site), "--a1", str(a1), "--scenarios", str(scenarios), "--out", str(out)],
                               capture_output=True, text=True, encoding="utf-8")
    results = json.loads(out.read_text(encoding="utf-8"))["results"]
    return completed.returncode, {item["id"]: item for item in results}


def test_data_acceptance_passes_on_built_data(tmp_path):
    site, a1, scenarios = make_site(tmp_path)
    code, results = run_acceptance(site, a1, scenarios, tmp_path / "out.json")
    assert code == 0, [item for item in results.values() if item["status"] != "pass"]
    assert set(results) == {"D1", "D2", "D3", "D4", "F1", "F2"}


def test_data_acceptance_rejects_duplicate_data_and_wrong_sources(tmp_path):
    site, a1, scenarios = make_site(tmp_path)
    generated = site / "data" / "generated"
    (generated / "size-match-full.json").write_text("{}", encoding="utf-8")
    shard_path = next(generated.glob("size-match-data-01-us-nonpick-*.json"))
    shard = json.loads(shard_path.read_text(encoding="utf-8"))
    shard["compressed"][0]["refs"] = [[0, "2024"]]  # 指向另一行：与 A1 压缩来源不一致
    shard_path.write_text(json.dumps(shard), encoding="utf-8")
    code, results = run_acceptance(site, a1, scenarios, tmp_path / "out.json")
    assert code == 1
    assert results["D1"]["status"] == "fail" and "size-match-full.json" in results["D1"]["detail"]
    assert results["D4"]["status"] == "fail" and "US 不一致" in results["D4"]["detail"]


def test_data_acceptance_rejects_out_of_context_search_results(tmp_path):
    site, a1, scenarios = make_site(tmp_path)
    # 场景期望只出现 ADX；把 Acura 记录的 MODEL 期望改成别的车型，模拟搜索结果混入上下文之外的车型
    payload = json.loads(scenarios.read_text(encoding="utf-8"))
    payload["searches"][0]["expect"]["models"] = ["RDX"]
    scenarios.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    code, results = run_acceptance(site, a1, scenarios, tmp_path / "out.json")
    assert code == 1 and results["F1"]["status"] == "fail" and "上下文之外的车型：ADX" in results["F1"]["detail"]
