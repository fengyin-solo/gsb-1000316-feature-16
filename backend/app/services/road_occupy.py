"""占道施工业务规则：申请、审批、延期、撤场、路面恢复与竣工验收都收在这里。

时间轴、审批详情、竣工验收三处展示的“当前许可范围 / 恢复状态”统一由本模块的
``detail`` 派生，避免各页面各算一份导致口径不一致。

放行红线（任一不满足都直接拦下，不允许状态继续流转）：
1. 实际占道面积超出批准占道面积（面积溢占）；
2. 延期审批时必备材料不全，或申请日已晚于当前批准结束日；
3. 路面恢复日期早于实际施工结束日；竣工验收时还要复核面积与恢复面积。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "road_occupy"

# 登记时必填；审批、施工等后续字段在对应动作里再校验
REQUIRED_FIELDS = ["申请编号", "施工路段", "申请占道面积", "申请开始日", "申请结束日"]
OPTIONAL_FIELDS = ["作业单位", "交通疏导方案", "审批单位"]

STATUS_ORDER = ["待审批", "已批准", "施工中", "已撤场", "已恢复", "已验收"]
# 主状态流转动作
ACTION_RULES = {"审批通过": "已批准", "开始施工": "施工中", "确认撤场": "已撤场", "登记恢复": "已恢复", "竣工验收": "已验收"}
# 延期是“挂在许可上的子流程”，不改变申请主状态
EXTENSION_ACTION = "申请延期"
EXTENSION_APPROVE = "延期批准"
EXTENSION_REJECT = "延期驳回"

# 延期申请必须随附的三份材料
EXTENSION_DOCS = ["延期申请书", "施工进度说明", "交通疏导调整方案"]


def _to_float(value: Any) -> float | None:
    """把 '120'、'120.5'、120 这类输入统一解析成面积数值；解析不了返回 None。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        return round(float(str(value).strip().replace("㎡", "").strip()), 2)
    except (TypeError, ValueError):
        return None


def _to_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


class RoadOccupyService:
    # ------------------------------------------------------------------ 查询
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
        return [self._list_row(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self.detail(entry)

    # ------------------------------------------------------------------ 登记
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        applied_area = _to_float(values.get("申请占道面积"))
        start_date = _to_date(values.get("申请开始日"))
        end_date = _to_date(values.get("申请结束日"))
        invalid: list[str] = []
        if applied_area is None or applied_area <= 0:
            invalid.append("申请占道面积（需为正数）")
        if start_date is None:
            invalid.append("申请开始日（格式 YYYY-MM-DD）")
        if end_date is None:
            invalid.append("申请结束日（格式 YYYY-MM-DD）")
        if start_date and end_date and end_date < start_date:
            invalid.append("申请结束日不能早于申请开始日")
        if invalid:
            return None, invalid

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["申请编号"] = str(values["申请编号"]).strip()
        entry["施工路段"] = str(values["施工路段"]).strip()
        entry["申请占道面积"] = applied_area
        entry["申请开始日"] = _iso(start_date)
        entry["申请结束日"] = _iso(end_date)
        for field in OPTIONAL_FIELDS:
            entry[field] = str(values.get(field) or "").strip() or None
        # 审批与现场信息登记后逐步补齐
        entry.update({
            "批准占道面积": None, "批准开始日": None, "批准结束日": None,
            "实际占道面积": None, "实际开始日": None, "实际结束日": None,
            "延期记录": [],
            "恢复日期": None, "恢复面积": None, "恢复方式": None,
            "验收日期": None, "验收人": None, "验收意见": None,
        })
        rows.append(entry)
        return self.detail(entry), []

    # ------------------------------------------------------------------ 动作
    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"占道申请 {entry_id} 不存在或已归档"
        values = values or {}

        if action == EXTENSION_ACTION:
            message = self._apply_extension(entry, values)
        elif action == EXTENSION_APPROVE:
            message = self._approve_extension(entry, values, reject=False)
        elif action == EXTENSION_REJECT:
            message = self._approve_extension(entry, values, reject=True)
        elif action in ACTION_RULES:
            message = self._advance_status(entry, action, values)
        else:
            return None, f"动作「{action}」不属于占道施工可执行范围"

        if message:
            return None, message
        self._refresh_flags(entry)
        return self.detail(entry), f"占道申请已{action}"

    # ---------------------------------------------------------- 主状态流转
    def _advance_status(self, entry: dict[str, Any], action: str, values: dict[str, Any]) -> str:
        target = ACTION_RULES[action]
        current = str(entry.get("status"))
        expected_index = STATUS_ORDER.index(target) - 1
        if STATUS_ORDER.index(current) != expected_index:
            return f"当前状态为「{current}」，不能执行「{action}」，请按 {('→'.join(STATUS_ORDER))} 的顺序流转"

        if action == "审批通过":
            return self._do_approve(entry, values)
        if action == "开始施工":
            return self._do_start(entry, values)
        if action == "确认撤场":
            return self._do_withdraw(entry, values)
        if action == "登记恢复":
            return self._do_restore(entry, values)
        if action == "竣工验收":
            return self._do_accept(entry, values)
        return f"动作「{action}」缺少处理逻辑"

    def _do_approve(self, entry: dict[str, Any], values: dict[str, Any]) -> str:
        approved_area = _to_float(values.get("批准占道面积"))
        start_date = _to_date(values.get("批准开始日"))
        end_date = _to_date(values.get("批准结束日"))
        approver = str(values.get("审批单位") or entry.get("审批单位") or "").strip()
        problems: list[str] = []
        if approved_area is None or approved_area <= 0:
            problems.append("批准占道面积（需为正数）")
        if start_date is None:
            problems.append("批准开始日")
        if end_date is None:
            problems.append("批准结束日")
        if start_date and end_date and end_date < start_date:
            problems.append("批准结束日不能早于批准开始日")
        if not approver:
            problems.append("审批单位")
        if problems:
            return "审批信息不完整：" + "、".join(problems)
        entry["批准占道面积"] = approved_area
        entry["批准开始日"] = _iso(start_date)
        entry["批准结束日"] = _iso(end_date)
        entry["审批单位"] = approver
        entry["status"] = "已批准"
        return ""

    def _do_start(self, entry: dict[str, Any], values: dict[str, Any]) -> str:
        actual_area = _to_float(values.get("实际占道面积"))
        start_date = _to_date(values.get("实际开始日"))
        problems: list[str] = []
        if actual_area is None or actual_area <= 0:
            problems.append("实际占道面积（需为正数）")
        if start_date is None:
            problems.append("实际开始日")
        if problems:
            return "开工信息不完整：" + "、".join(problems)

        approved_area = _to_float(entry.get("批准占道面积")) or 0.0
        permit_end = _to_date(entry.get("批准结束日"))
        # 红线 1：面积溢占，不得直接放行开工
        if actual_area > approved_area:
            overflow = round(actual_area - approved_area, 2)
            return (
                f"面积溢占：实际占道 {actual_area} ㎡ 超出批准范围 {approved_area} ㎡（溢占 {overflow} ㎡），"
                "不得开工放行，请压缩占用范围或先行办理许可变更"
            )
        # 批准期限约束：批准期限已过又没办延期，不能开工
        if permit_end and start_date > permit_end:
            return f"实际开工日 {start_date} 已晚于批准期限 {permit_end}，请先办理延期再开工"
        entry["实际占道面积"] = actual_area
        entry["实际开始日"] = _iso(start_date)
        entry["status"] = "施工中"
        return ""

    def _do_withdraw(self, entry: dict[str, Any], values: dict[str, Any]) -> str:
        end_date = _to_date(values.get("实际结束日"))
        if end_date is None:
            return "撤场信息不完整：实际结束日"
        start_date = _to_date(entry.get("实际开始日"))
        if start_date and end_date < start_date:
            return f"实际结束日 {end_date} 不能早于实际开工日 {start_date}"
        # 撤场时可复核实测面积（施工过程中可能扩大占用），有填写就更新口径
        remeasure = _to_float(values.get("实际占道面积"))
        if remeasure is not None and remeasure > 0:
            entry["实际占道面积"] = remeasure
        # 红线 1：带溢占撤场同样属于违规放行
        permit = self._permit(entry)
        if permit["面积溢占"]:
            return (
                f"面积溢占 {permit['溢占面积']} ㎡ 尚未处置，不得确认撤场放行；"
                "请先补办许可变更并结清溢占部分"
            )
        entry["实际结束日"] = _iso(end_date)
        entry["status"] = "已撤场"
        return ""

    def _do_restore(self, entry: dict[str, Any], values: dict[str, Any]) -> str:
        restore_date = _to_date(values.get("恢复日期"))
        restore_area = _to_float(values.get("恢复面积"))
        method = str(values.get("恢复方式") or "").strip()
        problems: list[str] = []
        if restore_date is None:
            problems.append("路面恢复日期")
        if restore_area is None or restore_area <= 0:
            problems.append("恢复面积（需为正数）")
        if not method:
            problems.append("恢复方式")
        if problems:
            return "恢复信息不完整：" + "、".join(problems)

        construction_end = _to_date(entry.get("实际结束日"))
        # 红线 3：恢复日期早于施工结束，工程还没结束谈不上恢复，不得登记放行
        if construction_end and restore_date < construction_end:
            return (
                f"路面恢复日期 {restore_date} 早于实际施工结束日 {construction_end}，"
                "时间逻辑不成立，不得登记路面恢复"
            )
        entry["恢复日期"] = _iso(restore_date)
        entry["恢复面积"] = restore_area
        entry["恢复方式"] = method
        entry["status"] = "已恢复"
        return ""

    def _do_accept(self, entry: dict[str, Any], values: dict[str, Any]) -> str:
        accept_date = _to_date(values.get("验收日期"))
        acceptor = str(values.get("验收人") or "").strip()
        opinion = str(values.get("验收意见") or "合格").strip() or "合格"
        problems: list[str] = []
        if accept_date is None:
            problems.append("验收日期")
        if not acceptor:
            problems.append("验收人")
        if problems:
            return "验收信息不完整：" + "、".join(problems)

        # 竣工验收统一复核三条红线，保证验收结论与许可范围、恢复状态一致
        permit = self._permit(entry)
        restoration = self._restoration(entry)
        if permit["面积溢占"]:
            return f"竣工验收不通过：实际占道溢占 {permit['溢占面积']} ㎡，超出当前许可范围，不得放行结案"
        if restoration["日期合规"] is False:
            return (
                f"竣工验收不通过：路面恢复日期 {entry.get('恢复日期')} "
                f"早于施工结束日 {entry.get('实际结束日')}，恢复状态存疑"
            )
        approved_area = _to_float(entry.get("批准占道面积")) or 0.0
        restore_area = _to_float(entry.get("恢复面积")) or 0.0
        if restore_area < approved_area:
            return (
                f"竣工验收不通过：路面恢复面积 {restore_area} ㎡ 小于批准占道面积 {approved_area} ㎡，"
                "恢复范围未覆盖许可占用范围"
            )
        entry["验收日期"] = _iso(accept_date)
        entry["验收人"] = acceptor
        entry["验收意见"] = opinion
        entry["status"] = "已验收"
        return ""

    # ---------------------------------------------------------- 延期子流程
    def _apply_extension(self, entry: dict[str, Any], values: dict[str, Any]) -> str:
        current = str(entry.get("status"))
        if current not in ("已批准", "施工中"):
            return f"当前状态为「{current}」，只有已批准或施工中的许可可以申请延期"
        if any(rec.get("状态") == "待审批" for rec in entry.get("延期记录", [])):
            return "上一条延期申请尚未审批办结，不能重复提交"

        new_end = _to_date(values.get("申请延至日"))
        reason = str(values.get("延期原因") or "").strip()
        docs = values.get("延期材料") or []
        if isinstance(docs, str):
            docs = [item.strip() for item in docs.replace("，", "、").split("、") if item.strip()]
        docs = [str(item).strip() for item in docs if str(item).strip()]

        problems: list[str] = []
        if new_end is None:
            problems.append("申请延至日")
        if not reason:
            problems.append("延期原因")
        if problems:
            return "延期申请不完整：" + "、".join(problems)

        current_end = _to_date(entry.get("批准结束日"))
        if current_end and new_end <= current_end:
            return f"申请延至日 {new_end} 必须晚于当前批准结束日 {current_end}"

        records = entry.setdefault("延期记录", [])
        records.append({
            "序号": len(records) + 1,
            "申请日": str(date.today()),
            "原结束日": entry.get("批准结束日"),
            "申请延至日": _iso(new_end),
            "延期原因": reason,
            "延期材料": docs,
            "材料齐全": all(doc in docs for doc in EXTENSION_DOCS),
            "缺失材料": [doc for doc in EXTENSION_DOCS if doc not in docs],
            "状态": "待审批",
            "批准结束日": None,
            "审批意见": None,
        })
        return ""

    def _approve_extension(self, entry: dict[str, Any], values: dict[str, Any], *, reject: bool) -> str:
        records: list[dict[str, Any]] = entry.get("延期记录", [])
        pending = [rec for rec in records if rec.get("状态") == "待审批"]
        if not pending:
            return "没有待审批的延期申请"
        index = _to_float(values.get("延期序号"))
        target = pending[-1]
        if index is not None:
            for rec in pending:
                if int(rec.get("序号", 0)) == int(index):
                    target = rec
                    break

        opinion = str(values.get("审批意见") or "").strip()
        if reject:
            target["状态"] = "已驳回"
            target["审批意见"] = opinion or "延期申请被驳回"
            return ""

        # 红线 2：材料不全 / 申请超期，延期不得放行；许可结束日保持不变
        if not target.get("材料齐全"):
            missing = "、".join(target.get("缺失材料") or [])
            return f"延期材料不全（缺少：{missing}），第 {target['序号']} 次延期不予批准放行"
        applied_day = _to_date(target.get("申请日"))
        original_end = _to_date(target.get("原结束日"))
        if original_end and applied_day and applied_day > original_end:
            return f"延期申请日 {applied_day} 已晚于原批准结束日 {original_end}，属于逾期申请，不予批准"

        new_end = _to_date(values.get("批准结束日")) or _to_date(target.get("申请延至日"))
        if new_end is None:
            return "延期审批不完整：批准结束日"
        target["状态"] = "已批准"
        target["批准结束日"] = _iso(new_end)
        target["审批意见"] = opinion or "同意延期"
        # 当前许可范围的结束日随延期同步顺延——时间轴与审批详情都读这一份
        entry["批准结束日"] = _iso(new_end)
        return ""

    # ---------------------------------------------------------- 派生口径
    def _permit(self, entry: dict[str, Any]) -> dict[str, Any]:
        """当前许可范围：面积口径与批准期限（含已批准的延期）。"""
        applied = _to_float(entry.get("申请占道面积"))
        approved = _to_float(entry.get("批准占道面积"))
        actual = _to_float(entry.get("实际占道面积"))
        overflow_area = round(actual - approved, 2) if (actual is not None and approved is not None and actual > approved) else 0.0
        overflow = overflow_area > 0
        if overflow:
            scope_text = f"溢占 {overflow_area} ㎡（实际 {actual} / 批准 {approved}）"
        elif approved is not None:
            scope_text = f"许可范围内（批准 {approved} ㎡）"
        else:
            scope_text = f"待审批（申请 {applied} ㎡）"
        return {
            "申请占道面积": applied,
            "批准占道面积": approved,
            "实际占道面积": actual,
            "溢占面积": overflow_area,
            "面积溢占": overflow,
            "申请开始日": entry.get("申请开始日"),
            "申请结束日": entry.get("申请结束日"),
            "批准开始日": entry.get("批准开始日"),
            "批准结束日": entry.get("批准结束日"),
            "许可范围说明": scope_text,
        }

    def _restoration(self, entry: dict[str, Any]) -> dict[str, Any]:
        """路面恢复与竣工验收状态。"""
        construction_end = _to_date(entry.get("实际结束日"))
        restore_date = _to_date(entry.get("恢复日期"))
        date_ok: bool | None = None
        issue = ""
        if restore_date and construction_end:
            date_ok = restore_date >= construction_end
            if not date_ok:
                issue = f"恢复日期 {restore_date} 早于施工结束日 {construction_end}"

        status_text = "未恢复"
        if entry.get("status") == "已验收":
            status_text = f"验收{entry.get('验收意见') or '合格'}"
        elif restore_date is not None:
            status_text = "已恢复，待竣工验收"
        elif construction_end is not None:
            status_text = "已撤场，待路面恢复"
        return {
            "实际结束日": entry.get("实际结束日"),
            "恢复日期": entry.get("恢复日期"),
            "恢复面积": _to_float(entry.get("恢复面积")),
            "恢复方式": entry.get("恢复方式"),
            "恢复状态": status_text,
            "日期合规": date_ok,
            "异常提示": issue,
            "验收日期": entry.get("验收日期"),
            "验收人": entry.get("验收人"),
            "验收意见": entry.get("验收意见"),
        }

    def _approval(self, entry: dict[str, Any]) -> dict[str, Any]:
        """审批详情：初始批复叠加历次延期，给出当前有效的许可期限。"""
        records = entry.get("延期记录", [])
        return {
            "审批单位": entry.get("审批单位"),
            "批准占道面积": _to_float(entry.get("批准占道面积")),
            "批准开始日": entry.get("批准开始日"),
            "批准结束日": entry.get("批准结束日"),
            "延期次数": len(records),
            "已批准延期次数": sum(1 for rec in records if rec.get("状态") == "已批准"),
            "待审批延期次数": sum(1 for rec in records if rec.get("状态") == "待审批"),
            "延期记录": records,
        }

    def _timeline(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        """把占道申请、施工路段、占道面积、批准期限串成同一条时间轴。"""
        permit = self._permit(entry)
        restoration = self._restoration(entry)
        current = str(entry.get("status"))
        current_key = {
            "待审批": "apply", "已批准": "approve", "施工中": "construct",
            "已撤场": "withdraw", "已恢复": "restore", "已验收": "accept",
        }.get(current, "apply")

        nodes: list[dict[str, Any]] = []

        def add(key: str, when: str | None, title: str, desc: str, *, abnormal: bool = False,
                blocked_reason: str = "", state_override: str | None = None) -> None:
            if state_override:
                state = state_override
            elif when is None and not blocked_reason:
                state = "pending"
            elif blocked_reason:
                state = "blocked"
            elif key == current_key and current != STATUS_ORDER[-1]:
                state = "current"
            else:
                state = "done"
            nodes.append({
                "节点": key, "日期": when or "待发生", "标题": title,
                "描述": desc, "状态": state, "异常": abnormal, "阻断原因": blocked_reason,
            })

        seg = str(entry.get("施工路段") or "—")
        add(
            "apply", entry.get("申请开始日"), "占道申请登记",
            f"施工路段：{seg}｜申请占道 {permit['申请占道面积']} ㎡｜"
            f"申请期限 {entry.get('申请开始日') or '—'} ~ {entry.get('申请结束日') or '—'}",
        )
        add(
            "approve", entry.get("批准开始日"), "审批通过",
            f"审批单位：{entry.get('审批单位') or '—'}｜批准占道 {permit['批准占道面积'] or '—'} ㎡｜"
            f"批准期限 {entry.get('批准开始日') or '—'} ~ {entry.get('批准结束日') or '—'}",
        )

        construct_desc = (
            f"实际开工 {entry.get('实际开始日') or '—'}｜实际占道 {permit['实际占道面积'] or '—'} ㎡"
        )
        add("construct", entry.get("实际开始日"), "开始施工", construct_desc,
            abnormal=permit["面积溢占"],
            blocked_reason=f"面积溢占 {permit['溢占面积']} ㎡，开工放行已被红线拦截" if current == "已批准" and permit["面积溢占"] else "")

        for rec in entry.get("延期记录", []):
            reason = ""
            abnormal = False
            state_day = rec.get("申请日")
            if rec.get("状态") == "待审批" and not rec.get("材料齐全"):
                reason = "延期材料不全（缺少：" + "、".join(rec.get("缺失材料") or []) + "），不予放行"
            elif rec.get("状态") == "已驳回":
                abnormal = True
            desc = (
                f"原结束日 {rec.get('原结束日')} → 申请延至 {rec.get('申请延至日')}｜"
                f"事由：{rec.get('延期原因')}｜材料：{'齐全' if rec.get('材料齐全') else '不全'}｜"
                f"结果：{rec.get('状态')}"
                + (f"，批准至 {rec.get('批准结束日')}" if rec.get("批准结束日") else "")
            )
            ext_state: str | None = None
            if reason and current in ("已批准", "施工中"):
                ext_state = "blocked"
            elif rec.get("状态") == "待审批" and current in ("已批准", "施工中"):
                ext_state = "current"
            add(f"extension-{rec.get('序号')}", state_day, f"第 {rec.get('序号')} 次延期", desc,
                abnormal=abnormal, blocked_reason=reason, state_override=ext_state)

        add(
            "withdraw", entry.get("实际结束日"), "确认撤场",
            f"实际施工结束 {entry.get('实际结束日') or '—'}",
            blocked_reason=f"面积溢占 {permit['溢占面积']} ㎡ 未处置，撤场放行被拦截"
            if current == "施工中" and permit["面积溢占"] else "",
        )
        add(
            "restore", entry.get("恢复日期"), "路面恢复",
            f"恢复日期 {entry.get('恢复日期') or '—'}｜恢复面积 {restoration['恢复面积'] or '—'} ㎡｜"
            f"方式：{entry.get('恢复方式') or '—'}",
            abnormal=restoration["日期合规"] is False,
            blocked_reason=restoration["异常提示"] if restoration["日期合规"] is False and current == "已撤场" else "",
        )
        accept_blocks: list[str] = []
        if permit["面积溢占"]:
            accept_blocks.append(f"面积溢占 {permit['溢占面积']} ㎡")
        if restoration["日期合规"] is False:
            accept_blocks.append("恢复日期早于施工结束日")
        add(
            "accept", entry.get("验收日期"), "竣工验收",
            f"验收日期 {entry.get('验收日期') or '—'}｜验收人 {entry.get('验收人') or '—'}｜"
            f"意见：{entry.get('验收意见') or '待验收'}",
            blocked_reason="；".join(accept_blocks)
            + ("，竣工验收不得放行" if accept_blocks and current in ("已撤场", "已恢复") else ""),
        )
        return nodes

    def detail(self, entry: dict[str, Any]) -> dict[str, Any]:
        """审批详情、时间轴、竣工验收共用同一份入口数据，口径天然一致。"""
        result = dict(entry)
        result["许可范围"] = self._permit(entry)
        result["审批详情"] = self._approval(entry)
        result["恢复信息"] = self._restoration(entry)
        result["时间轴"] = self._timeline(entry)
        result["占道状态"] = self._status_text(entry)
        return result

    def _status_text(self, entry: dict[str, Any]) -> str:
        permit = self._permit(entry)
        parts = [str(entry.get("status"))]
        if permit["面积溢占"]:
            parts.append(f"面积溢占{permit['溢占面积']}㎡")
        pending_ext = sum(1 for rec in entry.get("延期记录", []) if rec.get("状态") == "待审批")
        if pending_ext:
            parts.append(f"{pending_ext}条延期待审批")
        if entry.get("status") == "已撤场":
            parts.append("待路面恢复")
        if entry.get("status") == "已恢复":
            parts.append("待竣工验收")
        return "·".join(parts)

    def _list_row(self, entry: dict[str, Any]) -> dict[str, Any]:
        permit = self._permit(entry)
        if permit["实际占道面积"] is not None:
            area_text = f"实际 {permit['实际占道面积']} / 批准 {permit['批准占道面积']} ㎡"
        elif permit["批准占道面积"] is not None:
            area_text = f"批准 {permit['批准占道面积']}（申请 {permit['申请占道面积']}）㎡"
        else:
            area_text = f"申请 {permit['申请占道面积']} ㎡"
        if entry.get("批准结束日"):
            period = f"{entry.get('批准开始日') or '—'} ~ {entry.get('批准结束日')}（含延期）"
        else:
            period = f"{entry.get('申请开始日') or '—'} ~ {entry.get('申请结束日') or '—'}（申请）"
        return {
            "id": entry.get("id"),
            "status": entry.get("status"),
            "申请编号": entry.get("申请编号"),
            "施工路段": entry.get("施工路段"),
            "占道面积": area_text,
            "占道起止日": period,
            "作业单位": entry.get("作业单位"),
            "交通疏导": entry.get("交通疏导方案"),
            "审批单位": entry.get("审批单位"),
            "占道状态": self._status_text(entry),
            "面积溢占": permit["面积溢占"],
            "待延期审批": sum(1 for rec in entry.get("延期记录", []) if rec.get("状态") == "待审批"),
        }

    def _refresh_flags(self, entry: dict[str, Any]) -> None:
        permit = self._permit(entry)
        entry["abnormal"] = permit["面积溢占"] or any(
            rec.get("状态") == "已驳回" for rec in entry.get("延期记录", [])
        )
        entry["pending"] = entry.get("status") != "已验收"
