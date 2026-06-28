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


@router.get("/execution")
def execution(request: Request):
    return templates.TemplateResponse(request, "execution.html", {"title": "执行看板"})


@router.get("/events")
def events(request: Request):
    return templates.TemplateResponse(request, "events.html", {"title": "事件中心"})


@router.get("/notifications")
def notifications(request: Request):
    return templates.TemplateResponse(request, "notifications.html", {"title": "员工通知"})


@router.get("/audit")
def audit(request: Request):
    return templates.TemplateResponse(request, "audit.html", {"title": "审计日志"})
