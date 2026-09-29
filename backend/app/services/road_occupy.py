"""占道施工业务规则：延期审批、路面恢复跟踪与竣工验收闭环都收在这里。

时间轴把「占道申请 → 批准期限 → 施工路段/占道面积 → 延期 → 撤场 → 路面恢复 →
竣工验收」串成一条线；时间轴、审批详情与竣工验收共用同一份许可范围与恢复状态口径。
面积溢占、延期材料不全、恢复日期早于施工结束这三种情况不会被直接放行，
会在开始施工、延期审批、路面恢复与竣工验收各节点被拦下。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.store import store

MODULE = "road_occupy"
REQUIRED_FIELDS = ["申请编号", "施工路段", "占道面积"]
# 原四态之后追加「已恢复」「已验收」，覆盖路面恢复跟踪与竣工验收闭环。
STATUS_ORDER = ["待审批", "已批准", "施工中", "已撤场", "已恢复", "已验收"]
# 主状态推进动作；延期受理/审批只改延期记录，不直接推进主状态。
ACTION_RULES = {
    "审批通过": "已批准",
    "开始施工": "施工中",
    "申请延期": None,
    "审批延期": None,
    "确认撤场": "已撤场",
    "路面恢复": "已恢复",
    "竣工验收": "已验收",
}
NEGATIVE_ACTIONS: list[str] = []

# 延期审批需要的材料，缺一项都视为延期材料不全。
EXTENSION_MATERIALS = ["延期申请单", "现场佐证材料"]
# 占道面积允许误差，实际占道面积超过批准面积（含误差）即判溢占。
AREA_TOLERANCE = 0.0


def _parse_date(value: Any) -> date | None:
    """把 'YYYY-MM-DD' 或 date/datetime 统一成 date；解析不了就返回 None。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_area(value: Any) -> float | None:
    """从数字或 '120㎡' 这类文本里取出占道面积；取不到有效正数时返回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else None


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _fmt_area(value: float | None) -> str:
    """面积展示口径：整数不带小数点，未取到时显示 '—'。"""
    if value is None:
        return "—"
    return f"{value:.0f}" if float(value).is_integer() else f"{value:g}"


class RoadOccupyService:
    # ---------- 查询 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("申请编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [self._summary(dict(row)) for row in rows[start:start + size]]
        return page_rows, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._detail(entry)

    def timeline(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return {
            "申请编号": entry.get("申请编号"),
            "timeline": self._timeline(entry),
            "permit_scope": self._permit_scope(entry),
            "restoration": self._restoration(entry),
            "checks": self._checks(entry),
        }

    # ---------- 登记 ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS + ["作业单位", "交通疏导", "审批单位", "占道起止日"]:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        # 占道起止日形如「2026-09-01 至 2026-09-20」，拆出申请的起止日便于后续比对。
        period = str(values.get("占道起止日") or "")
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", period)
        if dates:
            entry["申请起始日"] = dates[0]
            entry["申请截止日"] = dates[-1]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["extensions"] = []
        rows.append(entry)
        return self._detail(entry), []

    # ---------- 动作流转 ----------
    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        values = values or {}
        if entry is None:
            return None, f"占道申请 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于占道施工可执行范围"

        if action == "审批通过":
            return self._approve(entry, values)
        if action == "开始施工":
            return self._start_construction(entry, values)
        if action == "申请延期":
            return self._apply_extension(entry, values)
        if action == "审批延期":
            return self._review_extension(entry, values)
        if action == "确认撤场":
            return self._finish_construction(entry, values)
        if action == "路面恢复":
            return self._restore_surface(entry, values)
        if action == "竣工验收":
            return self._accept(entry, values)
        return None, f"动作「{action}」暂未接入"

    # ---------- 各动作的放行规则 ----------
    def _approve(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if entry.get("status") != "待审批":
            return self._blocked(entry, "只有待审批的占道申请才能审批通过")
        applied_area = _parse_area(values.get("占道面积", entry.get("占道面积")))
        approved_area = _parse_area(values.get("批准面积"))
        if applied_area is None:
            return self._blocked(entry, "申请占道面积无法识别，请补录有效的面积数值")
        if approved_area is None:
            approved_area = applied_area  # 未单列批准面积时，按申请面积批准
        if approved_area <= 0:
            return self._blocked(entry, "批准占道面积必须大于 0")
        if approved_area > applied_area:
            return self._blocked(entry, f"批准面积 {approved_area:g}㎡ 超出申请面积 {applied_area:g}㎡，不能放行")
        start = _parse_date(values.get("批准起始日") or values.get("申请起始日") or entry.get("申请起始日"))
        end = _parse_date(values.get("批准截止日") or values.get("申请截止日") or entry.get("申请截止日"))
        if start is None or end is None:
            return self._blocked(entry, "批准期限缺少批准起始日或批准截止日，不能放行")
        if end < start:
            return self._blocked(entry, "批准截止日早于批准起始日，批准期限不成立")
        entry["批准面积"] = approved_area
        entry["批准起始日"] = _iso(start)
        entry["批准截止日"] = _iso(end)
        entry["原始批准截止日"] = entry.get("原始批准截止日") or _iso(end)
        entry["批准日期"] = date.today().isoformat()
        if values.get("审批单位"):
            entry["审批单位"] = values.get("审批单位")
        if values.get("审批意见"):
            entry["审批意见"] = values.get("审批意见")
        return self._advance(entry, "已批准", "占道申请已审批通过")

    def _start_construction(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if entry.get("status") != "已批准":
            return self._blocked(entry, "只有已批准的占道申请才能开始施工")
        approved_area = _parse_area(entry.get("批准面积"))
        actual_area = _parse_area(values.get("实际占道面积"))
        if actual_area is None or actual_area <= 0:
            return self._blocked(entry, "开始施工需填报有效的实际占道面积")
        # 面积溢占：实际占道超过批准范围，不允许直接放行开工。
        if approved_area is not None and actual_area > approved_area + AREA_TOLERANCE:
            entry["实际占道面积"] = actual_area
            entry["abnormal"] = True
            return self._blocked(
                entry,
                f"实际占道面积 {actual_area:g}㎡ 超出批准面积 {approved_area:g}㎡，属面积溢占，不得直接开工",
            )
        entry["实际占道面积"] = actual_area
        start = _parse_date(values.get("施工开始日") or entry.get("批准起始日"))
        if start is None:
            return self._blocked(entry, "缺少施工开始日，不能开始施工")
        entry["施工开始日"] = _iso(start)
        return self._advance(entry, "施工中", "施工已开始，实际占道面积在批准范围内")

    def _apply_extension(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if entry.get("status") not in ("已批准", "施工中"):
            return self._blocked(entry, "只有已批准或施工中的占道申请才能申请延期")
        if any(ext.get("状态") == "待审批" for ext in entry.get("extensions", [])):
            return self._blocked(entry, "已有一条延期申请待审批，请先办结再发起新的延期")
        extend_to = _parse_date(values.get("延期至"))
        current_end = _parse_date(self._current_end(entry))
        if extend_to is None:
            return self._blocked(entry, "延期申请需填报延期截止日")
        if current_end is not None and extend_to <= current_end:
            return self._blocked(entry, "延期截止日必须晚于当前批准截止日")
        materials = self._split_materials(values.get("延期材料"))
        extension = {
            "序号": len(entry.get("extensions", [])) + 1,
            "延期至": _iso(extend_to),
            "延期事由": str(values.get("延期事由") or "").strip(),
            "延期材料": materials,
            "材料齐全": all(name in materials for name in EXTENSION_MATERIALS),
            "状态": "待审批",
            "申请日期": date.today().isoformat(),
            "批准日期": None,
            "审批意见": None,
        }
        entry.setdefault("extensions", []).append(extension)
        return self._detail(entry), f"延期申请已受理（编号 延期{extension['序号']}），等待审批"

    def _review_extension(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        pending = self._pending_extension(entry)
        if pending is None:
            return self._blocked(entry, "当前没有待审批的延期申请")
        decision = str(values.get("审批结果") or "批准").strip()
        extend_to = _parse_date(pending.get("延期至"))
        # 驳回不要求材料齐全，用于把材料不全的延期申请退回。
        if decision in ("驳回", "不予批准"):
            if extend_to is None:
                return self._blocked(entry, "延期截止日无效，无法审批")
            pending["状态"] = "已驳回"
            pending["批准日期"] = date.today().isoformat()
            pending["审批意见"] = str(values.get("审批意见") or "延期申请被驳回").strip()
            return self._detail(entry), f"延期{pending['序号']}已驳回，当前许可范围不变"
        # 批准延期时：材料不全不得直接放行，必须补齐材料后再审。
        if not pending.get("材料齐全"):
            missing = [name for name in EXTENSION_MATERIALS if name not in pending.get("延期材料", [])]
            return self._blocked(
                entry, f"延期材料不全（缺：{'、'.join(missing)}），不予放行，请补齐后重新提交审批"
            )
        if extend_to is None:
            return self._blocked(entry, "延期截止日无效，无法审批")
        pending["状态"] = "已批准"
        pending["批准日期"] = date.today().isoformat()
        pending["审批意见"] = str(values.get("审批意见") or "").strip() or "同意延期"
        entry["批准截止日"] = _iso(extend_to)  # 当前许可范围随之顺延
        return self._detail(entry), f"延期{pending['序号']}已批准，批准期限顺延至 {_iso(extend_to)}"

    def _finish_construction(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if entry.get("status") != "施工中":
            return self._blocked(entry, "只有施工中的占道申请才能确认撤场")
        start = _parse_date(entry.get("施工开始日"))
        end = _parse_date(values.get("施工结束日"))
        if end is None:
            return self._blocked(entry, "确认撤场需填报施工结束日")
        if start is not None and end < start:
            return self._blocked(entry, "施工结束日早于施工开始日，不能确认撤场")
        entry["施工结束日"] = _iso(end)
        # 撤场复测的实际占道面积若已溢占，先挂异常，竣工验收时统一拦截。
        measured = _parse_area(values.get("实际占道面积"))
        if measured is not None:
            entry["实际占道面积"] = measured
        scope = self._permit_scope(entry)
        entry["abnormal"] = bool(scope["是否溢占"]) or bool(end and self._is_overdue(entry, end))
        return self._advance(entry, "已撤场", "施工队伍已撤场，等待路面恢复")

    def _restore_surface(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if entry.get("status") != "已撤场":
            return self._blocked(entry, "只有已撤场的占道申请才能登记路面恢复")
        construction_end = _parse_date(entry.get("施工结束日"))
        restore_date = _parse_date(values.get("恢复日期"))
        if restore_date is None:
            return self._blocked(entry, "路面恢复需填报恢复日期")
        # 恢复日期早于施工结束：时间逻辑不成立，不得直接放行。
        if construction_end is not None and restore_date < construction_end:
            return self._blocked(
                entry,
                f"恢复日期 {_iso(restore_date)} 早于施工结束日 {_iso(construction_end)}，不能登记路面恢复",
            )
        entry["恢复日期"] = _iso(restore_date)
        entry["恢复情况"] = str(values.get("恢复情况") or "").strip() or "路面已按原状恢复"
        return self._advance(entry, "已恢复", "路面恢复已登记，等待竣工验收")

    def _accept(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if entry.get("status") != "已恢复":
            return self._blocked(entry, "只有已恢复的占道申请才能组织竣工验收")
        # 竣工验收对当前许可范围与恢复状态做一致性总校验，任一拦截项都不放行。
        blockers = [item for item in self._checks(entry) if item["级别"] == "拦截"]
        if blockers:
            return self._blocked(entry, "竣工验收不通过：" + "；".join(item["问题"] for item in blockers))
        restore_date = _parse_date(entry.get("恢复日期"))
        accept_date = _parse_date(values.get("验收日期"))
        if accept_date is None:
            return self._blocked(entry, "竣工验收需填报验收日期")
        if restore_date is not None and accept_date < restore_date:
            return self._blocked(entry, f"验收日期 {_iso(accept_date)} 早于恢复日期 {_iso(restore_date)}，不能验收")
        entry["验收日期"] = _iso(accept_date)
        entry["验收结论"] = str(values.get("验收结论") or "").strip() or "合格"
        entry["验收单位"] = str(values.get("验收单位") or "").strip()
        return self._advance(entry, "已验收", "竣工验收通过，许可范围与恢复状态一致")

    # ---------- 口径汇总：时间轴 / 审批详情 / 竣工验收共用 ----------
    def _current_end(self, entry: dict[str, Any]) -> str | None:
        """当前许可截止日：批准截止日会随已批准的延期顺延。"""
        approved_ends = [
            _parse_date(ext.get("延期至"))
            for ext in entry.get("extensions", [])
            if ext.get("状态") == "已批准"
        ]
        approved_ends = [d for d in approved_ends if d is not None]
        if approved_ends:
            return _iso(max(approved_ends))
        return entry.get("批准截止日")

    def _permit_scope(self, entry: dict[str, Any]) -> dict[str, Any]:
        approved_area = _parse_area(entry.get("批准面积"))
        actual_area = _parse_area(entry.get("实际占道面积"))
        overflow = (
            approved_area is not None
            and actual_area is not None
            and actual_area > approved_area + AREA_TOLERANCE
        )
        extensions = entry.get("extensions", [])
        return {
            "申请占道面积": _parse_area(entry.get("占道面积")),
            "批准面积": approved_area,
            "实际占道面积": actual_area,
            "批准起始日": entry.get("批准起始日"),
            "原始批准截止日": entry.get("原始批准截止日") or entry.get("批准截止日"),
            "当前批准截止日": self._current_end(entry),
            "延期次数": sum(1 for ext in extensions if ext.get("状态") == "已批准"),
            "待审批延期": any(ext.get("状态") == "待审批" for ext in extensions),
            "是否溢占": overflow,
        }

    def _restoration(self, entry: dict[str, Any]) -> dict[str, Any]:
        construction_end = _parse_date(entry.get("施工结束日"))
        restore_date = _parse_date(entry.get("恢复日期"))
        accept_date = _parse_date(entry.get("验收日期"))
        return {
            "施工结束日": entry.get("施工结束日"),
            "恢复日期": entry.get("恢复日期"),
            "验收日期": entry.get("验收日期"),
            "恢复情况": entry.get("恢复情况"),
            "验收结论": entry.get("验收结论"),
            "恢复日期早于施工结束": bool(
                construction_end and restore_date and restore_date < construction_end
            ),
            "验收日期早于恢复日期": bool(restore_date and accept_date and accept_date < restore_date),
        }

    def _checks(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        """许可范围与恢复状态的一致性检查；拦截项不放行，提示项只提醒。"""
        checks: list[dict[str, Any]] = []
        scope = self._permit_scope(entry)
        restoration = self._restoration(entry)

        if scope["是否溢占"]:
            checks.append({
                "级别": "拦截",
                "问题": f"实际占道面积 {scope['实际占道面积']:g}㎡ 超出批准面积 {scope['批准面积']:g}㎡（面积溢占）",
            })
        pending = self._pending_extension(entry)
        if pending is not None:
            missing = [n for n in EXTENSION_MATERIALS if n not in pending.get("延期材料", [])]
            if missing:
                checks.append({"级别": "拦截", "问题": f"延期{pending['序号']}材料不全，缺：{'、'.join(missing)}"})
            else:
                checks.append({"级别": "提示", "问题": f"延期{pending['序号']}正在审批，当前许可范围以审批结果为准"})
        if restoration["恢复日期早于施工结束"]:
            checks.append({
                "级别": "拦截",
                "问题": f"恢复日期 {restoration['恢复日期']} 早于施工结束日 {restoration['施工结束日']}",
            })
        if restoration["验收日期早于恢复日期"]:
            checks.append({
                "级别": "拦截",
                "问题": f"验收日期 {restoration['验收日期']} 早于恢复日期 {restoration['恢复日期']}",
            })
        construction_end = _parse_date(entry.get("施工结束日"))
        current_end = _parse_date(scope["当前批准截止日"])
        if construction_end and current_end and construction_end > current_end:
            checks.append({
                "级别": "提示",
                "问题": f"施工结束日 {_iso(construction_end)} 已超出当前批准期限 {_iso(current_end)}",
            })
        return checks

    def _timeline(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        """把占道申请、施工路段、占道面积、批准期限与恢复验收串成一条时间轴。"""
        status = entry.get("status")
        nodes: list[dict[str, Any]] = []

        nodes.append({
            "节点": "占道申请",
            "日期": entry.get("申请起始日") or entry.get("批准起始日"),
            "状态": "已完成",
            "内容": f"{entry.get('申请编号')}｜施工路段：{entry.get('施工路段')}｜申请占道面积："
                    f"{_fmt_area(_parse_area(entry.get('占道面积')))}㎡",
        })

        scope = self._permit_scope(entry)
        approved = status != "待审批" and entry.get("批准起始日")
        permit_state = "待处理"
        if approved:
            permit_state = "进行中" if status in ("已批准", "施工中") else "已完成"
        nodes.append({
            "节点": "批准期限",
            "日期": entry.get("批准起始日"),
            "状态": permit_state,
            "内容": f"{entry.get('批准起始日') or '—'} 至 {scope['当前批准截止日'] or '—'}"
                    f"｜批准面积 {_fmt_area(scope['批准面积'])}㎡｜审批单位：{entry.get('审批单位') or '—'}",
        })

        construction_state = "待处理"
        if entry.get("施工开始日"):
            construction_state = "进行中" if status == "施工中" else "已完成"
        overflow_mark = "（溢占）" if scope["是否溢占"] else ""
        nodes.append({
            "节点": "进场施工",
            "日期": entry.get("施工开始日"),
            "状态": construction_state,
            "内容": f"施工路段：{entry.get('施工路段')}｜实际占道面积："
                    f"{_fmt_area(scope['实际占道面积'])}㎡ / 批准 {_fmt_area(scope['批准面积'])}㎡{overflow_mark}",
        })

        for ext in entry.get("extensions", []):
            state_map = {"待审批": "进行中", "已批准": "已完成", "已驳回": "异常"}
            nodes.append({
                "节点": f"延期{ext.get('序号')}",
                "日期": ext.get("申请日期"),
                "状态": state_map.get(ext.get("状态"), "待处理"),
                "内容": f"申请延期至 {ext.get('延期至')}｜{ext.get('状态')}"
                        f"｜材料：{'、'.join(ext.get('延期材料', [])) or '未提交'}"
                        f"｜批准日期：{ext.get('批准日期') or '—'}",
            })

        nodes.append({
            "节点": "确认撤场",
            "日期": entry.get("施工结束日"),
            "状态": "已完成" if entry.get("施工结束日") else "待处理",
            "内容": f"施工结束日：{entry.get('施工结束日') or '—'}",
        })
        restoration = self._restoration(entry)
        nodes.append({
            "节点": "路面恢复",
            "日期": entry.get("恢复日期"),
            "状态": "异常" if restoration["恢复日期早于施工结束"] else (
                "已完成" if entry.get("恢复日期") else "待处理"
            ),
            "内容": f"恢复日期：{entry.get('恢复日期') or '—'}｜{entry.get('恢复情况') or '尚未恢复'}",
        })
        nodes.append({
            "节点": "竣工验收",
            "日期": entry.get("验收日期"),
            "状态": "已完成" if entry.get("验收日期") else "待处理",
            "内容": f"验收日期：{entry.get('验收日期') or '—'}｜验收结论：{entry.get('验收结论') or '待验收'}",
        })

        order = {"进行中": 0, "异常": 0, "已完成": 1, "待处理": 2}
        nodes.sort(key=lambda n: (n["日期"] is None, n["日期"] or "", order.get(n["状态"], 3)))
        return nodes

    # ---------- 组装与内部工具 ----------
    def _summary(self, entry: dict[str, Any]) -> dict[str, Any]:
        scope = self._permit_scope(entry)
        restoration = self._restoration(entry)
        return {
            **entry,
            "批准面积": scope["批准面积"],
            "实际占道面积": scope["实际占道面积"],
            "当前批准截止日": scope["当前批准截止日"],
            "延期次数": scope["延期次数"],
            "待审批延期": scope["待审批延期"],
            "是否溢占": scope["是否溢占"],
            "恢复日期": restoration["恢复日期"],
            "验收日期": restoration["验收日期"],
        }

    def _detail(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            **self._summary(entry),
            "permit_scope": self._permit_scope(entry),
            "restoration": self._restoration(entry),
            "checks": self._checks(entry),
            "timeline": self._timeline(entry),
        }

    def _pending_extension(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        for ext in entry.get("extensions", []):
            if ext.get("状态") == "待审批":
                return ext
        return None

    def _is_overdue(self, entry: dict[str, Any], day: date) -> bool:
        current_end = _parse_date(self._current_end(entry))
        return current_end is not None and day > current_end

    @staticmethod
    def _split_materials(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [part.strip() for part in re.split(r"[、,，;；\s]+", str(value)) if part.strip()]

    def _advance(self, entry: dict[str, Any], target: str, message: str) -> tuple[dict[str, Any], str]:
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        if target == STATUS_ORDER[-1]:
            entry["abnormal"] = False
        return self._detail(entry), message

    def _blocked(self, entry: dict[str, Any], message: str) -> tuple[dict[str, Any] | None, str]:
        """被拦下的动作：状态不动，按统一约定回 (None, 拦截原因) 给页面提示。"""
        return None, message
