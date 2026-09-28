"""占道施工接口：占道申请登记、审批、开工、延期、撤场、路面恢复与竣工验收。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.road_occupy import RoadOccupyService

router = APIRouter(prefix="/api/road_occupy", tags=["占道施工"])

service = RoadOccupyService()

LIST_FIELDS = ["申请编号", "施工路段", "占道面积", "占道起止日", "作业单位", "交通疏导", "审批单位", "占道状态"]
STATUSES = ["待审批", "已批准", "施工中", "已撤场", "已恢复", "已验收"]


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


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条占道申请明细：含当前许可范围、审批详情、延期记录、恢复状态与时间轴。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"占道申请 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条占道申请，缺字段或日期/面积不合法时说明原因而不是静默丢弃。"""
    entry, problems = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message=f"占道申请无法登记：{'、'.join(problems)}")
    return ActionResult(ok=True, message="占道申请已登记，进入待审批", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """审批通过、开始施工、申请延期、延期批准/驳回、确认撤场、登记恢复、竣工验收。

    动作名与业务参数统一放在 ``values`` 里；触发红线（面积溢占、延期材料不全、
    恢复日期早于施工结束等）时以 ``ok=false`` 返回可读原因，状态不发生流转。
    """
    values = dict(payload.values or {})
    action = str(values.pop("action", "") or "").strip()
    if not action:
        return ActionResult(ok=False, message="缺少 action，未执行任何动作")
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
