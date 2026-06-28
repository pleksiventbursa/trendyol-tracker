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
# HEADERS — Trendyol botu engellemez
# ─────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.trendyol.com",
}


# ─────────────────────────────────────────
# VERİ MODELLERİ
# ─────────────────────────────────────────
class UrunEkle(BaseModel):
    url: str
    kullanici_id: str
    hedef_fiyat: float = None  # Kullanıcı bu fiyata düşünce bildir


class UrunSonuc(BaseModel):
    basari: bool
    urun_adi: str = None
    fiyat: float = None
    para_birimi: str = "TL"
    satici: str = None
    yorum_sayisi: int = None
    puan: float = None
    stok_durumu: str = None
    url: str = None
    zaman: str = None
    hata: str = None


# ─────────────────────────────────────────
# TRENDYOL SCRAPER
# ─────────────────────────────────────────
def trendyol_scrape(url: str) -> dict:
    """
    Trendyol ürün sayfasından veri çeker.
    Fiyat, satıcı, puan, yorum sayısı döndürür.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
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

        # JSON-LD içinden fiyat çekmeyi dene
        if not fiyat:
            scripts = soup.find_all("script", type="application/ld+json")
            for script in scripts:
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
        satici_el = soup.find("a", class_=re.compile("merchant-text|seller-name|store-name"))
        if not satici_el:
            satici_el = soup.find(class_=re.compile("merchant"))
        if satici_el:
            satici = satici_el.get_text(strip=True)
        sonuc["satici"] = satici

        # ── Puan & Yorum Sayısı ──
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

        # ── Stok Durumu ──
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
# BUYBOx FIRSAT ANALİZİ
# ─────────────────────────────────────────
def buybox_analiz(kategori_url: str) -> dict:
    """
    Kategori sayfasındaki ürünleri tarar.
    Az satıcılı, yüksek yorumlu, fiyat marjı uygun ürünleri bulur.
    """
    try:
        response = requests.get(kategori_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        firsatlar = []
        urun_kartlari = soup.find_all(class_=re.compile("p-card|product-card|prdct-cntnr"))

        for kart in urun_kartlari[:20]:  # İlk 20 ürün
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

                # Fırsat skoru: yüksek yorum + makul fiyat = fırsat
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

        # Fırsat skoruna göre sırala
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
        "versiyon": "1.0.0",
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
    """
    Kullanıcının takip listesine ürün ekler.
    Supabase entegrasyonu ile çalışır.
    """
    if "trendyol.com" not in istek.url:
        raise HTTPException(status_code=400, detail="Geçerli bir Trendyol URL'si giriniz.")

    # Önce mevcut fiyatı çek
    sonuc = trendyol_scrape(istek.url)
    if not sonuc["basari"]:
        raise HTTPException(status_code=422, detail="Ürün bilgisi alınamadı.")

    # Supabase'e kaydet (entegrasyon hazır olduğunda aktif edilecek)
    kayit = {
        "kullanici_id": istek.kullanici_id,
        "url": istek.url,
        "urun_adi": sonuc.get("urun_adi"),
        "baslangic_fiyati": sonuc.get("fiyat"),
        "guncel_fiyat": sonuc.get("fiyat"),
        "hedef_fiyat": istek.hedef_fiyat,
        "eklenme_tarihi": datetime.now().isoformat(),
    }

    return {
        "basari": True,
        "mesaj": "Ürün takip listesine eklendi.",
        "urun": kayit,
    }


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
    """API sağlık kontrolü — Render.com için"""
    return {"durum": "sağlıklı", "zaman": datetime.now().isoformat()}


# ─────────────────────────────────────────
# LOKAL ÇALIŞTIRMA
# ─────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
