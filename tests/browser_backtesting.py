"""Run explicitly after web build: uv run pytest tests/browser_backtesting.py -q.

Owns a temporary MySQL DB through the regular fixture; never seeds personal data.
Requires `uv run playwright install chromium` on a fresh developer machine.
"""

import json
import os
import socket
import threading
import time
from decimal import Decimal
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright
from test_backtesting import installed as installed
from test_backtesting import seed

from tradeguard.console import create_app
from tradeguard.market.schemas import BarInput
from tradeguard.market.service import save_bars


def test_create_portfolio_report_and_manage_plugins_in_browser(database, installed, tmp_path):
    seed()
    save_bars(
        [
            BarInput.model_validate(
                {
                    "symbol": "600000.SH",
                    "source": "other_fixture",
                    "adjustment": "forward",
                    "trade_date": "2025-02-03",
                    "open": "12",
                    "high": "12",
                    "low": "12",
                    "close": "12",
                    "volume": "100000",
                }
            )
        ]
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(), host="127.0.0.1", port=port, log_level="warning", access_log=False
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started, "Temporary test server failed to start"
        with sync_playwright() as automation:
            browser = automation.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, accept_downloads=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/backtests?market=CN&source=fixture&adjustment=none")
            expect(page.get_by_role("heading", name="策略与回测", exact=True)).to_be_visible()
            expect(page.get_by_text("还没有此范围的回测。", exact=False)).to_be_visible()
            page.get_by_role("button", name="新建回测", exact=True).click()
            form = page.get_by_role("form", name="新建回测实验")
            # A newer default source must not extend the explicitly selected cache.
            expect(form.get_by_label("结束日期", exact=True)).to_have_value("2025-01-09")
            expect(form.get_by_label("开始日期", exact=True)).to_have_value("2024-01-09")
            form.get_by_label("实验名称", exact=True).fill("浏览器多股票验收")
            form.get_by_label("开始日期", exact=True).fill("2025-01-06")
            form.get_by_label("结束日期", exact=True).fill("2025-01-09")
            form.get_by_role("textbox", name="固定股票池", exact=False).fill("600000.SH, 600001.SH")
            form.get_by_role("checkbox", name="均线金叉多头排列").uncheck()
            form.get_by_role("checkbox", name="箱体突破", exact=True).uncheck()
            form.get_by_role("checkbox", name="合成验收信号", exact=True).check()
            form.get_by_label("初始资金", exact=True).fill("10000")
            form.get_by_label("最多持仓数", exact=True).fill("2")
            form.get_by_label("单股目标权重", exact=False).fill("0.5")
            form.get_by_label("可投资比例", exact=False).fill("1")
            form.get_by_label("佣金比例", exact=True).fill("0")
            form.get_by_label("最低佣金", exact=True).fill("0")
            form.get_by_label("单边滑点", exact=False).fill("0")
            form.get_by_label("每次成交/前日成交量上限", exact=True).fill("1")
            form.get_by_role("checkbox", name="确认使用", exact=False).check()
            form.get_by_role("button", name="检查数据", exact=True).click()
            expect(form.get_by_role("status")).to_contain_text("4 个观察日")
            form.get_by_role("button", name="开始回测", exact=True).click()
            expect(page.get_by_role("heading", name="浏览器多股票验收", exact=True)).to_be_visible(
                timeout=15000
            )
            expect(page.get_by_role("img", name="组合净值与基准曲线")).to_be_visible(timeout=15000)
            expect(page.get_by_text("20.00%", exact=True).first).to_be_visible()
            page.get_by_role("tab", name="订单与未成交原因", exact=True).click()
            expect(page.get_by_text("已成交", exact=True).first).to_be_visible()
            page.get_by_role("tab", name="持仓", exact=True).click()
            expect(page.get_by_text("当日收盘", exact=True).first).to_be_visible()
            page.get_by_role("tab", name="配置与数据清单", exact=True).click()
            expect(page.get_by_text("输入 SHA-256：", exact=False)).to_be_visible()
            page.get_by_role("tab", name="成交", exact=True).click()
            with page.expect_download() as download:
                page.get_by_role("button", name="导出报告 JSON", exact=True).click()
            target = tmp_path / "report.json"
            download.value.save_as(target)
            saved = json.loads(target.read_text())
            assert saved["report"]["metrics"]["trade_count"] == 2
            assert len(saved["report"]["positions"]) == 2
            expect(page.get_by_text("基准：未知", exact=True)).to_be_visible()
            # Capture the report on its own; then check responsive navigation.
            page.get_by_role("button", name="收起配置", exact=True).click()
            screenshot = Path(
                os.environ.get("TRADEGUARD_QA_SCREENSHOT", str(tmp_path / "report.png"))
            )
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot), full_page=True)
            page.get_by_role("button", name="策略管理", exact=True).click()
            card = page.locator("div.rounded-lg").filter(
                has=page.get_by_text("合成验收信号", exact=True)
            )
            card.get_by_role("button", name="禁用", exact=True).click()
            expect(card.get_by_role("button", name="启用", exact=True)).to_be_visible()
            page.reload()
            expect(page.get_by_role("img", name="组合净值与基准曲线")).to_be_visible()
            page.get_by_role("button", name="美股 · USD", exact=True).click()
            expect(page.get_by_role("img", name="组合净值与基准曲线")).to_have_count(0)
            expect(page.get_by_role("heading", name="实验记录 · US", exact=False)).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="打开菜单", exact=True).click()
            expect(
                page.get_by_role("navigation", name="主导航").get_by_role(
                    "button", name="策略与回测"
                )
            ).to_be_visible()
            page.get_by_role("button", name="关闭菜单", exact=True).click()
            page.set_viewport_size({"width": 1440, "height": 1100})
            page.get_by_role("button", name="A 股 · CNY", exact=True).click()
            page.get_by_role("button", name="策略管理", exact=True).click()
            search = page.get_by_role("textbox", name="搜索策略或类别", exact=True)
            search.fill("通用均线")
            ma_card = page.locator("div.rounded-lg").filter(
                has=page.get_by_text("通用均线交叉", exact=True)
            )
            ma_card.get_by_text("学习思路与条件", exact=True).click()
            expect(
                ma_card.get_by_role("heading", name="入场 / 调仓条件", exact=True)
            ).to_be_visible()
            expect(ma_card.get_by_text("昨日快/慢线为", exact=False)).to_be_visible()
            ma_card.get_by_role("button", name="用此信号回测", exact=True).click()
            form = page.get_by_role("form", name="新建回测实验")
            experiment_name = form.get_by_label("实验名称", exact=True)
            expect(experiment_name).to_be_focused()
            expect(experiment_name).to_be_in_viewport(ratio=1)
            mode_note = form.get_by_role("note", name="当前回测方式", exact=True)
            expect(mode_note).to_contain_text("单信号策略回测")
            expect(mode_note).to_contain_text("尚未运行")
            expect(form.get_by_role("checkbox", name="通用均线交叉", exact=True)).to_be_checked()
            expect(form.get_by_role("checkbox", name="均线金叉多头排列")).not_to_be_checked()
            expect(form.get_by_role("checkbox", name="箱体突破", exact=True)).not_to_be_checked()
            form.get_by_role("checkbox", name="箱体突破", exact=True).check()
            expect(mode_note).to_contain_text("多信号组合回测 · 2 个信号 · 全部命中")
            form.get_by_label("组合条件", exact=True).select_option("any")
            expect(mode_note).to_contain_text("任一命中")
            form.get_by_label("组合条件", exact=True).select_option("at_least")
            expect(mode_note).to_contain_text("至少 2 个命中")
            # Reapplying the same preset also brings an already open form into view.
            ma_card.get_by_role("button", name="用此信号回测", exact=True).click()
            expect(experiment_name).to_be_focused()
            expect(experiment_name).to_be_in_viewport(ratio=1)
            expect(mode_note).to_contain_text("单信号策略回测")
            expect(form.get_by_role("checkbox", name="箱体突破", exact=True)).not_to_be_checked()
            form.get_by_text("参数与时序窗口", exact=True).click()
            params = form.get_by_role("group", name="通用均线交叉参数", exact=True)
            params.get_by_role("spinbutton", name="快线周期", exact=False).fill("2")
            params.get_by_role("spinbutton", name="慢线周期", exact=False).fill("3")
            expect(params.get_by_role("spinbutton", name="快线周期", exact=False)).to_have_value(
                "2"
            )
            search.fill("多股票相对动量")
            rotation_card = page.locator("div.rounded-lg").filter(
                has=page.get_by_text("多股票相对动量轮动", exact=True)
            )
            rotation_card.get_by_text("学习思路与条件", exact=True).click()
            expect(rotation_card.get_by_text("把可比较的历史价格收益", exact=False)).to_be_visible()
            learning_shot = screenshot.with_name("strategy-learning.png")
            rotation_card.screenshot(path=str(learning_shot))
            rotation_card.get_by_role("button", name="用此交易策略回测", exact=True).click()
            expect(experiment_name).to_be_focused()
            expect(experiment_name).to_be_in_viewport(ratio=1)
            expect(mode_note).to_contain_text("独立交易策略回测 · 多股票相对动量轮动")
            expect(form.get_by_role("checkbox", name="通用均线交叉", exact=True)).to_have_count(0)
            params = form.get_by_role("group", name="多股票相对动量轮动参数", exact=True)
            params.get_by_role("spinbutton", name="动量回看周期", exact=False).fill("2")
            params.get_by_role("spinbutton", name="跳过近期日数", exact=False).fill("0")
            params.get_by_role("spinbutton", name="排名入选数", exact=False).fill("1")
            form.get_by_label("实验名称", exact=True).fill("学习策略验收·轮动")
            form.get_by_label("开始日期", exact=True).fill("2025-01-06")
            form.get_by_label("结束日期", exact=True).fill("2025-01-09")
            form.get_by_role("textbox", name="固定股票池", exact=False).fill("600000.SH, 600001.SH")
            form.get_by_role("checkbox", name="确认使用", exact=False).check()
            form.get_by_role("button", name="开始回测", exact=True).click()
            expect(page.get_by_role("heading", name="学习策略验收·轮动", exact=True)).to_be_visible(
                timeout=15000
            )
            expect(page.get_by_role("img", name="组合净值与基准曲线")).to_be_visible(timeout=15000)
            with page.expect_download() as download:
                page.get_by_role("button", name="导出报告 JSON", exact=True).click()
            target = tmp_path / "learning-report.json"
            download.value.save_as(target)
            learned = json.loads(target.read_text())
            assert learned["config"]["combination"] is None
            assert learned["config"]["strategy_parameters"] == {
                "lookback": 2,
                "skip": 0,
                "top_n": 1,
            }
            assert learned["report"]["metrics"]["trade_count"] == 1
            assert learned["plugins"][0]["education"]["family"] == "轮动"
            page.get_by_role("tab", name="配置与数据清单", exact=True).click()
            expect(page.get_by_text("策略学习说明（随实验归档）", exact=True)).to_be_visible()
            # A native strategy's private parameters must not leak into a signal run.
            search.fill("通用均线")
            ma_card.get_by_role("button", name="用此信号回测", exact=True).click()
            expect(experiment_name).to_be_focused()
            expect(experiment_name).to_be_in_viewport(ratio=1)
            form.get_by_text("参数与时序窗口", exact=True).click()
            params = form.get_by_role("group", name="通用均线交叉参数", exact=True)
            params.get_by_role("spinbutton", name="快线周期", exact=False).fill("2")
            params.get_by_role("spinbutton", name="慢线周期", exact=False).fill("3")
            with page.expect_response("**/api/backtests/preflight") as checked:
                form.get_by_role("button", name="检查数据", exact=True).click()
            assert checked.value.status == 200
            signal_config = checked.value.request.post_data_json
            assert signal_config["portfolio_strategy"] == "signal_portfolio"
            assert signal_config["strategy_parameters"] == {}
            assert [s["name"] for s in signal_config["combination"]["signals"]] == [
                "moving_average_cross"
            ]
            expect(form.get_by_role("status")).to_contain_text("4 个观察日")
            form.get_by_role("button", name="开始回测", exact=True).click()
            expect(
                page.get_by_role("heading", name="学习回测 · 通用均线交叉", exact=True)
            ).to_be_visible(timeout=15000)
            expect(page.get_by_role("img", name="组合净值与基准曲线")).to_be_visible(timeout=15000)
            # Reuse the real configuration form for same-input comparison and allocation.
            form.get_by_label("实验名称", exact=True).fill("对比·均线")
            form.get_by_role("button", name="加入对比 / 组合", exact=True).click()
            study_form = page.get_by_role("region", name="策略对比与资金组合配置", exact=True)
            expect(study_form.get_by_text("对比·均线", exact=True)).to_be_visible()
            search.fill("多股票相对动量")
            rotation_card.get_by_role("button", name="用此交易策略回测", exact=True).click()
            params = form.get_by_role("group", name="多股票相对动量轮动参数", exact=True)
            params.get_by_role("spinbutton", name="动量回看周期", exact=False).fill("2")
            params.get_by_role("spinbutton", name="跳过近期日数", exact=False).fill("0")
            params.get_by_role("spinbutton", name="排名入选数", exact=False).fill("1")
            form.get_by_label("实验名称", exact=True).fill("对比·轮动")
            form.get_by_role("button", name="加入对比 / 组合", exact=True).click()
            ma_row = study_form.get_by_role("row").filter(
                has=page.get_by_text("对比·均线", exact=True)
            )
            ma_row.get_by_role("button", name="载入编辑", exact=True).click()
            expect(experiment_name).to_be_focused()
            params = form.get_by_role("group", name="通用均线交叉参数", exact=True)
            # Parameters survive loading the saved variant, and replacement does not append.
            expect(params.get_by_role("spinbutton", name="快线周期", exact=False)).to_have_value(
                "2"
            )
            form.get_by_label("实验名称", exact=True).fill("对比·均线已编辑")
            form.get_by_role("button", name="替换正在编辑的方案", exact=True).click()
            expect(study_form.get_by_role("row")).to_have_count(3)
            expect(study_form.get_by_text("对比·均线", exact=True)).to_have_count(0)
            form.get_by_label("初始资金", exact=True).fill("12000")
            form.get_by_role("button", name="更新共同设置", exact=True).click()
            expect(study_form.get_by_text("12,000 CNY", exact=False)).to_be_visible()
            study_form.get_by_label("研究实验名称", exact=True).fill("浏览器同口径策略对比")
            study_form.get_by_role("checkbox", name="确认所有方案", exact=False).check()
            study_form.get_by_role("button", name="检查全部方案", exact=True).click()
            expect(study_form.get_by_role("status")).to_contain_text("4 个观察日")
            study_form.get_by_role("button", name="运行策略对比", exact=True).click()
            expect(
                page.get_by_role("heading", name="浏览器同口径策略对比", exact=True)
            ).to_be_visible(timeout=15000)
            overlay = page.get_by_role("img", name="各策略归一化净值对比曲线", exact=True)
            expect(overlay).to_be_visible(timeout=15000)
            expect(overlay).to_be_in_viewport(ratio=1)
            page.get_by_role("button", name="查看对比·轮动完整报告", exact=True).click()
            expect(page.get_by_role("heading", name="对比·轮动", exact=True)).to_be_visible()
            expect(page.get_by_role("img", name="组合净值与基准曲线")).to_be_visible()
            page.get_by_role("button", name="收起子报告", exact=True).click()
            with page.expect_download() as download:
                page.get_by_role("button", name="导出研究报告 JSON", exact=True).click()
            target = tmp_path / "comparison.json"
            download.value.save_as(target)
            compared = json.loads(target.read_text())
            assert compared["study_report"]["portfolio"] is None
            assert len(compared["study_report"]["cases"]) == 2
            assert all(
                c["initial_cash"] == compared["config"]["initial_cash"]
                for c in compared["study_report"]["cases"]
            )
            page.get_by_role("button", name="策略对比 / 资金组合", exact=True).click()
            study_form.get_by_role("tab", name="资金组合", exact=True).click()
            study_form.get_by_label("研究实验名称", exact=True).fill("浏览器独立资金组合")
            first_weight = study_form.get_by_role(
                "spinbutton", name="对比·均线已编辑初始资金比例百分数", exact=True
            )
            first_weight.fill("75")
            study_form.get_by_role("button", name="检查全部方案", exact=True).click()
            expect(study_form.get_by_role("alert")).to_contain_text("100%")
            first_weight.fill("50")
            study_form.get_by_role("button", name="运行资金组合", exact=True).click()
            expect(
                page.get_by_role("heading", name="浏览器独立资金组合", exact=True)
            ).to_be_visible(timeout=15000)
            summary = page.get_by_role("note", name="资金组合汇总", exact=True)
            expect(summary).to_contain_text("组合累计收益", timeout=15000)
            expect(page.get_by_role("heading", name="各策略收益贡献", exact=True)).to_be_visible()
            page.screenshot(path=str(screenshot.with_name("strategy-studies.png")))
            with page.expect_download() as download:
                page.get_by_role("button", name="导出研究报告 JSON", exact=True).click()
            target = tmp_path / "allocation.json"
            download.value.save_as(target)
            allocated = json.loads(target.read_text())["study_report"]
            assert sum(Decimal(c["initial_cash"]) for c in allocated["cases"]) == Decimal(
                compared["config"]["initial_cash"]
            )
            assert sum(
                Decimal(c["return_contribution"]) for c in allocated["attribution"]
            ) == Decimal(allocated["portfolio"]["metrics"]["total_return"])
            page.reload()
            expect(page.get_by_role("note", name="资金组合汇总", exact=True)).to_contain_text(
                "组合累计收益"
            )
            page.get_by_role("button", name="美股 · USD", exact=True).click()
            expect(overlay).to_have_count(0)
            page.get_by_role("button", name="策略对比 / 资金组合", exact=True).click()
            expect(study_form.get_by_text("② 策略方案 · 0/8", exact=True)).to_be_visible()
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
