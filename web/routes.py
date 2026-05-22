from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates


router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="web/templates")


@router.get("/")
def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"title": "检测队列仪表盘"})


@router.get("/orders")
def orders(request: Request):
    return templates.TemplateResponse(request, "orders.html", {"title": "订单管理"})


@router.get("/queue")
def queue(request: Request):
    return templates.TemplateResponse(request, "queue.html", {"title": "队列与排程"})


@router.get("/knowledge")
def knowledge(request: Request):
    return templates.TemplateResponse(request, "knowledge.html", {"title": "知识库检索"})


@router.get("/agents")
def agents(request: Request):
    return templates.TemplateResponse(request, "agents.html", {"title": "Agent 执行轨迹"})


@router.get("/notifications")
def notifications(request: Request):
    return templates.TemplateResponse(request, "notifications.html", {"title": "员工通知"})
