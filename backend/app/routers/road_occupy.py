"""占道施工接口：占道申请的登记、审批、延期、路面恢复与竣工验收闭环。

审批放行规则只在 service 里判断；路由层负责把动作参数透传下去，
并把「不得直接放行」的拦截原因通过 ActionResult.ok=False 返回给页面。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.road_occupy import STATUS_ORDER, RoadOccupyService

router = APIRouter(prefix="/api/road_occupy", tags=["占道施工"])

service = RoadOccupyService()

LIST_FIELDS = ["申请编号", "施工路段", "占道面积", "批准面积", "实际占道面积", "当前批准截止日",
               "延期次数", "恢复日期", "验收日期", "占道状态"]
STATUSES = STATUS_ORDER


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按申请编号检索"),
    status: str | None = Query(default=None, description="待审批、已批准、施工中、已撤场、已恢复、已验收"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按申请编号与状态过滤占道施工列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出占道施工清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "road_occupy", "total": total, "items": items}


@router.get("/{entry_id}/timeline", response_model=dict)
def get_timeline(entry_id: int) -> dict[str, Any]:
    """读取占道时间轴：申请、批准期限、施工、延期、恢复、验收按日期串好，
    并回当前许可范围、恢复状态与一致性检查结果。"""
    result = service.timeline(entry_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"占道申请 {entry_id} 不存在或已归档")
    return result


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict[str, Any]:
    """读取单条占道申请明细（含时间轴、许可范围、恢复状态与检查项）；不存在时给出可读错误。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"占道申请 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条占道申请，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="占道申请已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条占道申请执行审批、开工、延期、撤场、恢复、验收等动作。

    面积溢占、延期材料不全、恢复日期早于施工结束等情况不会放行，
    返回 ok=False 并在 message 里说明拦截原因。
    """
    action = str(payload.values.get("action") or "").strip()
    action_values = {k: v for k, v in payload.values.items() if k != "action"}
    entry, message = service.run_action(entry_id, action, action_values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
