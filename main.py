from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import json
import re
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Trendyol Rakip Takip API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────
# SCRAPERAPI — 403 engelini aşar
# ─────────────────────────────────────────
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "f6c9fda506d5d43ce78b46b287334e14")
SCRAPER_API_URL = "http://api.scraperapi.com"

def scraper_get(url: str, render_js: bool = False) -> requests.Response:
    """ScraperAPI üzerinden istek — Türkiye IP, bot engeli yok"""
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": url,
        "country_code": "tr",
        "render": "true" if render_js else "false",
    }
    response = requests.get(SCRAPER_API_URL, params=params, timeout=60)
    response.raise_for_status()
    return response


# ─────────────────────────────────────────
# VERİ MODELLERİ
# ─────────────────────────────────────────
class UrunEkle(BaseModel):
    url: str
    kullanici_id: str
    hedef_fiyat: float = None


# ─────────────────────────────────────────
# TRENDYOL SCRAPER
# ─────────────────────────────────────────
def trendyol_scrape(url: str) -> dict:
    """
    Trendyol ürün sayfasından veri çeker.
    ScraperAPI ile 403 engeli aşılır.
    """
    try:
        response = scraper_get(url, render_js=False)
        soup = BeautifulSoup(response.text, "html.parser")

        sonuc = {
            "url": url,
            "zaman": datetime.now().isoformat(),
            "basari": False,
        }

        # ── Ürün Adı ──
        urun_adi = None
        h1 = soup.find("h1", class_=re.compile("pr-new-br|product-name|pdp-product-name"))
        if h1:
            urun_adi = h1.get_text(strip=True)
        else:
            title_tag = soup.find("title")
            if title_tag:
                urun_adi = title_tag.get_text(strip=True).split("|")[0].strip()
        sonuc["urun_adi"] = urun_adi

        # ── Fiyat ──
        fiyat = None
        fiyat_el = soup.find("span", class_=re.compile("prc-dsc|product-price|price"))
        if fiyat_el:
            fiyat_str = fiyat_el.get_text(strip=True)
            fiyat_str = re.sub(r"[^\d,\.]", "", fiyat_str).replace(",", ".")
            try:
                fiyat = float(fiyat_str)
            except:
                pass

        # JSON-LD içinden fiyat dene
        if not fiyat:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and "offers" in data:
                        fiyat = float(data["offers"].get("price", 0))
                        break
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and "offers" in item:
                                fiyat = float(item["offers"].get("price", 0))
                                break
                except:
                    continue

        sonuc["fiyat"] = fiyat
        sonuc["para_birimi"] = "TL"

        # ── Satıcı ──
        satici = None
        satici_el = soup.find(class_=re.compile("merchant-text|seller-name|store-name|merchant"))
        if satici_el:
            satici = satici_el.get_text(strip=True)
        sonuc["satici"] = satici

        # ── Puan & Yorum ──
        puan = None
        yorum_sayisi = None

        puan_el = soup.find(class_=re.compile("ratingScore|rating-score|pr-rnr-sm-p"))
        if puan_el:
            try:
                puan = float(puan_el.get_text(strip=True).replace(",", "."))
            except:
                pass

        yorum_el = soup.find(class_=re.compile("ratingCount|review-count|pr-rnr-sm-c"))
        if yorum_el:
            yorum_str = re.sub(r"[^\d]", "", yorum_el.get_text(strip=True))
            try:
                yorum_sayisi = int(yorum_str)
            except:
                pass

        sonuc["puan"] = puan
        sonuc["yorum_sayisi"] = yorum_sayisi

        # ── Stok ──
        stok = "Belirsiz"
        stok_el = soup.find(class_=re.compile("sold-out|out-of-stock|stockAlert"))
        if stok_el:
            stok = "Tükendi"
        elif fiyat:
            stok = "Stokta"
        sonuc["stok_durumu"] = stok

        sonuc["basari"] = True if (urun_adi or fiyat) else False
        return sonuc

    except requests.exceptions.Timeout:
        return {"basari": False, "hata": "Bağlantı zaman aşımına uğradı.", "url": url}
    except requests.exceptions.HTTPError as e:
        return {"basari": False, "hata": f"HTTP hatası: {e}", "url": url}
    except Exception as e:
        return {"basari": False, "hata": str(e), "url": url}


# ─────────────────────────────────────────
# BUYBOX FIRSAT ANALİZİ
# ─────────────────────────────────────────
def buybox_analiz(kategori_url: str) -> dict:
    """Kategori sayfasında fırsat tarar"""
    try:
        response = scraper_get(kategori_url, render_js=False)
        soup = BeautifulSoup(response.text, "html.parser")

        firsatlar = []
        urun_kartlari = soup.find_all(class_=re.compile("p-card|product-card|prdct-cntnr"))

        for kart in urun_kartlari[:20]:
            try:
                ad_el = kart.find(class_=re.compile("name|title|prdct-desc"))
                fiyat_el = kart.find(class_=re.compile("prc-dsc|price|prdct-pr"))
                link_el = kart.find("a", href=True)
                yorum_el = kart.find(class_=re.compile("ratingCount|review|rnr"))

                ad = ad_el.get_text(strip=True) if ad_el else "Bilinmiyor"
                fiyat_str = re.sub(r"[^\d,]", "", fiyat_el.get_text(strip=True)) if fiyat_el else "0"
                fiyat = float(fiyat_str.replace(",", ".")) if fiyat_str else 0
                link = "https://www.trendyol.com" + link_el["href"] if link_el else ""
                yorum_str = re.sub(r"[^\d]", "", yorum_el.get_text(strip=True)) if yorum_el else "0"
                yorum = int(yorum_str) if yorum_str else 0

                firsat_skoru = 0
                if yorum > 100:
                    firsat_skoru += 2
                if yorum > 500:
                    firsat_skoru += 3
                if 50 < fiyat < 500:
                    firsat_skoru += 2

                firsatlar.append({
                    "urun_adi": ad,
                    "fiyat": fiyat,
                    "yorum_sayisi": yorum,
                    "firsat_skoru": firsat_skoru,
                    "url": link,
                })
            except:
                continue

        firsatlar.sort(key=lambda x: x["firsat_skoru"], reverse=True)

        return {
            "basari": True,
            "toplam_urun": len(firsatlar),
            "en_iyi_firsatlar": firsatlar[:5],
            "zaman": datetime.now().isoformat(),
        }

    except Exception as e:
        return {"basari": False, "hata": str(e)}


# ─────────────────────────────────────────
# API ENDPOINTLERİ
# ─────────────────────────────────────────

@app.get("/")
def anasayfa():
    return {
        "mesaj": "Trendyol Rakip Takip API çalışıyor ✅",
        "versiyon": "1.1.0",
        "scraperapi": "aktif",
        "endpointler": [
            "GET  /urun?url=TRENDYOL_URL",
            "POST /takip-ekle",
            "GET  /buybox?url=KATEGORI_URL",
            "GET  /saglik",
        ]
    }


@app.get("/urun")
def urun_sorgula(url: str):
    """Tek ürün fiyat ve bilgi sorgulama"""
    if "trendyol.com" not in url:
        raise HTTPException(status_code=400, detail="Geçerli bir Trendyol URL'si giriniz.")
    sonuc = trendyol_scrape(url)
    if not sonuc["basari"]:
        raise HTTPException(status_code=422, detail=sonuc.get("hata", "Veri çekilemedi."))
    return sonuc


@app.post("/takip-ekle")
def takip_ekle(istek: UrunEkle):
    """Kullanıcının takip listesine ürün ekler"""
    if "trendyol.com" not in istek.url:
        raise HTTPException(status_code=400, detail="Geçerli bir Trendyol URL'si giriniz.")
    sonuc = trendyol_scrape(istek.url)
    if not sonuc["basari"]:
        raise HTTPException(status_code=422, detail="Ürün bilgisi alınamadı.")
    kayit = {
        "kullanici_id": istek.kullanici_id,
        "url": istek.url,
        "urun_adi": sonuc.get("urun_adi"),
        "baslangic_fiyati": sonuc.get("fiyat"),
        "guncel_fiyat": sonuc.get("fiyat"),
        "hedef_fiyat": istek.hedef_fiyat,
        "eklenme_tarihi": datetime.now().isoformat(),
    }
    return {"basari": True, "mesaj": "Ürün takip listesine eklendi.", "urun": kayit}


@app.get("/buybox")
def buybox_firsat(url: str):
    """Kategori sayfasında BuyBox fırsatı analizi"""
    if "trendyol.com" not in url:
        raise HTTPException(status_code=400, detail="Geçerli bir Trendyol kategori URL'si giriniz.")
    sonuc = buybox_analiz(url)
    if not sonuc["basari"]:
        raise HTTPException(status_code=422, detail=sonuc.get("hata", "Analiz yapılamadı."))
    return sonuc


@app.get("/saglik")
def saglik_kontrolu():
    """API sağlık kontrolü"""
    return {"durum": "sağlıklı", "zaman": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
