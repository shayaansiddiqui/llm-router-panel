"""Versioned objective starter cases, not model ratings or a model catalog.

Exact-answer microtasks provide limited initial coverage, not a comprehensive
benchmark for production coding/reasoning. Add audited domain evaluations later.
"""
from dataclasses import dataclass
import hashlib
import json
import unicodedata


@dataclass(frozen=True)
class Case:
    id: str
    prompt: str
    answers: tuple[str, ...]


CASES = (
    Case('greeting-01', 'Hi', ('hello', 'hi', 'hey')),
    Case('greeting-02', 'Hello', ('hello', 'hi', 'hey')),
    Case('greeting-03', 'Hey', ('hello', 'hi', 'hey')),
    Case('greeting-04', 'Hi there', ('hello', 'hi', 'hey')),
    Case('greeting-05', 'Hello there', ('hello', 'hi', 'hey')),
    Case('greeting-06', 'Merhaba', ('merhaba', 'selam')),
    Case('greeting-07', 'Selam', ('merhaba', 'selam')),
    Case('greeting-08', 'Merhabalar', ('merhaba', 'selam')),
    Case('greeting-09', 'Selamlar', ('merhaba', 'selam')),
    Case('greeting-10', 'Günaydın', ('merhaba', 'selam', 'gunaydin')),
    Case('code-01', 'Python list(range(2, 9, 2)) ifadesi kaç eleman üretir? Yalnızca sayıyı ver.', ('4',)),
    Case('code-02', 'Python x=[1,2]; y=x; y.append(3) kodundan sonra len(x) kaçtır? Yalnızca sayıyı ver.', ('3',)),
    Case('code-03', 'Python len({"a": 1, "b": 2, "a": 3}) sonucu kaçtır? Yalnızca sayıyı ver.', ('2',)),
    Case('code-04', 'Python sum(i*i for i in range(4)) sonucu kaçtır? Yalnızca sayıyı ver.', ('14',)),
    Case('code-05', 'Python bool([]) sonucu nedir? Yalnızca true veya false ver.', ('false',)),
    Case('code-06', 'Python [1,2,3,4][1:3] listesinin eleman toplamı kaçtır? Yalnızca sayıyı ver.', ('5',)),
    Case('code-07', 'Python len(set([1,1,2,3,3])) sonucu kaçtır? Yalnızca sayıyı ver.', ('3',)),
    Case('code-08', 'Python 17 // 5 sonucu kaçtır? Yalnızca sayıyı ver.', ('3',)),
    Case('reason-01', 'Bir mağazada 18 ürün var. 7 ürün satılıyor, sonra 4 yeni ürün geliyor. Kaç ürün kalır? Yalnızca sayıyı ver.', ('15',)),
    Case('reason-02', 'Bir ürün 80 liradır. Yüzde 25 indirim sonrası fiyatı kaç liradır? Yalnızca sayıyı ver.', ('60',)),
    Case('reason-03', 'Saatte 60 kilometre giden araç 150 kilometreyi kaç dakikada alır? Yalnızca sayıyı ver.', ('150',)),
    Case('reason-04', '3 işçi aynı hızda 6 günde işi bitiriyor. 6 işçi kaç günde bitirir? Yalnızca sayıyı ver.', ('3',)),
    Case('reason-05', '5 kutunun her birinde 8 kalem var. 13 kalem çıkarılırsa kaç kalem kalır? Yalnızca sayıyı ver.', ('27',)),
    Case('reason-06', '2, 6, 18, 54 dizisinde sıradaki sayı nedir? Yalnızca sayıyı ver.', ('162',)),
    Case('reason-07', 'Bir etkinlikte 12 kişinin her biri diğerleriyle bir kez tokalaşıyor. Toplam kaç tokalaşma olur? Yalnızca sayıyı ver.', ('66',)),
    Case('reason-08', 'Bir sayının üç katının 5 fazlası 26. Sayı kaçtır? Yalnızca sayıyı ver.', ('7',)),
    Case('extract-01', 'Metni özetlemek için teslim tarihini çıkar: Sipariş pazartesi alındı, teslimat cuma yapılacak. Yalnızca teslim gününü ver.', ('cuma',)),
    Case('extract-02', 'Metindeki görev sahibini çıkar: Ayşe raporu yazacak, Mehmet raporu onaylayacak. Raporu kim yazacak? Yalnızca adı ver.', ('ayşe',)),
    Case('extract-03', 'Kısa metindeki son durumu çıkar: Sunucu önce kapalıydı. Sonra açıldı ve şu anda çalışıyor. Sunucu açık mı? Yalnızca evet veya hayır ver.', ('evet',)),
    Case('extract-04', 'Metindeki sipariş adedini çıkar: Fiyat 250 lira, sipariş 12 adet, teslim süresi 3 gün. Yalnızca adet sayısını ver.', ('12',)),
    Case('extract-05', 'Metindeki şehri çıkar: Ece Ankara ofisinde, Can İzmir ofisinde çalışıyor. Can hangi şehirde? Yalnızca şehri ver.', ('izmir',)),
    Case('extract-06', 'Metni okuyup tutarı çıkar: Fatura toplamı 900 lira, bunun 300 lirası ödendi. Ödenmemiş tutar kaçtır? Yalnızca sayıyı ver.', ('600',)),
    Case('extract-07', 'Metindeki toplantı saatini çıkar: Kahvaltı 08:00, toplantı 09:30, öğle yemeği 12:00. Yalnızca toplantı saatini ver.', ('09:30',)),
    Case('extract-08', 'Metni okuyup öncelikli görevi çıkar: Önce yedekle, ardından güncelle, en son yeniden başlat. İlk işlemi tek kelimeyle ver.', ('yedekle',)),
    Case('language-01', 'Translate the Turkish word kedi into English. Return only the translated word.', ('cat',)),
    Case('language-02', 'Translate the Turkish word köpek into English. Return only the translated word.', ('dog',)),
    Case('language-03', 'Translate the Turkish word kitap into English. Return only the translated word.', ('book',)),
    Case('language-04', 'Translate the Turkish word su into English. Return only the translated word.', ('water',)),
    Case('language-05', 'İngilizce red sözcüğünü Türkçeye çevir. Yalnızca çevrilen sözcüğü ver.', ('kırmızı',)),
    Case('language-06', 'İngilizce blue sözcüğünü Türkçeye çevir. Yalnızca çevrilen sözcüğü ver.', ('mavi',)),
    Case('language-07', 'İngilizce five sözcüğünü Türkçeye çevir. Yalnızca çevrilen sözcüğü ver.', ('beş',)),
    Case('language-08', 'İngilizce Monday sözcüğünü Türkçeye çevir. Yalnızca çevrilen sözcüğü ver.', ('pazartesi',)),
    Case('sql-advanced-01', 'PostgreSQL stok=1. İki Python transaction aynı stok değerini okuyup sipariş oluşturuyor. Okuma sırasında satırı kilitleyen SQL cümlesini yaz. Sadece kilit cümlesi.', ('select for update', 'for update', 'select ... for update')),
    Case('sql-advanced-02', 'PostgreSQL eşzamanlı siparişlerde stok eksiye düşmesin. UPDATE inventory SET stock=stock-1 WHERE id=1 AND stock>0 RETURNING stock sıfır satır döndürdü. Sipariş onaylanmalı mı? Yalnızca evet/hayır.', ('hayır',)),
    Case('sql-advanced-03', 'Python ödeme API aynı idempotency anahtarını eşzamanlı iki kez alıyor. PostgreSQL tablosunda anahtarın tek kaydı olmasını hangi constraint garanti eder? Yalnızca constraint adı.', ('unique', 'unique constraint')),
    Case('sql-advanced-04', 'PostgreSQL READ COMMITTED transaction iki sorguda aynı satırın farklı değerlerini okuyabilir mi? Eşzamanlı başka transaction commit ediyor. Yalnızca evet/hayır.', ('evet',)),
    Case('sql-advanced-05', 'PostgreSQL SERIALIZABLE sipariş transaction SQLSTATE 40001 aldı. Güvenli tekrar kapsamı hangisi: son sorgu mu, tüm transaction mı? Yalnızca kapsamı yaz.', ('tüm transaction', 'entire transaction', 'whole transaction')),
    Case('sql-advanced-06', 'Python API PostgreSQL sipariş commit etti, mesaj kuyruğuna yayınlamadan çöktü. Sipariş ve yayınlanacak olayı aynı DB transaction içinde saklayan desenin adını yaz.', ('transactional outbox', 'outbox')),
    Case('sql-advanced-07', 'PostgreSQL stok kilidi alınmış transaction içinde uzak ödeme servisini beklemek kilidin tutulma süresini artırır mı? Yalnızca evet/hayır.', ('evet',)),
    Case('sql-advanced-08', 'Ödeme servisi zaman aşımına uğradı. Python sipariş API ödemeyi kesin başarısız kabul edip yeniden farklı anahtarla çekebilir mi? Sonuç henüz bilinmiyor. Yalnızca evet/hayır.', ('hayır',)),
    Case('sql-advanced-09', 'PostgreSQL transaction A önce ürün 1 sonra 2 kilitliyor; B önce 2 sonra 1 kilitliyor. Kilitlerin döngüsel bekleyişinin adı nedir? Yalnızca teknik terim.', ('deadlock', 'kilitlenme')),
    Case('sql-advanced-10', 'Python API PostgreSQL transaction stok düşürüyor, sonra hata yüzünden ROLLBACK oluyor. Commit edilmemiş stok azalması kalıcı mı? Yalnızca evet/hayır.', ('hayır',)),
    Case('algorithm-advanced-01', 'Python asal sayı testi için her n değerinde 2 ile n-1 arasındaki tüm bölenler deneniyor. Tek sayıyı kontrol etmenin en kötü zaman karmaşıklığı nedir? Yalnızca Big-O.', ('o(n)',)),
    Case('algorithm-advanced-02', 'Python asal sayı testi 2 ile floor(sqrt(n)) arasındaki bölenleri dener. Tek n sayısını kontrol etmenin en kötü zaman karmaşıklığı nedir? Yalnızca Big-O.', ('o(sqrt(n))', 'o(n^0.5)', 'o(√n)')),
    Case('algorithm-advanced-03', 'Python ile 1..N aralığındaki bütün asalları bulan Eratosthenes eleğinde bool dizisi kullanılıyor. Ek bellek karmaşıklığı nedir? Yalnızca Big-O.', ('o(n)',)),
    Case('algorithm-advanced-04', 'Python kodunda sıralı dizide binary search her adımda aralığı yarıya indirir. En kötü arama zamanı nedir? Yalnızca Big-O.', ('o(log n)', 'o(log(n))')),
    Case('algorithm-advanced-05', 'Python heapq ile Dijkstra negatif ağırlıklı kenarlarda her zaman doğru en kısa yol üretir mi? Yalnızca evet/hayır.', ('hayır',)),
    Case('reason-advanced-01', 'Üç kutuda altın/altın, gümüş/gümüş, altın/gümüş var. Rastgele kutudan rastgele para altın çıktı. Aynı kutudaki diğerinin altın olma olasılığı? Yalnızca kesir.', ('2/3',)),
    Case('reason-advanced-02', 'Hastalık oranı %1. Test duyarlılığı %99, yanlış pozitif oranı %9. Pozitif kişinin hasta olma olasılığı? Yalnızca yüzde tam sayı.', ('10', '10%')),
    Case('reason-advanced-03', 'A Bden önce, B Cden önce tamamlanmalı. C Ayı bekliyor. Üç görevin bağımlılık grafiği döngülü mü? Yalnızca evet/hayır.', ('hayır',)),
    Case('reason-advanced-04', 'A Bden önce, B Cden önce, C Adan önce tamamlanmalı. Bu bağımlılıklar için topolojik sıralama mümkün mü? Yalnızca evet/hayır.', ('hayır',)),
    Case('reason-advanced-05', 'Bir sistemde iki bağımsız bileşenin çalışma olasılıkları 0.9 ve 0.8. Sistem ikisi de çalışırsa çalışıyor. Çalışma olasılığı? Yalnızca ondalık.', ('0.72', '0,72')),
    Case('security-advanced-01', 'Python PostgreSQL API sorguyu kullanıcı adıyla f-string birleştiriyor. SQL injection önlemek için değerleri sorgu parametresi olarak geçirmek yeterli mi? Yalnızca evet/hayır.', ('evet',)),
    Case('security-advanced-02', 'Python API JWT payload decode etti fakat imzayı doğrulamadı. Kullanıcı rolüne güvenerek admin yetkisi verebilir mi? Yalnızca evet/hayır.', ('hayır',)),
    Case('security-advanced-03', 'Python API kullanıcıdan URL alıp HTTP isteği yapıyor. 127.0.0.1 ve private IPye erişim engellenmedi. Bu saldırının teknik kısaltması nedir?', ('ssrf',)),
    Case('security-advanced-04', 'Web API CORS yalnızca güvenilir origin kabul ediyor. Bu ayar curl istemcisinin APIye ulaşmasını engeller mi? Yalnızca evet/hayır.', ('hayır',)),
    Case('security-advanced-05', 'Python web API parolaları salt olmadan SHA256 ile saklıyor. Parola depolamak için Argon2id uygun bir alternatif mi? Yalnızca evet/hayır.', ('evet',)),
)

SYSTEM = 'Return JSON only: {"answer":"your final short answer"}. Do not include explanations or reasoning. Follow the requested answer format.'
GENERATION_OPTIONS = {'temperature': 0, 'num_ctx': 4096, 'num_predict': 128, 'seed': 42}
ANSWER_SCHEMA = {'type': 'object', 'properties': {'answer': {'type': 'string'}},
                 'required': ['answer'], 'additionalProperties': False}
RUBRIC = 'starter-exact-answer-v1-' + hashlib.sha256(json.dumps({
    'cases': [case.__dict__ for case in CASES], 'system': SYSTEM,
    'generation_options': GENERATION_OPTIONS, 'format': ANSWER_SCHEMA,
    'grading': 'unicode-exact-microtask-or-short-greeting-prefix-v2',
    'latency_metric': 'ollama-prompt-eval-plus-generation-nanoseconds-v1',
}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def grade(response: str, case: Case) -> float:
    try:
        result = json.loads(response)
        if set(result) != {'answer'} or not isinstance(result['answer'], str):
            return 0.0
        def normalize(text):
            return ''.join(character for character in unicodedata.normalize('NFKD', text.strip().casefold().replace('ı', 'i'))
                           if not unicodedata.combining(character))
        answer = normalize(result['answer'])
        if case.id.startswith('greeting-'):
            # Objective, deliberately narrow greeting check; not a free-form
            # quality judge and never a runtime request-routing keyword rule.
            return float(len(answer) <= 200 and any(
                answer == normalize(expected) or any(answer.startswith(normalize(expected) + boundary)
                    for boundary in (' ', '.', '!', ',', '?')) for expected in case.answers))
        return float(answer in {normalize(expected) for expected in case.answers})
    except (ValueError, TypeError, AttributeError):
        return 0.0
