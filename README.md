# adkworkshop.com — ADK Workshop sitesi

Eserler `works\` klasörüne konur, **`yayinla.bat`** çift tıklanır: site yeniden üretilir ve GitHub'a gönderilir
(1–2 dakika içinde https://adkworkshop.com güncellenir). Göndermeden bakmak için **`onizle.bat`**.

## Eser ekleme

```
works\
  01-digital-art\                ← kategori (baştaki sayı sırayı belirler, sitede görünmez)
    _category.txt                ← (isteğe bağlı) kategorinin adı:  en: Digital Art / tr: Dijital Sanat
    2024-05_red-dragon.jpg       ← tek resimli eser (baştaki tarih sıralama ve yıl için)
    2024-05_red-dragon.txt       ← (isteğe bağlı) bilgiler, aşağıda
    2023-11_orc-warlord\         ← çok resimli eser: klasör; ilk resim (ada göre) kapak
      1.jpg  2.jpg  3.jpg
      info.txt
  02-miniatures\
  03-3d-prints\
```

- Resim türleri: JPG, PNG, WebP, GIF, TIFF, BMP. Büyük orijinaller sorun değil: site için 640 ve 1600 piksellik
  WebP kopyaları üretilir, **EXIF/GPS bilgisi atılır**. Orijinaller GitHub'a gönderilmez (`works\` .gitignore'da).
- Bilgi dosyası yoksa başlık dosya adından gelir: `2024-05_red-dragon` → "Red Dragon", yıl 2024.
- Bir eseri kaldırmak için resmini `works\`'ten silip `yayinla.bat`; sitedeki kopyaları da silinir.

### Bilgi dosyası (`.txt`, UTF-8)

```
title: Red Dragon
başlık: Kızıl Ejderha
year: 2021
featured: evet
tags: dragon, concept art
desc: Concept painting for a sculpt.
Birden çok satır olabilir.
açıklama: Bir heykel için konsept çizim.
```

Hepsi isteğe bağlı. `featured: evet` olanlar ana sayfadaki "Seçilmiş işler"de önce çıkar (kalan yer en yeni işlerle
dolar). Türkçe alan yoksa İngilizcesi kullanılır. Çok resimli eserde kapağı değiştirmek için `kapak: 3.jpg`.

## Site ayarları — `site.json`

Ad, slogan (`tagline`), hakkında metni (`about`, paragraflar `\n\n` ile), e-posta, sosyal bağlantılar
(`links`; adresi boş olan görünmez), ana sayfadaki eser sayısı (`featured_count`) ve ürünler (`products`, 3D Vault).
`works_dir`: eser klasörü başka bir yerde olabilir, ör. Google Drive: `"G:\\My Drive\\ADK Works"`.

## Yapı

- `build.py` — üretici (Python + Pillow). `--works <klasör> --out <klasör>` ile deneme.
- `theme\` — stil, betik, favicon (`docs\assets\`'e kopyalanır).
- `docs\` — üretilen site (elle düzenleme; her derlemede yeniden yazılır). GitHub Pages: main / docs.
- Barındırma: GitHub Pages (depo minotaurosk/adkworkshop), alan adı DNS'i Squarespace'te
  (Arsiv3D `store\dns-adkworkshop.md`). Depo ~1 GB'ı geçmemeli; `build.py` 800 MB'ta uyarır.
