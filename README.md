# Trendyol Rakip Takip API

Trendyol satıcıları için rakip fiyat takibi ve BuyBox fırsat analizi.

## Kurulum

### 1. Lokal Test
```bash
pip install -r requirements.txt
python main.py
# API: http://localhost:8000
```

### 2. Render.com Deploy
1. GitHub'a yükle
2. render.com → New Web Service → GitHub repo bağla
3. render.yaml otomatik okunur
4. Environment variables ekle (Supabase bilgileri)

## API Kullanımı

### Ürün Sorgula
```
GET /urun?url=https://www.trendyol.com/...
```

### Takip Ekle
```
POST /takip-ekle
{
  "url": "https://www.trendyol.com/...",
  "kullanici_id": "user123",
  "hedef_fiyat": 150.0
}
```

### BuyBox Fırsat Analizi
```
GET /buybox?url=https://www.trendyol.com/kadin-giyim-x-c50003
```

### Sağlık Kontrolü
```
GET /saglik
```

## Sonraki Adımlar
- [ ] Supabase entegrasyonu
- [ ] Zamanlanmış fiyat kontrolü (APScheduler)
- [ ] Email bildirimi (SendGrid)
- [ ] Bubble arayüz bağlantısı
