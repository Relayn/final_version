import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
import sqlite3
from time import sleep
from bs4 import BeautifulSoup


FL_BASE_URL = "https://www.fl.ru"
FL_SEARCH_URL = f"{FL_BASE_URL}/projects/"
REQUEST_DELAY = 1.0  # Увеличиваем задержку для избежания блокировки
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


@dataclass
class Vacancy:
    title: str
    company: str
    location: str
    salary: Optional[str]
    description: str
    published_at: datetime
    source: str = "fl.ru"
    original_url: str = ""


class FLParser:
    def __init__(self):
        self._init_session()
        self._init_db()

    def _init_session(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3"
        })

    def _init_db(self):
        self.conn = sqlite3.connect("vacancies.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_table()

    def _create_table(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS vacancies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                salary TEXT,
                description TEXT,
                published_at DATETIME NOT NULL,
                source TEXT NOT NULL,
                original_url TEXT NOT NULL,
                UNIQUE(title, company, published_at)
            )
        """)
        self.conn.commit()

    def _parse_salary(self, text: str) -> Optional[str]:
        if not text or "Договорная" in text:
            return None
        return text.strip()

    def _parse_date(self, date_str: str) -> datetime:
        """Парсит дату в формате FL.ru"""
        try:
            # Пример: "сегодня в 14:30" или "вчера в 09:15"
            if "сегодня" in date_str:
                date_part = datetime.now().date()
            elif "вчера" in date_str:
                date_part = datetime.now().date() - timedelta(days=1)
            else:
                # Для других форматов может потребоваться дополнительная обработка
                return datetime.now()

            time_part = date_str.split()[-1]
            return datetime.combine(date_part, datetime.strptime(time_part, "%H:%M").time())
        except:
            return datetime.now()

    def _parse_vacancy_page(self, url: str) -> Dict:
        """Парсит страницу вакансии"""
        try:
            response = self.session.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            description = soup.find('div', {'class': 'b-layout__txt'})
            if description:
                description = description.get_text('\n', strip=True)
            else:
                description = ""

            return {
                'description': description
            }
        except Exception as e:
            print(f"Ошибка при парсинге страницы вакансии: {e}")
            return {'description': ''}

    def _save_vacancy(self, vacancy: Vacancy):
        try:
            self.cursor.execute("""
                INSERT OR IGNORE INTO vacancies (
                    title, company, location, salary, 
                    description, published_at, source, original_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                vacancy.title,
                vacancy.company,
                vacancy.location,
                vacancy.salary,
                vacancy.description,
                vacancy.published_at.isoformat(),
                vacancy.source,
                vacancy.original_url,
            ))
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"Ошибка сохранения в БД: {e}")

    def parse_vacancies(self, search_query: str = "Python") -> List[Vacancy]:
        """Основной метод парсинга вакансий"""
        vacancies = []
        params = {
            "kind": "1",  # Проекты
            "sb": "1",  # Сортировка по дате
        }

        try:
            page = 1
            while True:
                params["page"] = page
                try:
                    response = self.session.get(FL_SEARCH_URL, params=params)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, 'html.parser')
                except requests.RequestException as e:
                    print(f"Ошибка запроса: {e}")
                    break

                projects = soup.find_all('div', {'class': 'project'})
                if not projects:
                    break

                for project in projects:
                    try:
                        title_elem = project.find('a', {'class': 'b-post__link'})
                        if not title_elem:
                            continue

                        title = title_elem.get_text(strip=True)
                        original_url = FL_BASE_URL + title_elem['href']

                        # Парсим дополнительные данные
                        price_elem = project.find('span', {'class': 'b-post__price'})
                        salary = self._parse_salary(price_elem.get_text(strip=True)) if price_elem else None

                        employer_elem = project.find('a', {'class': 'b-post__link_txt'})
                        company = employer_elem.get_text(strip=True) if employer_elem else "Частное лицо"

                        date_elem = project.find('span', {'class': 'b-post__time'})
                        date = self._parse_date(date_elem.get_text(strip=True)) if date_elem else datetime.now()

                        # Парсим страницу вакансии для получения описания
                        page_data = self._parse_vacancy_page(original_url)

                        vacancy = Vacancy(
                            title=title,
                            company=company,
                            location="Удалённая работа",  # FL.ru в основном для удалёнки
                            salary=salary,
                            description=page_data['description'],
                            published_at=date,
                            original_url=original_url
                        )
                        vacancies.append(vacancy)
                        self._save_vacancy(vacancy)
                    except Exception as e:
                        print(f"Пропущена вакансия из-за ошибки в данных: {e}")

                page += 1
                sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"Критическая ошибка парсинга: {e}")
        finally:
            return vacancies

    def __del__(self):
        if hasattr(self, "session"):
            self.session.close()
        if hasattr(self, "conn"):
            self.conn.close()