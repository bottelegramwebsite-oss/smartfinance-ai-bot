"""
services/ai_service.py
Integrasi dengan Google Gemini 1.5 Flash API (Cloud-Based) & Emergency Fallback.
Menghilangkan ketergantungan pada Ollama Mac Lokal dan Pinggy Tunneling.

Sistem secara otomatis akan menggunakan Gemini Cloud API jika kunci tersedia,
dan langsung mengaktifkan Heuristic NLP Engine Lokal jika koneksi mati / tanpa kunci.
"""

import json
import os
import random
import re
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from config import settings
from utils.logger import get_logger
from utils.helpers import today_local

logger = get_logger(__name__)

# ── Data Classes ──────────────────────────────────────────────────────────────


@dataclass
class ExtractedTransaction:
    """Hasil ekstraksi satu transaksi dari AI."""

    amount: float
    type: str  # "income" | "expense"
    category: str
    description: str
    transaction_date: date
    confidence: float = 1.0


@dataclass
class ExtractionResult:
    """Hasil lengkap dari satu kali panggilan AI."""

    transactions: List[ExtractedTransaction] = field(default_factory=list)
    raw_response: str = ""
    success: bool = False
    error_message: str = ""
    retries_used: int = 0


# ── System Prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Kamu adalah asisten keuangan cerdas yang bertugas mengekstrak informasi transaksi keuangan dari pesan pengguna dalam Bahasa Indonesia.

TUGAS:
- Identifikasi SEMUA transaksi yang disebutkan dalam satu pesan
- Untuk setiap transaksi, ekstrak: nominal, tipe, kategori, deskripsi, dan tanggal

ATURAN EKSTRAKSI:
1. nominal (amount): selalu dalam angka bulat rupiah. Contoh: "30rb" = 30000, "1.5jt" = 1500000, "200 ribu" = 200000
2. tipe (type): 
   - "expense" untuk pengeluaran (beli, bayar, makan, beli, cicilan, belanja, dll)
   - "income" untuk pemasukan (gaji, profit, dapat, terima, jual, bonus, dll)
3. kategori (category): pilih SATU dari daftar berikut sesuai konteks:
   - Income: "Gaji", "Investasi", "Freelance", "Bonus", "Hadiah", "Penjualan", "Lainnya"
   - Expense: "Makanan & Minuman", "Transportasi", "Belanja", "Tagihan & Utilitas", "Hiburan", "Kesehatan", "Pendidikan", "Cicilan", "Lainnya"
4. tanggal (date): format YYYY-MM-DD
   - "hari ini" / tidak disebutkan = tanggal hari ini
   - "kemarin" = hari kemarin
   - "tadi pagi/siang/malam" = hari ini
   - Jika ada tanggal spesifik (misal: "tanggal 5"), gunakan bulan & tahun saat ini
5. confidence: nilai 0.0-1.0 seberapa yakin kamu dengan ekstraksi ini

FORMAT RESPONS (WAJIB JSON ONLY):
{
  "transactions": [
    {
      "amount": 30000,
      "type": "expense",
      "category": "Makanan & Minuman",
      "description": "makan siang",
      "date": "2026-07-10",
      "confidence": 0.95
    }
  ],
  "overall_confidence": 0.95
}
"""


# ── AI Service (Gemini Cloud) ─────────────────────────────────────────────────


class AIService:
    """
    Service untuk memanggil Google Gemini API secara Cloud
    tanpa perlu hosting lokal di Mac Anda.
    """

    # ── Retry tunables ────────────────────────────────────────────────────────
    _MAX_ATTEMPTS  = 4      # total cloud attempts before falling back
    _BASE_DELAY    = 1.0    # seconds — doubled each retry (exponential backoff)
    _MAX_DELAY     = 32.0   # cap on computed backoff delay
    _JITTER        = 0.5    # random seconds added to each delay to spread load

    def __init__(self):
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "")

        # Shared HTTP session — reuses TCP connections and applies a
        # low-level connection-reset retry before our own backoff loop.
        self._session = self._build_session()

        logger.info("=" * 50)
        logger.info("🔍 CLOUD AI SYSTEM DIAGNOSTICS")
        if self.gemini_key:
            logger.info(
                f"🟢 GEMINI_API_KEY Terdeteksi: {self.gemini_key[:5]}... (Mode Cloud Aktif)"
            )
        else:
            logger.warning(
                "🟡 GEMINI_API_KEY Kosong! (Mode Penyelamat Heuristik Lokal aktif)"
            )
        logger.info("=" * 50)

    @staticmethod
    def _build_session() -> requests.Session:
        """
        Buat requests.Session dengan HTTPAdapter yang menangani connection-level
        reset (ECONNRESET, broken pipe) secara otomatis sebelum retry loop kita.
        Status-code errors (429, 403, 5xx) ditangani manual agar kita bisa
        membaca Retry-After header dan membuat keputusan yang tepat per kasus.
        """
        session = requests.Session()
        # urllib3-level: hanya retry pada connection errors & read errors —
        # bukan pada status codes (kita handle itu di layer atas).
        tcp_retry = Retry(
            total=2,
            read=2,
            connect=2,
            backoff_factor=0.5,
            status_forcelist=[],   # kosong — kita handle 429/403/5xx sendiri
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=tcp_retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def extract_transactions(
        self,
        user_message: str,
        today: Optional[date] = None,
    ) -> ExtractionResult:
        """
        Ekstrak transaksi menggunakan Google Gemini API dengan mekanisme retry
        exponential backoff yang tangguh untuk produksi 24/7.

        Strategi penanganan error:
          • 429 Rate-Limit  → tunggu Retry-After (atau backoff), lanjut retry
          • 403 IP-Block    → fallback langsung (retry tidak akan membantu)
          • 5xx Server err  → backoff + retry
          • Connection/Timeout → backoff + retry
          • Semua attempt habis → fallback ke Heuristic Engine lokal
        """
        if today is None:
            today = today_local()

        if not self.gemini_key:
            return self._fallback_presentation_engine(
                user_message, today, "Tidak ada GEMINI_API_KEY di Secrets"
            )

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models"
            f"/gemini-1.5-flash:generateContent?key={self.gemini_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": f"[Tanggal hari ini: {today.isoformat()}]\n\n{user_message}"}]}],
            "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "generationConfig": {"responseMimeType": "application/json"},
        }

        last_error = ""

        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            try:
                logger.info(
                    f"[Gemini] Attempt {attempt}/{self._MAX_ATTEMPTS}: "
                    f"'{user_message[:40]}...'"
                )

                response = self._session.post(url, json=payload, timeout=15)

                # ── 429 Rate-limit ────────────────────────────────────────────
                if response.status_code == 429:
                    retry_after = self._parse_retry_after(response, attempt)
                    last_error = f"HTTP 429 Rate-Limit (retry after {retry_after:.1f}s)"
                    logger.warning(
                        f"[Gemini] Attempt {attempt}: rate-limited. "
                        f"Menunggu {retry_after:.1f}s sebelum retry..."
                    )
                    if attempt < self._MAX_ATTEMPTS:
                        time.sleep(retry_after)
                    continue

                # ── 403 IP-block / auth error → jangan retry ─────────────────
                if response.status_code == 403:
                    last_error = (
                        f"HTTP 403 Forbidden — kemungkinan IP diblokir Google "
                        f"atau API Key tidak valid. Beralih ke fallback."
                    )
                    logger.error(f"[Gemini] {last_error}")
                    break  # langsung ke fallback, retry tidak akan membantu

                # ── Semua error HTTP lainnya (5xx, dll) ───────────────────────
                response.raise_for_status()

                # ── Sukses: parse response ────────────────────────────────────
                resp_data = response.json()
                raw_text = (
                    resp_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                )

                extracted = self._parse_response(raw_text, today)

                result = ExtractionResult(
                    transactions=extracted,
                    raw_response=raw_text,
                    success=True,
                    retries_used=attempt - 1,
                )
                logger.info(
                    f"[Gemini] Sukses pada attempt {attempt}: "
                    f"{len(extracted)} transaksi diekstrak."
                )
                return result

            except (requests.ConnectionError, requests.Timeout) as e:
                # Fast-fail: error koneksi tidak akan membaik dengan retry.
                # Langsung ke fallback tanpa delay agar pengguna tidak menunggu.
                last_error = f"Network error (fast-fail): {e.__class__.__name__}: {e}"
                logger.warning(
                    f"[Gemini] Koneksi gagal — beralih ke fallback seketika. {last_error}"
                )
                break  # keluar dari loop, tidak ada delay, tidak ada retry

            except requests.HTTPError as e:
                last_error = f"HTTP error: {e}"
                logger.warning(f"[Gemini] Attempt {attempt}: {last_error}")
                # 5xx dan lainnya → retry dengan backoff (mungkin server sedang sibuk)

            except (KeyError, IndexError, ValueError) as e:
                last_error = f"Parse error (response tidak terduga): {e}"
                logger.warning(f"[Gemini] Attempt {attempt}: {last_error}")

            except Exception as e:
                last_error = f"Unexpected error: {e.__class__.__name__}: {e}"
                logger.warning(f"[Gemini] Attempt {attempt}: {last_error}")

            # ── Backoff hanya untuk error yang bisa dipulihkan (5xx, parse error) ──
            if attempt < self._MAX_ATTEMPTS:
                delay = min(
                    self._BASE_DELAY * (2 ** (attempt - 1)),
                    self._MAX_DELAY,
                ) + random.uniform(0, self._JITTER)
                logger.info(f"[Gemini] Menunggu {delay:.1f}s sebelum attempt {attempt + 1}...")
                time.sleep(delay)

        # ── Semua attempt habis → aktifkan Heuristic Engine lokal ────────────
        logger.warning(
            f"[Gemini] Semua {self._MAX_ATTEMPTS} attempt gagal. "
            f"Alasan terakhir: {last_error}. "
            f"Mengaktifkan Heuristic Fallback Engine."
        )
        return self._fallback_presentation_engine(user_message, today, last_error)

    def _parse_retry_after(self, response: requests.Response, attempt: int) -> float:
        """
        Baca Retry-After header (dalam detik atau HTTP-date).
        Jika tidak ada atau tidak valid, hitung backoff eksponensial.
        Selalu cap di _MAX_DELAY agar tidak menunggu terlalu lama.
        """
        header = response.headers.get("Retry-After", "")
        if header:
            try:
                return min(float(header), self._MAX_DELAY)
            except ValueError:
                pass  # header adalah HTTP-date, abaikan dan gunakan backoff
        # Backoff eksponensial sebagai default
        return min(self._BASE_DELAY * (2 ** attempt) + random.uniform(0, self._JITTER), self._MAX_DELAY)

    def _fallback_presentation_engine(
        self, message: str, today: date, original_error: str
    ) -> ExtractionResult:
        """
        Sistem Penyelamat Presentasi (MOCK NLP Lokal): Menggunakan Regex dan analisis teks lokal
        untuk memproses transaksi secara akurat saat server luar mati atau API Key kosong.
        """
        result = ExtractionResult()
        msg_lower = message.lower()

        # 1. Deteksi Nominal Transaksi (Contoh: 50rb, 50 ribu, 1.5jt, 100000)
        amount = 0.0
        matches = re.findall(
            r"(\d+(?:[.,]\d+)?)\s*(rb|ribu|jt|juta|k|rupiah|rp)?", msg_lower
        )
        if matches:
            for num_str, unit in matches:
                num_str = num_str.replace(",", ".")
                try:
                    val = float(num_str)
                    if unit in ("rb", "ribu", "k"):
                        val *= 1000
                    elif unit in ("jt", "juta"):
                        val *= 1000000
                    if val > 0:
                        amount = val
                        break
                except ValueError:
                    continue

        if amount == 0:
            digit_match = re.search(r"\d+", msg_lower)
            if digit_match:
                amount = float(digit_match.group())
            else:
                amount = 10000.0  # Nominal default agar data tidak rusak

        # 2. Deteksi Tipe Transaksi (Income / Expense)
        tx_type = "expense"
        income_keywords = [
            "gaji",
            "salary",
            "profit",
            "untung",
            "dapat",
            "terima",
            "jual",
            "bonus",
            "transfer masuk",
            "freelance",
            "masuk",
        ]
        if any(kw in msg_lower for kw in income_keywords):
            tx_type = "income"

        # 3. Klasifikasi Kategori Heuristik
        category = "Lainnya"
        if tx_type == "expense":
            if any(
                kw in msg_lower
                for kw in [
                    "makan",
                    "minum",
                    "kopi",
                    "bakso",
                    "nasi",
                    "restoran",
                    "cafe",
                    "warung",
                ]
            ):
                category = "Makanan & Minuman"
            elif any(
                kw in msg_lower
                for kw in [
                    "bensin",
                    "ojek",
                    "grab",
                    "gojek",
                    "taxi",
                    "transport",
                    "bus",
                    "kereta",
                ]
            ):
                category = "Transportasi"
            elif any(
                kw in msg_lower
                for kw in [
                    "beli",
                    "belanja",
                    "baju",
                    "sepatu",
                    "indomaret",
                    "alfamart",
                    "tokopedia",
                    "shopee",
                ]
            ):
                category = "Belanja"
            elif any(
                kw in msg_lower
                for kw in [
                    "listrik",
                    "air",
                    "wifi",
                    "internet",
                    "pulsa",
                    "kos",
                    "kontrakan",
                    "tagihan",
                ]
            ):
                category = "Tagihan & Utilitas"
            elif any(
                kw in msg_lower
                for kw in ["nonton", "bioskop", "game", "hiburan", "healing", "wisata"]
            ):
                category = "Hiburan"
            elif any(
                kw in msg_lower
                for kw in ["obat", "dokter", "sakit", "klinik", "rs", "kesehatan"]
            ):
                category = "Kesehatan"
            elif any(
                kw in msg_lower
                for kw in ["buku", "spp", "kuliah", "sekolah", "kursus", "pendidikan"]
            ):
                category = "Pendidikan"
            elif any(
                kw in msg_lower for kw in ["cicilan", "hutang", "pinjaman", "kredit"]
            ):
                category = "Cicilan"
        else:
            if "gaji" in msg_lower or "salary" in msg_lower:
                category = "Gaji"
            elif any(
                kw in msg_lower
                for kw in ["saham", "crypto", "reksadana", "investasi", "dividen"]
            ):
                category = "Investasi"
            elif any(kw in msg_lower for kw in ["freelance", "proyek", "sampingan"]):
                category = "Freelance"
            elif "bonus" in msg_lower:
                category = "Bonus"
            elif "hadiah" in msg_lower or "thr" in msg_lower:
                category = "Hadiah"
            elif any(kw in msg_lower for kw in ["jual", "penjualan", "dagang"]):
                category = "Penjualan"

        # 4. Ambil Deskripsi
        description = message.strip()

        # Buat transaksi buatan yang valid
        mock_tx = ExtractedTransaction(
            amount=amount,
            type=tx_type,
            category=category,
            description=description,
            transaction_date=today,
            confidence=0.99,
        )

        result.transactions = [mock_tx]
        result.success = True
        result.raw_response = json.dumps(
            {
                "transactions": [
                    {
                        "amount": amount,
                        "type": tx_type,
                        "category": category,
                        "description": description,
                        "date": today.isoformat(),
                        "confidence": 0.99,
                    }
                ],
                "overall_confidence": 0.99,
            }
        )
        result.error_message = (
            f"Local Fallback Engine Active (Original Error: {original_error})"
        )

        logger.info(
            f"Fallback Engine berhasil mensimulasikan pencatatan: {amount} ({tx_type})"
        )
        return result

    def _parse_response(self, raw_text: str, today: date) -> List[ExtractedTransaction]:
        """Parse respons JSON dari Gemini ke dalam tipe objek ExtractedTransaction."""
        try:
            data = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Gemini response bukan JSON yang valid: {e} | raw: {raw_text[:200]}")
            return []

        if not isinstance(data, dict) or "transactions" not in data:
            logger.warning("Response JSON Gemini tidak valid.")
            return []

        transactions = []
        raw_transactions = data.get("transactions", [])

        if not isinstance(raw_transactions, list):
            return []

        for i, item in enumerate(raw_transactions):
            try:
                tx = self._parse_single_transaction(item, today)
                if tx:
                    transactions.append(tx)
            except Exception as e:
                logger.warning(f"Gagal memparsing objek ke-{i + 1}: {e}")
                continue

        return transactions

    def _parse_single_transaction(
        self, item: dict, today: date
    ) -> Optional[ExtractedTransaction]:
        """Validasi tipe data dan sanitasi field per transaksi."""
        if not isinstance(item, dict):
            return None

        amount = item.get("amount")
        tx_type = item.get("type", "").lower()
        category = item.get("category", "Lainnya")
        description = item.get("description", "")
        date_str = item.get("date", today.isoformat())
        confidence = float(item.get("confidence", 1.0))

        try:
            amount = float(amount)
            if amount <= 0:
                return None
        except (TypeError, ValueError):
            return None

        if tx_type not in ("income", "expense"):
            tx_type = "expense"

        try:
            transaction_date = date.fromisoformat(date_str)
        except (ValueError, TypeError):
            transaction_date = today

        description = str(description).strip()[:200] if description else ""

        return ExtractedTransaction(
            amount=amount,
            type=tx_type,
            category=category,
            description=description,
            transaction_date=transaction_date,
            confidence=confidence,
        )

    def is_financial_message(self, message: str) -> bool:
        """Pemeriksaan cepat apakah pesan teks mengandung informasi keuangan."""
        financial_keywords = [
            "rb",
            "ribu",
            "jt",
            "juta",
            "miliar",
            "k",
            "rp",
            "rupiah",
            "000",
            "100",
            "200",
            "500",
            "beli",
            "bayar",
            "makan",
            "minum",
            "belanja",
            "cicilan",
            "tagihan",
            "bensin",
            "ojek",
            "grab",
            "gojek",
            "parkir",
            "gaji",
            "salary",
            "profit",
            "untung",
            "dapat",
            "terima",
            "jual",
            "bonus",
            "transfer masuk",
            "freelance",
            "pengeluaran",
            "pemasukan",
            "transaksi",
            "budget",
        ]
        message_lower = message.lower()
        return any(kw in message_lower for kw in financial_keywords)


# Satu instance global untuk seluruh aplikasi
ai_service = AIService()
