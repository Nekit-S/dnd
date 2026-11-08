import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from aidm.config.settings import Settings
from aidm.ledger.ledger import Ledger
from aidm.store.campaign import CampaignStore, row_to_record
from aidm.web.access import host_only

router = APIRouter(prefix="/dev", dependencies=[Depends(host_only)])


def _render(request: Request, name: str, **ctx: object) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, name, ctx)


def _tree(by_category: dict[str, tuple[int, Decimal]]) -> dict[str, tuple[int, Decimal]]:
    """Суммы по каждому префиксу пути категории: generation, generation/plot, ..."""
    out: dict[str, tuple[int, Decimal]] = {}
    for path, (attempts, cost) in by_category.items():
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            key = "/".join(parts[:i])
            a, c = out.get(key, (0, Decimal(0)))
            out[key] = (a + attempts, c + cost)
    return dict(sorted(out.items()))


@router.get("/ledger", response_class=HTMLResponse)
def ledger_page(request: Request) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    ledger = Ledger(settings.ledger_path)
    rows = ledger.rows(200)
    summary = ledger.summary_by_category()
    tree = _tree({k: (v.attempts, v.cost) for k, v in summary.items()})
    scopes = {s: ledger.spend(scope=s) for s in ("campaign", "test", "app")}
    campaigns = {
        cid: ledger.spend(campaign_id=cid)
        for cid in sorted({r.campaign_id for r in rows if r.campaign_id})
    }
    return _render(
        request, "dev/ledger.html", rows=rows, tree=tree, scopes=scopes, campaigns=campaigns
    )


@router.get("/campaigns", response_class=HTMLResponse)
def campaigns_page(request: Request) -> HTMLResponse:
    campaigns = [c for c in CampaignStore.list_campaigns(request.app.state.settings) if c.is_test]
    return _render(request, "dev/campaigns.html", campaigns=campaigns)


@router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
def campaign_page(request: Request, campaign_id: str) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    # Ищем по списку, а не по пути из URL: так id не может выйти из папки кампаний
    info = next((c for c in CampaignStore.list_campaigns(settings) if c.id == campaign_id), None)
    if info is None:
        raise HTTPException(status_code=404, detail="Кампания не найдена")
    if not info.is_test:
        raise HTTPException(status_code=403, detail="Эта кампания не тестовая")
    with CampaignStore.open(settings, campaign_id) as store:
        records = [
            row_to_record(r) for r in store.conn.execute("SELECT * FROM records ORDER BY kind, id")
        ]
    shown = [(r, json.dumps(r.data, ensure_ascii=False, indent=2)) for r in records]
    return _render(request, "dev/campaign.html", info=info, records=shown)
