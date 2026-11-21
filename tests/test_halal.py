import pytest

from jobfinder.halal import banned_reason
from conftest import mk


@pytest.mark.parametrize("title,company,desc,reason", [
    # gambling
    ("Senior UX/UI Designer (iGaming)", "Компания скрыта", "", "gambling"),
    ("Data Scientist", "Компания скрыта (Сфера iGaming)", "", "gambling"),
    ("Медиабайер (Тизерный трафик, Betting)", "Лига Ставок", "", "gambling"),
    ("Java Developer", "Parimatch", "", "gambling"),
    ("Security Engineer", "Компания скрыта", "Мы разрабатываем ПО для iGaming.", "gambling"),
    ("Backend Developer", "Acme", "We build an online casino platform.", "gambling"),
    ("QA Engineer", "Acme", "Ведущий букмекер России.", "gambling"),
    # alcohol, pork, adult, drugs, tobacco
    ("Data Engineer", "Heineken", "", "alcohol"),
    ("Frontend Developer", "Acme", "We are a craft brewery with an online store.", "alcohol"),
    ("Backend Developer", "Acme", "Ведущий производитель алкогольной продукции.", "alcohol"),
    ("Product Manager", "Acme", "Our pork processing plants need software.", "pork"),
    ("Moderator", "Acme", "Платформа для вебкам моделей.", "adult"),
    ("AI Product Engineer", "Distru", "Distru is the #1 ERP in the cannabis industry.", "drugs"),
    ("Data Analyst", "Philip Morris International", "", "tobacco"),
    ("Маркетолог", "Acme", "Продаём вейпы и кальяны.", "tobacco"),
    # finance
    ("ML-инженер в команду GigaChat", "Сбер", "", "finance"),
    ("SRE-инженер", "Ozon Банк", "", "finance"),
    ("AppSec BP", "Aльфа-банк", "", "finance"),
    ("Senior Product Engineer", "Компания скрыта (Банк)", "", "finance"),
    ("DevSecOps-инженер", "МКБ", "", "finance"),
    ("Аналитик", "Acme", "Мы — российский частный системно значимый банк.", "finance"),
    ("Кредитный аналитик", "Acme", "", "finance"),
    ("Backend Engineer", "Acme", "Acme is a licensed insurance company.", "finance"),
    ("Go Developer", "Kaspi.kz", "", "finance"),
    # arbitrage, other
    ("Медиабайер", "Acme", "Команда арбитража трафика.", "arbitrage"),
    ("Quant Developer", "KSC Trading", "The focus has been on statistical arbitrage.", "arbitrage"),
    ("P2P-арбитражник", "Acme", "", "arbitrage"),
    ("Mobile Developer", "Acme", "Приложение для астрологов и таро.", "other"),
])
def test_banned(title, company, desc, reason):
    assert banned_reason(mk(title=title, company=company, description_text=desc)) == reason


@pytest.mark.parametrize("title,company,desc", [
    ("Flutter-разработчик", "hirix", ""),  # the framework, not Flutter Entertainment
    ("Optical Engineer", "Lawrence Livermore National Laboratory",
     "This includes testing for use of marijuana as Federal Law applies to us."),
    ("Системный аналитик", "Top Selection", "Арбитраж расхождений «дефект реализации»."),
    ("Юрист (арбитражные споры)", "Acme", "Представительство в арбитражном суде."),
    ("Freelance Developer", "Acme", "Experience with Stripe Connect and bank debits."),
    ("Fullstack Developer", "Acme", "Helps users evaluate loan scenarios against lender rules."),
    ("Private Equity Associate", "Acme", "Experience in investment banking or M&A."),
    ("Менеджер по продукту", "Acme", "Азартный и целеустремлённый, любишь результат."),
    ("Scrum Master", "Acme", "Ceremonies: planning poker, retros."),
    ("Backend Engineer", "Acme", "Smoke and tobacco-free campus. Drug and alcohol test required."),
    ("Wine/Proton Developer", "Valve", "Work on Wine compatibility layer."),
    ("DevOps", "Acme", "Настройка коллектора метрик OpenTelemetry."),
    ("Python Developer", "Acme", "ДМС, страхование жизни, компенсация спорта."),
    ("Backend Developer", "Shop", "Интеграция со СберПэй и Т-Банком, оплата через BNPL."),
    ("Trader Assistant Developer", "Acme", "Crypto exchange, spot and futures trading."),
    ("Music Streaming Engineer", "Acme", "Dating app and music streaming."),
    ("Data Engineer", "Компания XXX", ""),
])
def test_not_banned(title, company, desc):
    assert banned_reason(mk(title=title, company=company, description_text=desc)) is None
